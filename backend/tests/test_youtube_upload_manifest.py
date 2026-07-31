import json
from pathlib import Path

import pytest

from backend.studio.youtube.manifest import ManifestError, load_manifest


def make_record(tmp_path: Path) -> dict[str, object]:
    video = tmp_path / "artist_en.mp4"
    thumbnail = tmp_path / "artist_en.png"
    video.write_bytes(b"not a real video")
    thumbnail.write_bytes(b"not a real image")
    return {
        "slug": "fake_artist",
        "language_code": "en",
        "video_path": video.name,
        "thumbnail_path": thumbnail.name,
        "title": "A valid title",
        "description": "A valid description",
        "tags": ["music", "documentary"],
        "category_id": "10",
        "made_for_kids": False,
    }


def write_manifest(tmp_path: Path, records: list[dict[str, object]]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"uploads": records}), encoding="utf-8")
    return path


def test_valid_manifest_parsing(tmp_path: Path) -> None:
    record = make_record(tmp_path)
    entries = load_manifest(write_manifest(tmp_path, [record]))

    assert len(entries) == 1
    entry = entries[0]
    assert entry.slug == "fake_artist"
    assert entry.language_code == "en"
    assert entry.video_path == (tmp_path / "artist_en.mp4").resolve()
    assert entry.thumbnail_path == (tmp_path / "artist_en.png").resolve()
    assert entry.tags == ("music", "documentary")
    assert entry.privacy_status == "private"


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    record = make_record(tmp_path)
    record["video_path"] = "missing.mp4"
    with pytest.raises(ManifestError, match="file not found"):
        load_manifest(write_manifest(tmp_path, [record]))


def test_duplicate_slug_language_pair_is_rejected(tmp_path: Path) -> None:
    record = make_record(tmp_path)
    with pytest.raises(ManifestError, match="Duplicate slug/language pair"):
        load_manifest(write_manifest(tmp_path, [record, record.copy()]))


def test_unsupported_language_is_rejected(tmp_path: Path) -> None:
    record = make_record(tmp_path)
    record["language_code"] = "fr"
    with pytest.raises(ManifestError, match="unsupported language"):
        load_manifest(write_manifest(tmp_path, [record]))


def test_invalid_privacy_is_rejected(tmp_path: Path) -> None:
    record = make_record(tmp_path)
    record["privacy_status"] = "friends-only"
    with pytest.raises(ManifestError, match="invalid privacy"):
        load_manifest(write_manifest(tmp_path, [record]))


def test_excessive_title_length_is_rejected(tmp_path: Path) -> None:
    record = make_record(tmp_path)
    record["title"] = "x" * 101
    with pytest.raises(ManifestError, match="100-character limit"):
        load_manifest(write_manifest(tmp_path, [record]))


@pytest.mark.parametrize("extension", [".png", ".jpg", ".jpeg", ".JPG"])
def test_supported_thumbnail_formats_are_accepted(
    tmp_path: Path,
    extension: str,
) -> None:
    record = make_record(tmp_path)
    thumbnail = tmp_path / f"artist_en{extension}"
    thumbnail.write_bytes(b"not a real image")
    record["thumbnail_path"] = thumbnail.name

    entry = load_manifest(write_manifest(tmp_path, [record]))[0]

    assert entry.thumbnail_path == thumbnail.resolve()


def test_unsupported_thumbnail_format_is_rejected(tmp_path: Path) -> None:
    record = make_record(tmp_path)
    thumbnail = tmp_path / "artist_en.gif"
    thumbnail.write_bytes(b"not a real image")
    record["thumbnail_path"] = thumbnail.name
    with pytest.raises(ManifestError, match="thumbnail must be PNG, JPG, or JPEG"):
        load_manifest(write_manifest(tmp_path, [record]))


def test_oversized_thumbnail_is_rejected(tmp_path: Path) -> None:
    record = make_record(tmp_path)
    thumbnail = tmp_path / "oversized.jpg"
    thumbnail.write_bytes(b"x" * 2_097_153)
    record["thumbnail_path"] = thumbnail.name
    with pytest.raises(ManifestError, match="2097152-byte limit"):
        load_manifest(write_manifest(tmp_path, [record]))


def test_invalid_video_extension_is_rejected(tmp_path: Path) -> None:
    record = make_record(tmp_path)
    video = tmp_path / "artist_en.mov"
    video.write_bytes(b"not a real video")
    record["video_path"] = video.name
    with pytest.raises(ManifestError, match="video must be an MP4 file"):
        load_manifest(write_manifest(tmp_path, [record]))


def test_empty_video_is_rejected(tmp_path: Path) -> None:
    record = make_record(tmp_path)
    video = tmp_path / "empty.mp4"
    video.write_bytes(b"")
    record["video_path"] = video.name
    with pytest.raises(ManifestError, match="video file must not be empty"):
        load_manifest(write_manifest(tmp_path, [record]))


@pytest.mark.parametrize(
    "filename",
    ["image_sequence.mp4", "opening.mp4", "artist_review.mp4"],
)
def test_forbidden_video_filenames_are_rejected(
    tmp_path: Path,
    filename: str,
) -> None:
    record = make_record(tmp_path)
    forbidden = tmp_path / filename
    forbidden.write_bytes(b"not a real video")
    record["video_path"] = filename
    with pytest.raises(ManifestError, match="forbidden video file"):
        load_manifest(write_manifest(tmp_path, [record]))
