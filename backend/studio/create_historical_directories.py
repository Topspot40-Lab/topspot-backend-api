from __future__ import annotations

import argparse
import sys

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Artist, ArtistStory
from backend.studio.documentary import slugify
from backend.studio.historical_assets import (
    historical_directories,
)


STANDARD_SUBDIRECTORIES = (
    "archive",
    "metadata",
    "photos",
)


def load_premium_artists() -> list[Artist]:
    """
    Return one artist per unique normalized slug for every
    artist having at least one ArtistStory.
    """
    with Session(engine) as db:
        artist_records = list(
            db.exec(
                select(Artist)
                .join(
                    ArtistStory,
                    ArtistStory.artist_id == Artist.id,
                )
                .distinct()
                .order_by(Artist.artist_name)
            ).all()
        )

    unique_by_slug: dict[str, Artist] = {}

    for artist in artist_records:
        artist_slug = slugify(
            artist.artist_name.strip()
        )
        unique_by_slug[artist_slug] = artist

    return sorted(
        unique_by_slug.values(),
        key=lambda artist: artist.artist_name.casefold(),
    )


def create_directories(*, dry_run: bool) -> None:
    artists = load_premium_artists()

    new_artist_directories = 0
    existing_artist_directories = 0
    missing_subdirectories = 0

    print()
    print(
        "TOPSPOT STUDIO — PREMIUM ARTIST "
        "HISTORICAL DIRECTORIES"
    )
    print("=" * 70)
    print(f"Premium artists found: {len(artists)}")
    print(f"Dry run:               {'yes' if dry_run else 'no'}")
    print()

    for artist in artists:
        artist_name = artist.artist_name.strip()
        artist_slug = slugify(artist_name)

        directories = historical_directories(
            source_type="artist_story",
            slug=artist_slug,
        )

        if directories.root.exists():
            status = "EXISTS "
            existing_artist_directories += 1
        else:
            status = "CREATE "
            new_artist_directories += 1

        missing = [
            name
            for name in STANDARD_SUBDIRECTORIES
            if not (directories.root / name).exists()
        ]
        missing_subdirectories += len(missing)

        missing_text = (
            f" [missing: {', '.join(missing)}]"
            if missing
            else ""
        )

        print(
            f"{status} {artist_name} "
            f"-> {directories.root}"
            f"{missing_text}"
        )

        if not dry_run:
            directories.ensure()

    print()
    print("=" * 70)
    print(f"Premium artists processed:    {len(artists)}")
    print(f"New artist directories:       {new_artist_directories}")
    print(
        f"Existing artist directories:  "
        f"{existing_artist_directories}"
    )
    print(f"Missing subdirectories:       {missing_subdirectories}")

    if dry_run:
        print("Dry run complete. Nothing was changed.")
    else:
        print("Historical directory creation complete.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create alphabetized historical asset directories "
            "for every TopSpot40 premium artist."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without creating directories.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(
            encoding="utf-8",
            errors="replace",
        )

    args = parse_args()
    create_directories(dry_run=args.dry_run)


if __name__ == "__main__":
    main()