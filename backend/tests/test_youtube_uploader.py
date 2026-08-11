from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
from unittest.mock import MagicMock

from backend.studio.youtube.manifest import UploadSpec
from backend.studio.youtube.uploader import add_to_playlist


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
