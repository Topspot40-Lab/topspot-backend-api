from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.studio.youtube.manifest import (
    ManifestError,
    SUPPORTED_LANGUAGES,
    UploadManifestEntry,
    load_manifest,
)


DEFAULT_STATE_PATH = Path("backend/studio/work/youtube_upload_state.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update metadata for existing YouTube videos (dry run by default)."
    )
    parser.add_argument("--manifest", required=True, help="Path to batch JSON.")
    parser.add_argument(
        "--state",
        default=str(DEFAULT_STATE_PATH),
        help="Path to the existing YouTube upload state JSON.",
    )
    parser.add_argument(
        "--client-secrets",
        help="Path to installed-app OAuth client credentials.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Save metadata changes to YouTube (default: preview only).",
    )
    parser.add_argument("--artist", help="Only process this artist or slug.")
    parser.add_argument(
        "--language",
        choices=sorted(SUPPORTED_LANGUAGES),
        help="Only process this language.",
    )
    args = parser.parse_args()
    if args.apply and not args.client_secrets:
        parser.error("--client-secrets is required with --apply")
    return args


def main() -> int:
    args = parse_args()
    try:
        entries = load_manifest(args.manifest)
        state = _load_state(Path(args.state))
    except (ManifestError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2

    entries = [entry for entry in entries if _matches_filters(entry, args)]
    planned: list[tuple[UploadManifestEntry, str]] = []
    failures = 0

    for entry in entries:
        key = _state_key(entry)
        record = state["uploads"].get(key)
        video_id = record.get("video_id") if isinstance(record, dict) else None
        if not video_id:
            failures += 1
            print(f"FAILURE  {entry.slug}/{entry.language_code}: missing video ID")
            continue
        planned.append((entry, video_id))
        print(
            f"{'UPDATE' if args.apply else 'DRY RUN'}  "
            f"{entry.slug}/{entry.language_code} {video_id}\n"
            f"         title: {entry.title}\n"
            f"         tags:  {len(entry.tags)}"
        )

    if not args.apply:
        _print_summary(0, failures, len(planned), applied=False)
        return 1 if failures else 0

    try:
        from backend.studio.youtube.auth import get_credentials
        from backend.studio.youtube.uploader import build_youtube_service

        credentials = get_credentials(args.client_secrets)
        youtube = build_youtube_service(credentials)
    except Exception as exc:
        print(f"ERROR: YouTube authentication failed: {exc}")
        _print_summary(0, failures + 1, 0, applied=True)
        return 1

    successes = 0
    from backend.studio.youtube.uploader import update_video_metadata

    for entry, video_id in planned:
        try:
            update_video_metadata(youtube, video_id, entry)
            successes += 1
            print(f"SUCCESS  {entry.slug}/{entry.language_code} {video_id}")
        except Exception as exc:
            failures += 1
            print(f"FAILURE  {entry.slug}/{entry.language_code}: {exc}")

    _print_summary(successes, failures, 0, applied=True)
    return 1 if failures else 0


def _matches_filters(entry: UploadManifestEntry, args: argparse.Namespace) -> bool:
    if args.language and entry.language_code != args.language:
        return False
    if args.artist:
        artist = entry.artist or entry.slug
        if artist.casefold() != args.artist.casefold():
            return False
    return True


def _state_key(entry: UploadManifestEntry) -> str:
    return f"{entry.slug}|{entry.language_code}"


def _load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Upload state not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid upload state JSON: {path}") from exc
    if not isinstance(state, dict) or not isinstance(state.get("uploads"), dict):
        raise ValueError(f"Invalid upload state structure: {path}")
    return state


def _print_summary(
    successes: int,
    failures: int,
    previews: int,
    *,
    applied: bool,
) -> None:
    print()
    print("=" * 72)
    print(f"Success:  {successes}")
    print(f"Failure:  {failures}")
    if not applied:
        print(f"Ready:    {previews}")
        print("No YouTube changes were made. Add --apply after reviewing.")


if __name__ == "__main__":
    raise SystemExit(main())
