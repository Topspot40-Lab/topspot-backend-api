"""Explicit, quota-safe, restart-safe YouTube publisher; dry-run by default."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

from backend.studio.youtube.manifest import ManifestError, load_manifest


STATE = Path("backend/studio/work/youtube_release_state.json")
DEFAULT_MAX_UPLOADS = 15


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--client-secrets", type=Path)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("backend/studio/work/youtube_release_audit.csv"),
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true")
    action.add_argument("--authorize-only", action="store_true")
    parser.add_argument(
        "--max-uploads",
        type=_positive_int,
        default=DEFAULT_MAX_UPLOADS,
        help="maximum incomplete uploads to finish in one apply run (default: 15)",
    )
    args = parser.parse_args(argv)
    if (args.apply or args.authorize_only) and not args.client_secrets:
        parser.error("--client-secrets is required with --apply or --authorize-only")
    if not args.authorize_only and not args.manifest:
        parser.error("--manifest is required unless --authorize-only is used")

    if args.authorize_only:
        from backend.studio.youtube.auth import get_credentials

        get_credentials(args.client_secrets)
        print("OAuth authorization saved. No YouTube resources were changed.")
        return 0

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
    try:
        for spec in manifest.playlists:
            if spec.key not in playlist_ids:
                playlist_ids[spec.key] = ensure_playlist(youtube, spec)
                _save_state(state)
    except Exception as exc:
        return _handle_apply_error(exc, args.report, manifest, state)

    uploads = state.setdefault("uploads", {})
    batch = _select_batch(manifest.uploads, uploads, args.max_uploads)
    if not batch:
        _write_report(args.report, manifest, uploads)
        print("COMPLETE: all manifest uploads are already fully processed.")
        print(f"Audit report: {args.report}")
        return 0

    print(f"APPLY BATCH: up to {len(batch)} incomplete uploads (limit {args.max_uploads})")
    for spec in batch:
        key = f"{spec.slug}|{spec.language_code}"
        record = uploads.setdefault(key, {})
        try:
            video_id = record.get("video_id")
            if not video_id:
                video_id = upload_video(
                    youtube,
                    spec,
                    on_uploaded=lambda value, record=record: _record_video(
                        state, record, value
                    ),
                )
                record["video_id"] = video_id

            if not record.get("thumbnail_uploaded"):
                set_thumbnail(youtube, video_id, spec.thumbnail_path)
                record["thumbnail_uploaded"] = True
                _save_state(state)

            if spec.captions_path and not record.get("captions_uploaded"):
                upload_captions(
                    youtube, video_id, spec.language_code, spec.captions_path
                )
                record["captions_uploaded"] = True
                _save_state(state)

            completed_playlists = record.setdefault("playlist_keys", [])
            for playlist_key in spec.playlist_keys:
                if playlist_key in completed_playlists:
                    continue
                add_to_playlist(youtube, playlist_ids[playlist_key], video_id)
                completed_playlists.append(playlist_key)
                _save_state(state)

            record.update(
                status="uploaded",
                scheduled_publish_at=spec.scheduled_publish_at.isoformat(),
                end_screen_status=(
                    "manual_required" if spec.end_screen_required else "not_required"
                ),
            )
            _save_state(state)
            print(f"READY {key} https://www.youtube.com/watch?v={video_id}")
        except Exception as exc:
            return _handle_apply_error(exc, args.report, manifest, state)

    _write_report(args.report, manifest, uploads)
    remaining = sum(
        1
        for spec in manifest.uploads
        if uploads.get(f"{spec.slug}|{spec.language_code}", {}).get("status")
        != "uploaded"
    )
    print(f"BATCH COMPLETE: {len(batch)} processed; {remaining} remaining")
    print(f"Audit report: {args.report}")
    return 0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _select_batch(
    specs: Any, uploads: dict[str, Any], limit: int
) -> list[Any]:
    pending = [
        spec
        for spec in specs
        if uploads.get(f"{spec.slug}|{spec.language_code}", {}).get("status")
        != "uploaded"
    ]
    return pending[:limit]


def _handle_apply_error(
    exc: Exception, report: Path, manifest: Any, state: dict[str, Any]
) -> int:
    _save_state(state)
    _write_report(report, manifest, state.get("uploads", {}))
    if _is_quota_error(exc):
        print("QUOTA STOP: progress was saved safely; retry after the daily reset.")
        print(f"Audit report: {report}")
        return 3
    print(f"UPLOAD STOP: {exc}")
    print("Progress was saved safely. Resolve the error, then rerun the same command.")
    print(f"Audit report: {report}")
    return 4


def _is_quota_error(exc: Exception) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None)
    content = getattr(exc, "content", b"")
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    message = f"{exc} {content}".lower()
    return status in {403, 429} and any(
        marker in message
        for marker in ("quotaexceeded", "dailylimitexceeded", "rate limit")
    )


def _dry_run(manifest: Any) -> None:
    print(f"DRY RUN: {len(manifest.uploads)} private scheduled uploads")
    print(f"Playlists: {len(manifest.playlists)} (9 new + 3 existing language masters)")
    for spec in manifest.uploads:
        print(
            f"READY {spec.scheduled_publish_at.isoformat()} "
            f"{spec.slug}/{spec.language_code} -> {', '.join(spec.playlist_keys)}"
        )
    print("No network calls were made. Use --apply to create playlists and upload.")


def _load_state() -> dict[str, Any]:
    if not STATE.exists():
        return {"schema_version": 2, "playlists": {}, "uploads": {}}
    state = json.loads(STATE.read_text(encoding="utf-8"))
    state["schema_version"] = 2
    return state


def _save_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
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
            item_state = state_uploads.get(
                f"{spec.slug}|{spec.language_code}", {}
            )
            video_id = item_state.get("video_id", "")
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
                    "upload_status": item_state.get("status", "dry_run_ready"),
                    "end_screen_status": item_state.get(
                        "end_screen_status",
                        "manual_required"
                        if spec.end_screen_required
                        else "not_required",
                    ),
                    "youtube_url": (
                        f"https://www.youtube.com/watch?v={video_id}"
                        if video_id
                        else ""
                    ),
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
