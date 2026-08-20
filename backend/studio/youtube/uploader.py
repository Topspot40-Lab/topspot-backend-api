"""Small, retry-aware YouTube Data API publishing adapter."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.studio.youtube.manifest import THUMBNAIL_LIMIT, PlaylistSpec, UploadSpec

RETRIABLE = frozenset({500, 502, 503, 504})


def build_youtube_service(credentials: Any) -> Any:
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def ensure_playlist(youtube: Any, spec: PlaylistSpec) -> str:
    if spec.existing_playlist_id:
        return spec.existing_playlist_id
    token = None
    while True:
        response = _execute(youtube.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=token))
        for item in response.get("items", []):
            if item.get("snippet", {}).get("title") == spec.title:
                return str(item["id"])
        token = response.get("nextPageToken")
        if not token:
            break
    response = _execute(
        youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {"title": spec.title, "description": spec.description},
                "status": {"privacyStatus": spec.privacy_status},
            },
        )
    )
    return str(response["id"])


def upload_video(
        youtube: Any,
        spec: UploadSpec,
        *,
        on_uploaded: Callable[[str], None] | None = None,
) -> str:
    from googleapiclient.http import MediaFileUpload

    request = youtube.videos().insert(
        part="snippet,status",
        notifySubscribers=spec.notify_subscribers,
        body={
            "snippet": {
                "title": spec.title,
                "description": spec.description,
                "tags": list(spec.tags),
                "categoryId": spec.category_id,
                "defaultLanguage": spec.language_code,
                "defaultAudioLanguage": spec.language_code,
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": spec.scheduled_publish_at.isoformat(),
                "selfDeclaredMadeForKids": spec.made_for_kids,
                "containsSyntheticMedia": spec.contains_synthetic_media,
                "embeddable": True,
                "publicStatsViewable": True,
                "license": "youtube",
            },
        },
        media_body=MediaFileUpload(str(spec.video_path), mimetype="video/mp4", chunksize=-1, resumable=True),
    )
    response = _resumable(request)
    video_id = response.get("id") if response else None
    if not video_id:
        raise RuntimeError("YouTube did not return a video ID")
    if on_uploaded:
        on_uploaded(str(video_id))
    return str(video_id)


def set_thumbnail(youtube: Any, video_id: str, path: Path) -> None:
    from googleapiclient.http import MediaFileUpload

    if path.stat().st_size > THUMBNAIL_LIMIT:
        raise ValueError("Thumbnail exceeds 2 MiB")
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    _execute(youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(path), mimetype=mime)))


def upload_captions(youtube: Any, video_id: str, language: str, path: Path) -> None:
    from googleapiclient.http import MediaFileUpload

    mime = "application/octet-stream"
    existing = _execute(youtube.captions().list(part="snippet", videoId=video_id))
    matching = next(
        (
            item
            for item in existing.get("items", [])
            if (
                item.get("snippet", {}).get("language") == language
                and item.get("snippet", {}).get("trackKind") != "asr"
        )
        ),
        None,
    )
    media = MediaFileUpload(str(path), mimetype=mime)
    if matching:
        _execute(
            youtube.captions().update(
                part="snippet",
                body={
                    "id": matching["id"],
                    "snippet": {
                        "videoId": video_id,
                        "language": language,
                        "name": language,
                        "isDraft": False,
                    },
                },
                media_body=media,
            )
        )
        return
    _execute(
        youtube.captions().insert(
            part="snippet",
            body={"snippet": {"videoId": video_id, "language": language, "name": language, "isDraft": False}},
            media_body=media,
        )
    )


def add_to_playlist(youtube: Any, playlist_id: str, video_id: str) -> None:
    existing = _execute(
        youtube.playlistItems().list(part="snippet", playlistId=playlist_id, videoId=video_id, maxResults=1)
    )
    if existing.get("items"):
        return
    _execute(
        youtube.playlistItems().insert(
            part="snippet",
            body={"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
        )
    )


def _resumable(request: Any, retries: int = 5) -> dict[str, Any]:
    attempt = 0
    while True:
        try:
            _, response = request.next_chunk()
            if response is not None:
                return response
        except Exception as exc:
            if not _retryable(exc, attempt, retries):
                raise
            _pause(attempt)
            attempt += 1


def _execute(request: Any, retries: int = 5) -> Any:
    attempt = 0
    while True:
        try:
            return request.execute()
        except Exception as exc:
            if not _retryable(exc, attempt, retries):
                raise
            _pause(attempt)
            attempt += 1


def _retryable(exc: Exception, attempt: int, retries: int) -> bool:
    return getattr(getattr(exc, "resp", None), "status", None) in RETRIABLE and attempt < retries


def _pause(attempt: int) -> None:
    time.sleep((2 ** attempt) + random.random())
