from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import (
    MusicDocuseries,
    MusicDocuseriesLocale,
)
from backend.studio.production import Production
from backend.studio.studio_config import (
    PRODUCTIONS_DIR,
    WEBSITE,
)


LANGUAGE_SORT = {
    "en": 0,
    "es": 1,
    "pt-BR": 2,
}


def split_title(full_title: str) -> tuple[str, str]:
    """
    Split a database title such as:

        Casey Kasem: The Voice of America's Top 40

    into title and subtitle. Titles without a colon remain unchanged.
    """
    title, separator, subtitle = full_title.partition(":")

    if not separator:
        return full_title.strip(), ""

    return title.strip(), subtitle.strip()


def youtube_key_from_source(source_key: str | None) -> str | None:
    """
    Convert:

        music-docuseries/100.mp3

    into:

        music-docuseries-youtube/100.mp3
    """
    if not source_key:
        return None

    prefix = "music-docuseries/"

    if source_key.startswith(prefix):
        filename = source_key[len(prefix):]
        return f"music-docuseries-youtube/{filename}"

    return source_key


def build_language_entry(
    locale: MusicDocuseriesLocale,
) -> dict[str, Any]:
    language_code = locale.language_code

    entry: dict[str, Any] = {
        "language_code": language_code,
        "locale_id": locale.id,
        "duration_seconds": locale.duration_seconds,
        "bucket": locale.tts_bucket,
        "source_key": locale.tts_key,
        "youtube_key": youtube_key_from_source(locale.tts_key),
        "local_audio": f"audio/{language_code}_{locale.id}.mp3",
    }

    return entry


def load_docuseries(
    docuseries_id: int,
) -> tuple[MusicDocuseries, list[MusicDocuseriesLocale]]:
    with Session(engine) as db:
        item = db.exec(
            select(MusicDocuseries).where(
                MusicDocuseries.id == docuseries_id
            )
        ).first()

        if item is None:
            raise LookupError(
                f"Music docuseries ID not found: {docuseries_id}"
            )

        locales = list(
            db.exec(
                select(MusicDocuseriesLocale)
                .where(
                    MusicDocuseriesLocale.docuseries_id
                    == docuseries_id
                )
            ).all()
        )

    locales.sort(
        key=lambda row: LANGUAGE_SORT.get(
            row.language_code,
            99,
        )
    )

    if not locales:
        raise LookupError(
            f"No locale records found for docuseries ID "
            f"{docuseries_id}"
        )

    return item, locales


def build_production_record(
    item: MusicDocuseries,
    locales: list[MusicDocuseriesLocale],
) -> dict[str, Any]:
    title, subtitle_from_title = split_title(item.title)

    subtitle = (
        item.short_description
        or subtitle_from_title
        or ""
    )

    return {
        "version": 1,
        "production_type": "documentary",
        "slug": item.slug,
        "title": title,
        "subtitle": subtitle,
        "website": WEBSITE,
        "source": {
            "type": "music_docuseries",
            "id": item.id,
        },

        # Kept for compatibility with the current Production class
        # and existing Studio scripts.
        "docuseries_id": item.id,

        "status": {
            "current_station": "production_created",
            "production_created": True,
            "audio_ready": False,
            "cards_ready": False,
            "storyboard_ready": False,
            "images_ready": False,
            "image_review_complete": False,
            "preview_ready": False,
            "video_review_complete": False,
            "thumbnail_ready": False,
            "youtube_package_ready": False,
            "published": False,
        },

        "languages": [
            build_language_entry(locale)
            for locale in locales
        ],

        "cards": {
            "logo": "cards/01_logo.png",
            "languages": "cards/02_languages.png",
            "title": "cards/03_title.png",
        },

        "images": [],

        "output": {
            "video": f"output/{item.slug}.mp4",
            "thumbnail": "output/thumbnail.png",
        },

        "audio_mix": {
            "bed_key": "bed-tracks/docuseries/bed_01.mp3",
            "bed_volume_db": -26.0,
            "duck_threshold": 0.03,
            "duck_ratio": 8.0,
            "duck_attack_ms": 25,
            "duck_release_ms": 500,
        },
    }


def write_support_files(
    production_root: Path,
    item: MusicDocuseries,
) -> None:
    """
    These files track production work. The documentary story itself
    remains in the database, which is the source of truth.
    """
    notes_path = production_root / "notes.md"
    review_path = production_root / "review.md"

    notes_path.write_text(
        (
            f"# {item.title} — Production Notes\n\n"
            "## Research notes\n\n"
            "## Historical assets\n\n"
            "## Production decisions\n\n"
            "## Future improvements\n"
        ),
        encoding="utf-8",
    )

    review_path.write_text(
        (
            f"# {item.title} — Review Log\n\n"
            "## Story review\n\n"
            "Not reviewed.\n\n"
            "## Image review\n\n"
            "Not reviewed.\n\n"
            "## Audio review\n\n"
            "Not reviewed.\n\n"
            "## Video review\n\n"
            "Not reviewed.\n\n"
            "## Publication review\n\n"
            "Not reviewed.\n"
        ),
        encoding="utf-8",
    )

    storyboard_path = production_root / "storyboard.json"
    storyboard_path.write_text(
        json.dumps(
            {
                "version": 1,
                "source": {
                    "type": "music_docuseries",
                    "id": item.id,
                },
                "scenes": [],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def create_docuseries_production(
    docuseries_id: int,
) -> Path:
    item, locales = load_docuseries(docuseries_id)

    production_root = PRODUCTIONS_DIR / item.slug
    record_path = production_root / "manifest.json"

    if production_root.exists():
        raise FileExistsError(
            f"Production already exists: {production_root}"
        )

    production_root.mkdir(parents=True)

    record = build_production_record(item, locales)

    record_path.write_text(
        json.dumps(
            record,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    write_support_files(production_root, item)

    # Load the new record through the existing Production class,
    # then create the standard disposable work directories.
    production = Production(item.slug)
    production.ensure_work_dirs()

    return production_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a TopSpot Studio production from an "
            "existing database documentary."
        )
    )

    parser.add_argument(
        "--docuseries-id",
        required=True,
        type=int,
        help="Existing music_docuseries database ID.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        root = create_docuseries_production(
            args.docuseries_id
        )
    except (
        LookupError,
        FileExistsError,
        ValueError,
    ) as exc:
        raise SystemExit(f"❌ {exc}") from exc

    print()
    print("✅ Production Record created")
    print(f"   Permanent: {root}")
    print(f"   Work:      backend/studio/work/{root.name}")
    print()
    print("Factory Station 1 complete.")
    print("Source: existing database documentary")
    print("No audio, images, cards, or video generated yet.")


if __name__ == "__main__":
    main()
