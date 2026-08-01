from __future__ import annotations

import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from backend.studio.youtube.manifest import (
    YOUTUBE_THUMBNAIL_SIZE_LIMIT,
    UploadManifestEntry,
)


RETRIABLE_STATUS_CODES = frozenset({500, 502, 503, 504})
YOUTUBE_URL = "https://www.youtube.com/watch?v={video_id}"
THUMBNAIL_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def build_youtube_service(credentials: Any) -> Any:
    return build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def upload_video(
    youtube: Any,
    entry: UploadManifestEntry,
    privacy_status: str = "private",
    *,
    on_video_uploaded: Callable[[str, str], None] | None = None,
    max_retries: int = 5,
) -> tuple[str, str]:
    """Upload a video and its thumbnail, returning its ID and URL."""
    if privacy_status not in {"private", "unlisted", "public"}:
        raise ValueError(f"Invalid privacy status: {privacy_status}")
    video_name = entry.video_path.name.lower()
    if video_name in {"image_sequence.mp4", "opening.mp4"} or (
        video_name.endswith("_review.mp4")
    ):
        raise ValueError(f"Refusing to upload forbidden video: {video_name}")
    if entry.video_path.suffix.lower() != ".mp4":
        raise ValueError("YouTube video must be an MP4 file")
    if not entry.video_path.is_file() or entry.video_path.stat().st_size == 0:
        raise ValueError("YouTube video must be a non-empty file")

    media = MediaFileUpload(
        str(entry.video_path),
        mimetype="video/mp4",
        chunksize=-1,
        resumable=True,
    )
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": entry.title,
                "description": entry.description,
                "tags": list(entry.tags),
                "categoryId": entry.category_id,
                "defaultLanguage": entry.language_code,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": entry.made_for_kids,
            },
        },
        media_body=media,
        notifySubscribers=False,
    )

    response = _resumable_execute(request, max_retries=max_retries)
    video_id = response.get("id") if response else None
    if not video_id:
        raise RuntimeError("YouTube upload response did not contain a video ID")

    url = YOUTUBE_URL.format(video_id=video_id)
    if on_video_uploaded:
        on_video_uploaded(video_id, url)

    set_thumbnail(
        youtube,
        video_id,
        entry.thumbnail_path,
        max_retries=max_retries,
    )
    return video_id, url


def set_thumbnail(
    youtube: Any,
    video_id: str,
    thumbnail_path: Path,
    *,
    max_retries: int = 5,
) -> None:
    mimetype = THUMBNAIL_MIME_TYPES.get(thumbnail_path.suffix.lower())
    if mimetype is None:
        raise ValueError("YouTube thumbnail must be PNG, JPG, or JPEG")
    if not thumbnail_path.is_file():
        raise ValueError("YouTube thumbnail must be a file")
    if thumbnail_path.stat().st_size > YOUTUBE_THUMBNAIL_SIZE_LIMIT:
        raise ValueError(
            f"YouTube thumbnail exceeds the "
            f"{YOUTUBE_THUMBNAIL_SIZE_LIMIT}-byte limit"
        )

    media = MediaFileUpload(
        str(thumbnail_path),
        mimetype=mimetype,
        resumable=False,
    )
    request = youtube.thumbnails().set(
        videoId=video_id,
        media_body=media,
    )
    _execute_with_retry(request, max_retries=max_retries)


def update_video_metadata(
    youtube: Any,
    video_id: str,
    entry: UploadManifestEntry,
    *,
    max_retries: int = 5,
) -> None:
    """Update metadata for an existing video without changing its media/status."""
    response = _execute_with_retry(
        youtube.videos().list(part="snippet", id=video_id),
        max_retries=max_retries,
    )
    items = response.get("items", [])
    if not items:
        raise ValueError(f"YouTube video not found or not owned: {video_id}")

    current = items[0].get("snippet", {})
    snippet = {
        "title": entry.title,
        "description": entry.description,
        "tags": list(entry.tags),
        "categoryId": entry.category_id,
        "defaultLanguage": entry.language_code,
        "defaultAudioLanguage": entry.language_code,
    }

    # Preserve fields that YouTube allows on update but that this manifest
    # does not manage.
    for field in ("recordingDate",):
        if field in current:
            snippet[field] = current[field]

    _execute_with_retry(
        youtube.videos().update(
            part="snippet",
            body={"id": video_id, "snippet": snippet},
        ),
        max_retries=max_retries,
    )


def _resumable_execute(request: Any, *, max_retries: int) -> dict[str, Any]:
    retry_count = 0
    while True:
        try:
            _, response = request.next_chunk()
            if response is not None:
                return response
        except HttpError as exc:
            if not _can_retry(exc, retry_count, max_retries):
                raise
            _sleep_before_retry(retry_count)
            retry_count += 1


def _execute_with_retry(request: Any, *, max_retries: int) -> Any:
    retry_count = 0
    while True:
        try:
            return request.execute()
        except HttpError as exc:
            if not _can_retry(exc, retry_count, max_retries):
                raise
            _sleep_before_retry(retry_count)
            retry_count += 1


def _can_retry(exc: HttpError, retry_count: int, max_retries: int) -> bool:
    return (
        exc.resp.status in RETRIABLE_STATUS_CODES
        and retry_count < max_retries
    )


def _sleep_before_retry(retry_count: int) -> None:
    delay = (2**retry_count) + random.random()
    time.sleep(delay)
