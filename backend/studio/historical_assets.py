from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from backend.studio.studio_config import ASSETS_DIR

if TYPE_CHECKING:
    from backend.studio.production import Production


HISTORICAL_ROOT = ASSETS_DIR / "historical"


@dataclass(frozen=True)
class HistoricalAssetDirectories:
    root: Path
    archive: Path
    metadata: Path
    photos: Path

    def ensure(self) -> None:
        for directory in (
            self.archive,
            self.metadata,
            self.photos,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def artist_letter(slug: str) -> str:
    first_character = slug[:1].lower()

    if first_character.isalpha():
        return first_character

    return "0-9"


def historical_directories(
    *,
    source_type: str,
    slug: str,
) -> HistoricalAssetDirectories:
    normalized_source_type = source_type.strip().lower()

    if normalized_source_type in {
        "artist",
        "artist_story",
        "premium_artist",
    }:
        root = (
            HISTORICAL_ROOT
            / "artists"
            / artist_letter(slug)
            / slug
        )
    elif normalized_source_type in {
        "docuseries",
        "music_docuseries",
    }:
        root = (
            HISTORICAL_ROOT
            / "docuseries"
            / slug
        )
    else:
        raise ValueError(
            f"Unsupported historical source type: {source_type!r}"
        )

    return HistoricalAssetDirectories(
        root=root,
        archive=root / "archive",
        metadata=root / "metadata",
        photos=root / "photos",
    )


def historical_directories_for_production(
    production: Production,
) -> HistoricalAssetDirectories:
    return historical_directories(
        source_type=production.documentary.source_type,
        slug=production.slug,
    )