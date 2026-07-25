from __future__ import annotations

import argparse

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import (
    Collection,
    CollectionCategory,
    CollectionTrackRanking,
)
from backend.models.dbmodels import Track, Artist


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a simple console preview for a TopSpot40 collection catalog page."
    )
    parser.add_argument(
        "--slug",
        default="railroad_train_songs",
        help="Collection slug to preview.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with Session(engine) as session:
        collection = session.exec(
            select(Collection).where(Collection.slug == args.slug)
        ).first()

        if not collection:
            raise SystemExit(f"Collection not found: {args.slug}")

        category_name = "Uncategorized"
        if collection.category_id:
            category = session.get(CollectionCategory, collection.category_id)
            if category:
                category_name = category.name

        rows = session.exec(
            select(
                CollectionTrackRanking.ranking,
                Track.track_name,
                Track.artist_display_name,
                Artist.artist_name,
            )
            .join(Track, CollectionTrackRanking.track_id == Track.id)
            .join(Artist, Track.artist_id == Artist.id)
            .where(CollectionTrackRanking.collection_id == collection.id)
            .order_by(CollectionTrackRanking.ranking)
        ).all()

    print("=" * 72)
    print(collection.name)
    print("=" * 72)
    print()
    print(f"Slug:  {collection.slug}")
    print(f"Group: {category_name}")
    print()
    print("Description:")
    print(collection.intro or "(No description found.)")
    print()
    print("Tracks:")
    print("-" * 72)

    for ranking, track_name, artist_display_name, artist_name in rows:
        display_artist = artist_display_name or artist_name or "Unknown Artist"
        print(f"{ranking:>2}. {track_name} - {display_artist}")

    print("-" * 72)
    print(f"Total tracks: {len(rows)}")


if __name__ == "__main__":
    main()