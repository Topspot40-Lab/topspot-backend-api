from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from backend.studio.youtube.manifest import ManifestError, load_manifest
from backend.studio.youtube.release_plan import (
    TOPICS,
    build_manifest_document,
    release_dates,
    write_manifest,
)


def _factory_assets(root: Path) -> None:
    metadata = {
        "title": "Localized title",
        "description": "Localized description",
        "keywords": ["TopSpot40", "music documentary"],
    }
    for topic in TOPICS:
        factory = root / topic.slug / "factory"
        for language in ("en", "es", "pt-BR"):
            delivery = factory / "delivery" / language
            publishing = factory / "publishing" / language
            delivery.mkdir(parents=True)
            publishing.mkdir(parents=True)
            (delivery / "documentary.mp4").write_bytes(b"video")
            (publishing / "thumbnail.png").write_bytes(b"image")
            (publishing / "captions.vtt").write_text("WEBVTT\n", encoding="utf-8")
            (publishing / "youtube.json").write_text(json.dumps(metadata), encoding="utf-8")


def test_release_sequence_runs_wednesdays_and_saturdays_through_october() -> None:
    dates = release_dates()
    assert len(dates) == 16
    assert dates[0] == date(2026, 8, 12)
    assert dates[-1] == date(2026, 10, 3)
    assert {item.weekday() for item in dates} == {2, 5}


def test_manifest_builds_48_localized_private_scheduled_uploads(tmp_path: Path) -> None:
    _factory_assets(tmp_path)
    document = build_manifest_document(tmp_path, english_docuseries_playlist_id="PL-English")
    output = tmp_path / "manifest.json"
    write_manifest(document, output)
    manifest = load_manifest(output)

    assert len(manifest.uploads) == 48
    assert len(manifest.playlists) == 10
    assert sum(item.language_code == "en" for item in manifest.uploads) == 16
    assert all(item.notify_subscribers for item in manifest.uploads)
    assert all(item.contains_synthetic_media for item in manifest.uploads)
    assert all(not item.made_for_kids for item in manifest.uploads)
    assert all(item.end_screen_required for item in manifest.uploads)
    assert all(len(item.playlist_keys) == (2 if item.language_code == "en" else 1) for item in manifest.uploads)
    assert {item.scheduled_publish_at.hour for item in manifest.uploads if item.language_code == "en"} == {11}
    assert {item.scheduled_publish_at.hour for item in manifest.uploads if item.language_code == "es"} == {15}
    assert {item.scheduled_publish_at.hour for item in manifest.uploads if item.language_code == "pt-BR"} == {19}


def test_manifest_fails_closed_when_approved_asset_is_missing(tmp_path: Path) -> None:
    _factory_assets(tmp_path)
    (tmp_path / TOPICS[0].slug / "factory" / "publishing" / "es" / "captions.vtt").unlink()
    document = build_manifest_document(tmp_path, english_docuseries_playlist_id="PL-English")
    output = tmp_path / "manifest.json"
    write_manifest(document, output)
    with pytest.raises(ManifestError, match="missing or empty"):
        load_manifest(output)


def test_manifest_rejects_video_changed_after_visual_approval(tmp_path: Path) -> None:
    _factory_assets(tmp_path)
    document = build_manifest_document(tmp_path, english_docuseries_playlist_id="PL-English")
    output = tmp_path / "manifest.json"
    write_manifest(document, output)
    video = tmp_path / TOPICS[0].slug / "factory" / "delivery" / "en" / "documentary.mp4"
    video.write_bytes(b"changed after approval")
    with pytest.raises(ManifestError, match="changed after visual approval"):
        load_manifest(output)


def test_release_start_must_be_wednesday() -> None:
    with pytest.raises(ValueError, match="Wednesday"):
        release_dates(date(2026, 8, 13))
