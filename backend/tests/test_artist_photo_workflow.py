from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.studio.assign_historical import find_photo
from backend.studio.build_artist_photo_review_page import (
    approval_command,
)
from backend.studio.collect_artist_photo import (
    candidate_matches_artist,
    next_photo_number,
    safe_photo_title,
)
from backend.studio.historical_storage import (
    artist_photo_storage_key,
)
from backend.studio.stations.assign_approved_artist_photos import (
    is_safe_artist_shot,
)


def test_artist_photo_storage_key_uses_artist_layout() -> None:
    assert artist_photo_storage_key(
        artist_slug="al_jarreau",
        filename="001-concert.jpg",
    ) == (
        "artists/a/al_jarreau/photos/"
        "001-concert.jpg"
    )


def test_safe_photo_title_normalizes_filename() -> None:
    assert safe_photo_title(
        "File:Al Jarreau Live in Concert.JPG"
    ) == "al-jarreau-live-in-concert"


def test_next_photo_number_uses_photos_and_metadata(
    tmp_path: Path,
) -> None:
    photos = tmp_path / "photos"
    metadata = tmp_path / "metadata"
    photos.mkdir()
    metadata.mkdir()

    (photos / "001-first.jpg").write_bytes(b"photo")
    (metadata / "004-fourth.json").write_text(
        "{}",
        encoding="utf-8",
    )

    assert next_photo_number(photos, metadata) == 5


def test_candidate_matches_artist_uses_searchable_text() -> None:
    candidate = SimpleNamespace(
        title="File:Al Jarreau in Concert.jpg",
        description="American jazz singer Al Jarreau performing.",
        creator="Photographer",
        date="2012",
        page_url=(
            "https://commons.wikimedia.org/"
            "wiki/File:Al_Jarreau_in_Concert.jpg"
        ),
    )

    assert candidate_matches_artist(
        candidate,
        "Al Jarreau",
    )


def test_safe_artist_shot_accepts_artist_performance() -> None:
    shot = {
        "visual_intent": (
            "Al Jarreau singing live on a concert stage"
        ),
        "historical_search": "",
        "prompt": "",
        "historical_plan": {
            "subject": "Al Jarreau",
        },
    }

    assert is_safe_artist_shot(
        shot,
        "Al Jarreau",
    )


def test_safe_artist_shot_rejects_unsafe_subject() -> None:
    shot = {
        "visual_intent": (
            "Young Al Jarreau as a child at school"
        ),
        "historical_search": "",
        "prompt": "",
        "historical_plan": {
            "subject": "Al Jarreau",
        },
    }

    assert not is_safe_artist_shot(
        shot,
        "Al Jarreau",
    )


def test_approval_command_uses_current_python() -> None:
    command = approval_command(
        artist_id=42,
        query="Al Jarreau portrait",
        limit=10,
        page_url=(
            "https://commons.wikimedia.org/"
            "wiki/File:Al_Jarreau.jpg"
        ),
    )

    assert "backend.studio.collect_artist_photo" in command
    assert "--artist-id 42" in command
    assert "Al Jarreau portrait" in command
    assert "-X utf8" in command


def test_find_photo_uses_production_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    photos = tmp_path / "photos"
    photos.mkdir()
    expected = photos / "007-approved-photo.jpg"
    expected.write_bytes(b"photo")

    directories = SimpleNamespace(photos=photos)

    monkeypatch.setattr(
        "backend.studio.assign_historical."
        "historical_directories_for_production",
        lambda production: directories,
    )

    result = find_photo(
        production=SimpleNamespace(),
        photo_id="7",
    )

    assert result == expected
