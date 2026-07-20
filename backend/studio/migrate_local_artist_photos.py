from __future__ import annotations

import argparse
import mimetypes
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session

from backend.database import engine
from backend.models.dbmodels import Artist
from backend.services.supabase_storage import (
    list_folder_keys,
)
from backend.studio.historical.downloader import (
    save_json_atomic,
)
from backend.studio.historical_storage import (
    HISTORICAL_IMAGES_BUCKET,
    artist_photo_storage_key,
    upload_artist_photo,
)


ARTISTS = {
    "johnny_cash": 141,
    "juan_gabriel": 1952,
    "luis_miguel": 777,
    "merle_haggard": 155,
}

ASSETS_ROOT = Path(
    "backend/studio/assets/historical/artists"
)

CANONICAL_FILENAME = re.compile(
    r"^\d{3}-[a-z0-9][a-z0-9-]*\."
    r"(?:jpg|jpeg|png|webp)$",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate legacy local artist photos "
            "to Supabase Storage."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Upload photos and create metadata. "
            "Without this flag, only report actions."
        ),
    )
    parser.add_argument(
        "--artist",
        action="append",
        choices=sorted(ARTISTS),
        help=(
            "Limit migration to one or more artist "
            "slugs. May be repeated."
        ),
    )
    return parser.parse_args()


def artist_directory(artist_slug: str) -> Path:
    return (
        ASSETS_ROOT
        / artist_slug[0].lower()
        / artist_slug
    )


def load_artist(
    *,
    artist_id: int,
    expected_slug: str,
) -> Artist:
    with Session(engine) as db:
        artist = db.get(Artist, artist_id)

        if artist is None:
            raise LookupError(
                f"Artist ID not found: {artist_id}"
            )

        return artist


def build_metadata(
    *,
    artist: Artist,
    artist_slug: str,
    photo_path: Path,
    storage_metadata: dict[str, Any],
    object_preexisted: bool,
) -> dict[str, Any]:
    content_type = (
        mimetypes.guess_type(photo_path.name)[0]
        or "application/octet-stream"
    )

    return {
        "provider": "legacy_local",
        "title": photo_path.stem,
        "original_url": "",
        "page_url": "",
        "width": None,
        "height": None,
        "mime_type": content_type,
        "thumbnail_url": "",
        "creator": "",
        "credit": "",
        "description": (
            "Legacy curated TopSpot Studio "
            "artist photograph."
        ),
        "date": "",
        "license_name": "",
        "license_url": "",
        "usage_terms": "",
        "attribution_required": None,
        "score": 0.0,
        "identity_confidence": 1.0,
        "artist_id": artist.id,
        "artist_name": artist.artist_name,
        "artist_slug": artist_slug,
        "search_query": "",
        "discovered_via": "legacy_local",
        "discovery_url": "",
        "approved": True,
        "approved_at": datetime.now(
            UTC
        ).isoformat(),
        "approved_image": photo_path.name,
        "legacy_metadata_missing": True,
        "migrated_from_local": True,
        "storage_object_preexisted": (
            object_preexisted
        ),
        **storage_metadata,
    }


def migrate_artist(
    *,
    artist_slug: str,
    artist_id: int,
    execute: bool,
) -> dict[str, int]:
    artist = load_artist(
        artist_id=artist_id,
        expected_slug=artist_slug,
    )

    directory = artist_directory(artist_slug)
    photos_directory = directory / "photos"
    metadata_directory = directory / "metadata"

    if not photos_directory.exists():
        raise FileNotFoundError(
            f"Missing photos directory: "
            f"{photos_directory}"
        )

    photos = sorted(
        path
        for path in photos_directory.iterdir()
        if path.is_file()
    )

    folder = (
        f"artists/{artist_slug[0].lower()}/"
        f"{artist_slug}/photos"
    )
    existing_keys = list_folder_keys(
        HISTORICAL_IMAGES_BUCKET,
        folder,
    )

    counts = {
        "photos": len(photos),
        "upload": 0,
        "existing": 0,
        "metadata": 0,
        "skip": 0,
        "error": 0,
    }

    print()
    print("=" * 72)
    print(
        f"{artist.artist_name} "
        f"(ID {artist.id})"
    )
    print("=" * 72)

    for photo_path in photos:
        if not CANONICAL_FILENAME.fullmatch(
            photo_path.name
        ):
            counts["error"] += 1
            print(
                "ERROR NONCANONICAL NAME: "
                f"{photo_path.name}"
            )
            continue

        metadata_path = (
            metadata_directory
            / f"{photo_path.stem}.json"
        )
        storage_key = artist_photo_storage_key(
            artist_slug=artist_slug,
            filename=photo_path.name,
        )
        object_preexisted = (
            storage_key in existing_keys
        )

        if metadata_path.exists():
            counts["skip"] += 1
            print(
                f"SKIP METADATA EXISTS: "
                f"{photo_path.name}"
            )
            continue

        action = (
            "EXISTS"
            if object_preexisted
            else "UPLOAD"
        )
        print(
            f"{action:8} "
            f"{photo_path.name}"
        )

        if not execute:
            if object_preexisted:
                counts["existing"] += 1
            else:
                counts["upload"] += 1
            continue

        try:
            if object_preexisted:
                storage_metadata = {
                    "storage_bucket": (
                        HISTORICAL_IMAGES_BUCKET
                    ),
                    "storage_key": storage_key,
                    "storage_bytes": (
                        photo_path.stat().st_size
                    ),
                    "storage_content_type": (
                        mimetypes.guess_type(
                            photo_path.name
                        )[0]
                        or "application/octet-stream"
                    ),
                }
                counts["existing"] += 1
            else:
                storage_metadata = (
                    upload_artist_photo(
                        artist_slug=artist_slug,
                        photo_path=photo_path,
                    )
                )
                counts["upload"] += 1

            metadata = build_metadata(
                artist=artist,
                artist_slug=artist_slug,
                photo_path=photo_path,
                storage_metadata=storage_metadata,
                object_preexisted=(
                    object_preexisted
                ),
            )

            metadata_directory.mkdir(
                parents=True,
                exist_ok=True,
            )
            save_json_atomic(
                metadata_path,
                metadata,
            )
            counts["metadata"] += 1

        except Exception as exc:
            counts["error"] += 1
            print(
                f"ERROR: {photo_path.name}: "
                f"{exc}"
            )

    return counts


def main() -> None:
    args = parse_args()
    selected = (
        args.artist
        if args.artist
        else list(ARTISTS)
    )

    totals = {
        "photos": 0,
        "upload": 0,
        "existing": 0,
        "metadata": 0,
        "skip": 0,
        "error": 0,
    }

    print(
        "TOPSPOT STUDIO — LOCAL ARTIST "
        "PHOTO MIGRATION"
    )
    print(
        "MODE: "
        + ("EXECUTE" if args.execute else "DRY RUN")
    )

    for artist_slug in selected:
        counts = migrate_artist(
            artist_slug=artist_slug,
            artist_id=ARTISTS[artist_slug],
            execute=args.execute,
        )

        for key, value in counts.items():
            totals[key] += value

    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for key, value in totals.items():
        print(f"{key:12} {value}")

    if not args.execute:
        print()
        print(
            "Dry run only. Add --execute "
            "to perform the migration."
        )


if __name__ == "__main__":
    main()
