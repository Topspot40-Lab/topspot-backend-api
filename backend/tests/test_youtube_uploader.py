from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from backend.studio.youtube.manifest import UploadManifestEntry
from backend.studio.youtube.upload_batch import parse_args


@pytest.fixture
def mocked_uploader(monkeypatch: pytest.MonkeyPatch):
    package = types.ModuleType("googleapiclient")
    package.__path__ = []
    discovery = types.ModuleType("googleapiclient.discovery")
    errors = types.ModuleType("googleapiclient.errors")
    http = types.ModuleType("googleapiclient.http")

    class FakeHttpError(Exception):
        pass

    media_upload = MagicMock(name="MediaFileUpload")
    discovery.build = MagicMock(name="build")
    errors.HttpError = FakeHttpError
    http.MediaFileUpload = media_upload
    monkeypatch.setitem(sys.modules, "googleapiclient", package)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)
    monkeypatch.setitem(sys.modules, "googleapiclient.errors", errors)
    monkeypatch.setitem(sys.modules, "googleapiclient.http", http)

    module_name = "backend.studio.youtube.uploader"
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    try:
        yield module, media_upload
    finally:
        sys.modules.pop(module_name, None)


def make_entry(tmp_path: Path, thumbnail_suffix: str = ".png"):
    video = tmp_path / "artist_en.mp4"
    thumbnail = tmp_path / f"artist_en{thumbnail_suffix}"
    video.write_bytes(b"video")
    thumbnail.write_bytes(b"thumbnail")
    return UploadManifestEntry(
        slug="fake_artist",
        language_code="en",
        video_path=video,
        thumbnail_path=thumbnail,
        title="Fake Artist",
        description="Fake description",
        tags=("music", "documentary"),
        category_id="10",
        made_for_kids=True,
    )


def test_upload_metadata_defaults_and_callback_order(
    tmp_path: Path,
    mocked_uploader,
) -> None:
    uploader, media_upload = mocked_uploader
    entry = make_entry(tmp_path)
    youtube = MagicMock()
    video_request = MagicMock()
    video_request.next_chunk.return_value = (None, {"id": "video123"})
    youtube.videos.return_value.insert.return_value = video_request

    events = []
    thumbnail_request = MagicMock()

    def start_thumbnail(**kwargs):
        events.append("thumbnail")
        return thumbnail_request

    youtube.thumbnails.return_value.set.side_effect = start_thumbnail

    def save_video(video_id: str, url: str) -> None:
        events.append("callback")
        assert video_id == "video123"
        assert url == "https://www.youtube.com/watch?v=video123"

    result = uploader.upload_video(
        youtube,
        entry,
        on_video_uploaded=save_video,
    )

    insert_kwargs = youtube.videos.return_value.insert.call_args.kwargs
    assert insert_kwargs["notifySubscribers"] is False
    assert insert_kwargs["body"]["status"] == {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": True,
    }
    assert insert_kwargs["body"]["snippet"]["defaultLanguage"] == "en"
    assert events == ["callback", "thumbnail"]
    assert result == (
        "video123",
        "https://www.youtube.com/watch?v=video123",
    )
    assert media_upload.call_args_list == [
        call(
            str(entry.video_path),
            mimetype="video/mp4",
            chunksize=-1,
            resumable=True,
        ),
        call(str(entry.thumbnail_path), mimetype="image/png", resumable=False),
    ]


@pytest.mark.parametrize(
    ("extension", "mimetype"),
    [(".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg")],
)
def test_thumbnail_uses_matching_mime_type(
    tmp_path: Path,
    mocked_uploader,
    extension: str,
    mimetype: str,
) -> None:
    uploader, media_upload = mocked_uploader
    entry = make_entry(tmp_path, extension)
    youtube = MagicMock()

    uploader.set_thumbnail(youtube, "video123", entry.thumbnail_path)

    media_upload.assert_called_once_with(
        str(entry.thumbnail_path),
        mimetype=mimetype,
        resumable=False,
    )
    youtube.thumbnails.return_value.set.assert_called_once()


def test_public_apply_requires_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "upload_batch",
            "--manifest",
            "manifest.json",
            "--client-secrets",
            "client.json",
            "--apply",
            "--privacy",
            "public",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        parse_args()

    assert exc_info.value.code == 2
    assert "--confirm-public is required" in capsys.readouterr().err
