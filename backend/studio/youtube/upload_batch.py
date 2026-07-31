from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from backend.studio.youtube.manifest import (
    ManifestError,
    SUPPORTED_LANGUAGES,
    UploadManifestEntry,
    load_manifest,
)


STATE_PATH = Path("backend/studio/work/youtube_upload_state.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely upload a batch of videos to YouTube."
    )
    parser.add_argument("--manifest", required=True, help="Path to batch JSON.")
    parser.add_argument(
        "--client-secrets",
        help="Path to installed-app OAuth client credentials.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform network uploads (the default is a dry run).",
    )
    parser.add_argument("--artist", help="Only process this artist or slug.")
    parser.add_argument(
        "--language",
        choices=sorted(SUPPORTED_LANGUAGES),
        help="Only process this language.",
    )
    parser.add_argument(
        "--privacy",
        choices=("private", "unlisted", "public"),
        default="private",
        help="Uploaded video privacy (default: private).",
    )
    parser.add_argument(
        "--confirm-public",
        action="store_true",
        help="Explicitly confirm that public uploads are intended.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Upload pairs already marked complete.",
    )
    args = parser.parse_args()

    if args.apply and not args.client_secrets:
        parser.error("--client-secrets is required with --apply")
    if args.apply and args.privacy == "public" and not args.confirm_public:
        parser.error("--confirm-public is required for public uploads")
    return args


def main() -> int:
    args = parse_args()
    try:
        entries = load_manifest(args.manifest)
        state = _load_state(STATE_PATH)
    except (ManifestError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2

    entries = [entry for entry in entries if _matches_filters(entry, args)]
    completed = state.setdefault("uploads", {})
    successes = 0
    failures = 0
    skipped = 0
    dry_run_ready = 0

    youtube = None
    needs_upload = any(
        args.force
        or completed.get(_state_key(entry), {}).get("status") != "complete"
        for entry in entries
    )
    if args.apply and needs_upload:
        try:
            from backend.studio.youtube.auth import get_credentials
            from backend.studio.youtube.uploader import build_youtube_service

            credentials = get_credentials(args.client_secrets)
            youtube = build_youtube_service(credentials)
        except Exception:
            print("ERROR: YouTube authentication failed.")
            print("Success: 0")
            print("Failure: 1")
            print("Skipped: 0")
            return 1

    for entry in entries:
        key = _state_key(entry)
        prior = completed.get(key, {})
        if prior.get("status") == "complete" and not args.force:
            skipped += 1
            print(f"SKIP     {entry.slug}/{entry.language_code} (complete)")
            continue

        if not args.apply:
            dry_run_ready += 1
            print(
                f"DRY RUN  {entry.slug}/{entry.language_code} "
                f"-> {args.privacy}"
            )
            continue

        try:
            assert youtube is not None
            video_id = prior.get("video_id") if not args.force else None
            if video_id and prior.get("status") == "video_uploaded":
                from backend.studio.youtube.uploader import set_thumbnail

                set_thumbnail(youtube, video_id, entry.thumbnail_path)
                url = prior["url"]
            else:
                from backend.studio.youtube.uploader import upload_video

                def save_video(uploaded_id: str, uploaded_url: str) -> None:
                    completed[key] = {
                        "status": "video_uploaded",
                        "video_id": uploaded_id,
                        "url": uploaded_url,
                    }
                    _save_state(STATE_PATH, state)

                video_id, url = upload_video(
                    youtube,
                    entry,
                    privacy_status=args.privacy,
                    on_video_uploaded=save_video,
                )

            completed[key] = {
                "status": "complete",
                "video_id": video_id,
                "url": url,
            }
            _save_state(STATE_PATH, state)
            successes += 1
            print(f"SUCCESS  {entry.slug}/{entry.language_code} {url}")
        except Exception as exc:
            failures += 1
            print(f"FAILURE  {entry.slug}/{entry.language_code}: {exc}")

    print()
    print("=" * 72)
    print(f"Success:       {successes}")
    print(f"Failure:       {failures}")
    print(f"Skipped:       {skipped}")
    if not args.apply:
        print(f"Dry-run ready: {dry_run_ready}")
        print("No network uploads were attempted. Add --apply to upload.")
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
    if not path.exists():
        return {"version": 1, "uploads": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid upload state JSON: {path}") from exc
    if not isinstance(state, dict) or not isinstance(state.get("uploads"), dict):
        raise ValueError(f"Invalid upload state structure: {path}")
    return state


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


if __name__ == "__main__":
    raise SystemExit(main())
