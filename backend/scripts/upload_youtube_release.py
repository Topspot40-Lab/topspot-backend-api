"""Explicit, restart-safe YouTube release publisher; dry-run by default."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

from backend.studio.youtube.manifest import ManifestError, load_manifest


STATE = Path("backend/studio/work/youtube_release_state.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--client-secrets", type=Path)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("backend/studio/work/youtube_release_audit.csv"),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and not args.client_secrets:
        parser.error("--client-secrets is required with --apply")
    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"ERROR: {exc}")
        return 2
    if not args.apply:
        _dry_run(manifest)
        _write_report(args.report, manifest, {})
        print(f"Audit report: {args.report}")
        return 0

    from backend.studio.youtube.auth import get_credentials
    from backend.studio.youtube.uploader import (
        add_to_playlist,
        build_youtube_service,
        ensure_playlist,
        set_thumbnail,
        upload_captions,
        upload_video,
    )

    youtube = build_youtube_service(get_credentials(args.client_secrets))
    state = _load_state()
    playlist_ids = state.setdefault("playlists", {})
    for spec in manifest.playlists:
        if spec.key not in playlist_ids:
            playlist_ids[spec.key] = ensure_playlist(youtube, spec)
        _save_state(state)
    uploads = state.setdefault("uploads", {})
    for spec in manifest.uploads:
        key = f"{spec.slug}|{spec.language_code}"
        record = uploads.setdefault(key, {})
        video_id = record.get("video_id")
        if not video_id:
            video_id = upload_video(
                youtube,
                spec,
                on_uploaded=lambda value, record=record: _record_video(state, record, value),
            )
            record["video_id"] = video_id
        set_thumbnail(youtube, video_id, spec.thumbnail_path)
        if spec.captions_path:
            upload_captions(youtube, video_id, spec.language_code, spec.captions_path)
        for playlist_key in spec.playlist_keys:
            add_to_playlist(youtube, playlist_ids[playlist_key], video_id)
        record.update(
            status="uploaded",
            scheduled_publish_at=spec.scheduled_publish_at.isoformat(),
            end_screen_status="manual_required" if spec.end_screen_required else "not_required",
        )
        _save_state(state)
        print(f"READY {key} https://www.youtube.com/watch?v={video_id}")
    _write_report(args.report, manifest, state.get("uploads", {}))
    print(f"Audit report: {args.report}")
    return 0


def _dry_run(manifest: Any) -> None:
    print(f"DRY RUN: {len(manifest.uploads)} private scheduled uploads")
    print(f"Playlists: {len(manifest.playlists)} (9 new + 1 existing English)")
    for spec in manifest.uploads:
        print(
            f"READY {spec.scheduled_publish_at.isoformat()} "
            f"{spec.slug}/{spec.language_code} -> {', '.join(spec.playlist_keys)}"
        )
    print("No network calls were made. Use --apply to create playlists and upload.")


def _load_state() -> dict[str, Any]:
    if not STATE.exists():
        return {"schema_version": 1, "playlists": {}, "uploads": {}}
    return json.loads(STATE.read_text(encoding="utf-8"))


def _save_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, STATE)


def _record_video(state: dict[str, Any], record: dict[str, Any], video_id: str) -> None:
    record.update(status="video_uploaded", video_id=video_id)
    _save_state(state)


def _write_report(path: Path, manifest: Any, state_uploads: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "slug",
                "collection",
                "language",
                "title",
                "scheduled_publish_at",
                "playlists",
                "thumbnail",
                "captions",
                "visual_approval",
                "upload_status",
                "end_screen_status",
                "youtube_url",
            ),
        )
        writer.writeheader()
        for spec in manifest.uploads:
            state = state_uploads.get(f"{spec.slug}|{spec.language_code}", {})
            video_id = state.get("video_id", "")
            writer.writerow(
                {
                    "slug": spec.slug,
                    "collection": spec.collection_key,
                    "language": spec.language_code,
                    "title": spec.title,
                    "scheduled_publish_at": spec.scheduled_publish_at.isoformat(),
                    "playlists": " | ".join(spec.playlist_keys),
                    "thumbnail": spec.thumbnail_path,
                    "captions": spec.captions_path or "",
                    "visual_approval": spec.visual_approval,
                    "upload_status": state.get("status", "dry_run_ready"),
                    "end_screen_status": state.get(
                        "end_screen_status",
                        "manual_required" if spec.end_screen_required else "not_required",
                    ),
                    "youtube_url": (
                        f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
                    ),
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
