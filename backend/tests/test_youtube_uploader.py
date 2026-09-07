from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
from unittest.mock import MagicMock

from backend.studio.youtube.manifest import UploadSpec
from backend.studio.youtube.uploader import add_to_playlist, upload_video


def test_add_to_playlist_is_idempotent() -> None:
    youtube = MagicMock()
    youtube.playlistItems.return_value.list.return_value.execute.return_value = {"items": [{"id": "already"}]}
    add_to_playlist(youtube, "playlist", "video")
    youtube.playlistItems.return_value.insert.assert_not_called()


def test_upload_contract_defaults_are_approved(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    thumb = tmp_path / "thumb.png"
    video.write_bytes(b"video")
    thumb.write_bytes(b"image")
    spec = UploadSpec(
        slug="fabulous_fifties",
        collection_key="history_eras",
        language_code="en",
        video_path=video,
        thumbnail_path=thumb,
        captions_path=None,
        title="The Fabulous Fifties",
        description="Description",
        tags=("music",),
        scheduled_publish_at=datetime.fromisoformat("2026-08-12T11:00:00-05:00"),
        playlist_keys=("english_docuseries", "history_eras_en"),
        visual_approval="gary",
        approved_video_sha256=hashlib.sha256(b"video").hexdigest(),
    )
    assert spec.notify_subscribers is True
    assert spec.contains_synthetic_media is True
    assert spec.made_for_kids is False
    assert spec.end_screen_required is True



def test_upload_video_can_be_unlisted_without_schedule(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "video.mp4"
    thumb = tmp_path / "thumb.png"
    video.write_bytes(b"video")
    thumb.write_bytes(b"image")
    spec = UploadSpec(
        slug="replacement",
        collection_key="people_behind_music",
        language_code="en",
        video_path=video,
        thumbnail_path=thumb,
        captions_path=None,
        title="Replacement",
        description="Review copy",
        tags=("music",),
        scheduled_publish_at=None,
        playlist_keys=("english_docuseries",),
        visual_approval="gary",
        approved_video_sha256=hashlib.sha256(b"video").hexdigest(),
        notify_subscribers=False,
        privacy_status="unlisted",
    )
    youtube = MagicMock()
    monkeypatch.setattr(
        "backend.studio.youtube.uploader._resumable",
        lambda request: {"id": "replacement-id"},
    )

    assert upload_video(youtube, spec) == "replacement-id"

    request = youtube.videos.return_value.insert
    body = request.call_args.kwargs["body"]
    assert body["status"]["privacyStatus"] == "unlisted"
    assert "publishAt" not in body["status"]
    assert request.call_args.kwargs["notifySubscribers"] is False
