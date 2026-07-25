from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.studio.documentary import (
    Documentary,
    DocumentaryLanguage,
)
from backend.studio.production import Production
from backend.studio.studio_config import (
    PRODUCTIONS_DIR,
    WEBSITE,
)


def build_language_entry(
    language: DocumentaryLanguage,
) -> dict[str, Any]:
    return {
        "language_code": language.language_code,
        "locale_id": language.locale_id,
        "duration_seconds": language.duration_seconds,
        "bucket": language.tts_bucket,
        "source_key": language.tts_key,
        "youtube_key": language.youtube_key,
        "local_audio": (
            f"audio/{language.local_audio_name}"
        ),
    }


def build_production_record(
    documentary: Documentary,
) -> dict[str, Any]:
    return {
        "version": 1,
        "production_type": "documentary",
        "slug": documentary.slug,
        "title": documentary.title,
        "subtitle": documentary.subtitle,
        "website": WEBSITE,
        "artwork_url": documentary.artwork_url,

        "source": {
            "type": documentary.source_type,
            "id": documentary.source_id,
        },

        # Retain compatibility for older code while docuseries
        # productions are being migrated.
        "docuseries_id": (
            documentary.source_id
            if documentary.source_type == "music_docuseries"
            else None
        ),

        "status": {
            "current_station": "production_created",
            "production_created": True,
            "story_ready": False,
            "audio_ready": False,
            "cards_ready": False,
            "storyboard_ready": False,
            "visual_plan_ready": False,
            "images_ready": False,
            "image_review_complete": False,
            "preview_ready": False,
            "video_review_complete": False,
            "thumbnail_ready": False,
            "youtube_package_ready": False,
            "published": False,
        },

        "languages": [
            build_language_entry(language)
            for language in documentary.languages
        ],

        "cards": {
            "logo": "cards/01_logo.png",
            "languages": "cards/02_languages.png",
            "title": "cards/03_title.png",
        },

        "images": [],

        "output": {
            "video": f"output/{documentary.slug}.mp4",
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
    documentary: Documentary,
) -> None:
    notes_path = production_root / "notes.md"
    review_path = production_root / "review.md"
    storyboard_path = production_root / "storyboard.json"

    notes_path.write_text(
        (
            f"# {documentary.title} — Production Notes\n\n"
            "## Research notes\n\n"
            "## Historical assets\n\n"
            "## Production decisions\n\n"
            "## Future improvements\n"
        ),
        encoding="utf-8",
    )

    review_path.write_text(
        (
            f"# {documentary.title} — Review Log\n\n"
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

    storyboard_path.write_text(
        json.dumps(
            {
                "version": 1,
                "source": {
                    "type": documentary.source_type,
                    "id": documentary.source_id,
                },
                "title": documentary.title,
                "subtitle": documentary.subtitle,
                "scenes": [],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def create_production(
    *,
    source_type: str,
    source_id: int,
) -> Path:
    documentary = Documentary.load(
        source_type=source_type,
        source_id=source_id,
    )

    production_root = (
        PRODUCTIONS_DIR / documentary.slug
    )
    record_path = production_root / "manifest.json"

    if production_root.exists():
        raise FileExistsError(
            f"Production already exists: {production_root}"
        )

    production_root.mkdir(parents=True)

    record = build_production_record(documentary)

    record_path.write_text(
        json.dumps(
            record,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    write_support_files(
        production_root,
        documentary,
    )

    production = Production(documentary.slug)
    production.ensure_work_dirs()

    return production_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a TopSpot Studio production from an "
            "existing database source."
        )
    )

    source_group = parser.add_mutually_exclusive_group(
        required=True
    )

    source_group.add_argument(
        "--docuseries-id",
        type=int,
        help="Existing music_docuseries database ID.",
    )

    source_group.add_argument(
        "--artist-id",
        type=int,
        help="Existing premium artist database ID.",
    )

    source_group.add_argument(
        "--source-id",
        type=int,
        help="Source database ID used with --source-type.",
    )

    parser.add_argument(
        "--source-type",
        choices=[
            "music_docuseries",
            "artist_story",
        ],
        help="Generic source type used with --source-id.",
    )

    return parser.parse_args()


def resolve_source(
    args: argparse.Namespace,
) -> tuple[str, int]:
    if args.docuseries_id is not None:
        return (
            "music_docuseries",
            args.docuseries_id,
        )

    if args.artist_id is not None:
        return (
            "artist_story",
            args.artist_id,
        )

    if args.source_id is not None:
        if not args.source_type:
            raise ValueError(
                "--source-type is required with --source-id."
            )

        return (
            args.source_type,
            args.source_id,
        )

    raise ValueError("No production source was supplied.")


def main() -> None:
    args = parse_args()

    try:
        source_type, source_id = resolve_source(args)

        root = create_production(
            source_type=source_type,
            source_id=source_id,
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
    print(f"Source type: {source_type}")
    print(f"Source ID:   {source_id}")
    print("No audio, images, cards, or video generated yet.")


if __name__ == "__main__":
    main()
