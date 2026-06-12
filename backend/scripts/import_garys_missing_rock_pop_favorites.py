from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from sqlalchemy import or_, func
from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Artist, Track
from backend.models.collection_models import (
    Collection,
    CollectionCategory,
    CollectionTrackRanking,
)
from backend.services.spotify.spotify_lookup import get_spotify_track_data


CATEGORY_NAME = "Specialty Mixes"
CATEGORY_SLUG = "specialty_mixes"

COLLECTION_NAME = "Gary's Missing Rock & Pop Favorites"
COLLECTION_SLUG = "garys_missing_rock_pop_favorites"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower().strip()).strip("_")


def find_artist(session: Session, name: str) -> Artist | None:
    return session.exec(
        select(Artist).where(func.lower(Artist.artist_name) == name.lower())
    ).first()


def find_track_by_spotify_id(session: Session, spotify_id: str) -> Track | None:
    return session.exec(
        select(Track).where(Track.spotify_track_id == spotify_id)
    ).first()


def find_track_by_artist_title(session: Session, artist_id: int, track_name: str) -> Track | None:
    return session.exec(
        select(Track).where(
            Track.artist_id == artist_id,
            func.lower(Track.track_name) == track_name.lower(),
        )
    ).first()


def get_or_create_category(session: Session) -> CollectionCategory:
    existing = session.exec(
        select(CollectionCategory).where(
            or_(
                CollectionCategory.slug == CATEGORY_SLUG,
                CollectionCategory.name == CATEGORY_NAME,
            )
        )
    ).first()

    if existing:
        return existing

    category = CollectionCategory(
        name=CATEGORY_NAME,
        slug=CATEGORY_SLUG,
        intro="Specialty mixes and personal listening collections.",
        sort_order=0,
    )
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def get_or_create_collection(session: Session, category: CollectionCategory) -> Collection:
    existing = session.exec(
        select(Collection).where(Collection.slug == COLLECTION_SLUG)
    ).first()

    if existing:
        existing.name = COLLECTION_NAME
        existing.category_id = category.id
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    collection = Collection(
        name=COLLECTION_NAME,
        slug=COLLECTION_SLUG,
        intro=(
            "A personal rock and pop collection of songs Gary reaches for when "
            "country music is not playing, from CCR and Dire Straits to Billy Joel, "
            "Rod Stewart, classic pop, oldies, and road-trip favorites."
        ),
        category_id=category.id,
    )
    session.add(collection)
    session.commit()
    session.refresh(collection)
    return collection


def find_ranking(session: Session, collection_id: int, rank: int) -> CollectionTrackRanking | None:
    return session.exec(
        select(CollectionTrackRanking).where(
            CollectionTrackRanking.collection_id == collection_id,
            CollectionTrackRanking.ranking == rank,
        )
    ).first()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        default="backend/data/heritage_collections/garys_missing_rock_pop_favorites.csv",
    )
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    path = Path(args.csv)
    rows = load_rows(path)

    print("=" * 80)
    print("Import Gary's Missing Country Favorites")
    print(f"CSV:  {path}")
    print(f"Rows: {len(rows)}")
    print(f"Save: {args.save}")
    print("=" * 80)

    created_tracks = 0
    existing_tracks = 0
    missing_spotify = 0
    rankings_written = 0

    with Session(engine) as session:
        category = get_or_create_category(session)
        collection = get_or_create_collection(session, category)

        for rank, row in enumerate(rows, start=1):
            artist_name = row["artist_name"].strip()
            track_name = row["track_name"].strip()

            artist = find_artist(session, artist_name)

            if not artist:
                artist = Artist(artist_name=artist_name)

                if args.save:
                    session.add(artist)
                    session.commit()
                    session.refresh(artist)

                print(f"{rank:02d}. Created artist: {artist_name}")

            existing_track = find_track_by_artist_title(session, artist.id, track_name)

            if existing_track:
                track = existing_track
                existing_tracks += 1
                print(f"{rank:02d}. Existing track: {artist_name} - {track_name} ({track.id})")
            else:
                spotify = get_spotify_track_data(track_name, artist_name)

                if not spotify:
                    missing_spotify += 1
                    print(f"{rank:02d}. SPOTIFY MISS: {artist_name} - {track_name}")
                    continue

                spotify_track_id = spotify["spotify_track_id"]
                spotify_existing = find_track_by_spotify_id(session, spotify_track_id)

                if spotify_existing:
                    track = spotify_existing
                    existing_tracks += 1
                    print(
                        f"{rank:02d}. Using existing Spotify track: "
                        f"{artist_name} - {track_name} ({track.id})"
                    )
                else:
                    track = Track(
                        track_name=track_name,
                        album_name=spotify.get("album_name"),
                        artist_display_name=artist_name,
                        spotify_track_id=spotify_track_id,
                        duration_ms=spotify.get("duration_ms"),
                        popularity=spotify.get("popularity"),
                        album_artwork=spotify.get("album_artwork"),
                        year_released=spotify.get("year_released"),
                        artist_id=artist.id,
                        language="en",
                    )

                    if args.save:
                        session.add(track)
                        session.commit()
                        session.refresh(track)

                    created_tracks += 1
                    print(f"{rank:02d}. Created track: {artist_name} - {track_name}")

            intro = f"At number {rank}, {track_name} by {artist_name}, from Gary's Missing Country Favorites."

            existing_ranking = find_ranking(session, collection.id, rank)

            if existing_ranking:
                ranking = existing_ranking
                ranking.track_id = track.id
                ranking.intro = intro
            else:
                ranking = CollectionTrackRanking(
                    collection_id=collection.id,
                    track_id=track.id,
                    ranking=rank,
                    intro=intro,
                )

            if args.save:
                session.add(ranking)
                session.commit()
                session.refresh(ranking)

            rankings_written += 1

    print("=" * 80)
    print(f"Existing tracks:  {existing_tracks}")
    print(f"Created tracks:   {created_tracks}")
    print(f"Spotify misses:   {missing_spotify}")
    print(f"Rankings written: {rankings_written}")
    print("=" * 80)


if __name__ == "__main__":
    main()
