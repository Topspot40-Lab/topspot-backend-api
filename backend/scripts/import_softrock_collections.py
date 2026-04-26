from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlmodel import Session, select
from sqlalchemy import or_

from backend.database import engine
from backend.models.dbmodels import (
    Artist,
    ArtistLocale,
    Track,
    TrackLocale,
)
from backend.models.collection_models import (
    Collection,
    CollectionCategory,
    CollectionTrackRanking,
    CollectionTrackRankingLocale,
)

from backend.services.spotify.spotify_lookup import get_spotify_track_data
from backend.services.xai_client import ask_xai


INPUT_FILE = Path("data/softrock/softrock_70s_90s_collections.json")

CATEGORY_NAME = "Soft Rock 70s-90s"
CATEGORY_SLUG = "soft_rock_70s_90s"

LANG_ES = "es"
LANG_PTBR = "pt-BR"

LIMIT = 2  # set to None for full run


# ─────────────────────────────────────────────

def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower().strip()).strip("-")

def title_case(value: str) -> str:
    special = {
        "bee gees": "Bee Gees",
        "foreigner": "Foreigner",
    }
    return special.get(value.lower().strip(), value.title())


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


# ─────────────────────────────────────────────

def load_collection_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


# ─────────────────────────────────────────────
# XAI GENERATORS
# ─────────────────────────────────────────────

def generate_artist_info_text(artist_name: str) -> dict[str, str]:
    text = ask_xai(
        "You are a concise music historian.",
        f"Describe the artist {artist_name} in 2 sentences."
    )

    text = re.sub(r"\s+", " ", text).strip()

    return {
        "en": text,
        "es": f"{artist_name} es conocido por su estilo suave dentro del soft rock.",
        "ptbr": f"{artist_name} é conhecido por seu estilo suave dentro do soft rock.",
    }


def generate_track_detail_text(track_name: str, artist_name: str) -> dict[str, str]:
    text = ask_xai(
        "You are a concise music historian.",
        f"Describe the song {track_name} by {artist_name} in 2 sentences."
    )

    text = re.sub(r"\s+", " ", text).strip()

    return {
        "en": text,
        "es": f"{track_name} de {artist_name} tiene un sonido suave y emocional.",
        "ptbr": f"{track_name} de {artist_name} tem um som suave e emocional.",
    }


import random

def generate_intro(
    rank: int,
    collection: str,
    track: str,
    artist: str,
    album: str | None = None,
    year: int | None = None,
) -> dict[str, str]:

    # Fallbacks
    album = album or "Unknown Album"
    year = year or "Unknown Year"

    collection_es = "Canciones románticas de soft rock"
    collection_pt = "Canções românticas de soft rock"

    templates_en = [
        "Did you know? '{track}' by {artist}, at rank {rank}, from '{album}' released in {year}, is a {collection} classic.",
        "At rank {rank}, '{track}' by {artist}, from '{album}' ({year}), stands as a true {collection} favorite.",
        "Coming in at number {rank}, it's '{track}' by {artist}, from '{album}' released in {year}, a standout in {collection}.",
    ]

    templates_es = [
        "¿Sabías que '{track}' de {artist}, en el puesto {rank}, del álbum '{album}' lanzado en {year}, es un clásico de {collection}?",
        "En el puesto {rank}, '{track}' de {artist}, del álbum '{album}' ({year}), destaca como un favorito de {collection}.",
        "Ocupando el lugar {rank}, '{track}' de {artist}, incluido en '{album}' lanzado en {year}, representa lo mejor de {collection}.",
    ]

    templates_pt = [
        "Você sabia? '{track}' do {artist}, na posição {rank}, do álbum '{album}' lançado em {year}, é um clássico de {collection}.",
        "Na posição {rank}, '{track}' do {artist}, do álbum '{album}' ({year}), se destaca como um favorito de {collection}.",
        "Ocupando o lugar {rank}, '{track}' do {artist}, presente em '{album}' lançado em {year}, representa o melhor de {collection}.",
    ]

    en = random.choice(templates_en).format(
        track=track,
        artist=artist,
        rank=rank,
        album=album,
        year=year,
        collection=collection
    )

    es = random.choice(templates_es).format(
        track=track,
        artist=artist,
        rank=rank,
        album=album,
        year=year,
        collection=collection_es
    )

    pt = random.choice(templates_pt).format(
        track=track,
        artist=artist,
        rank=rank,
        album=album,
        year=year,
        collection=collection_pt
    )

    return {
        "en": en,
        "es": es,
        "pt-BR": pt
    }


# ─────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────

def get_or_create_category(session: Session) -> CollectionCategory:
    existing = session.exec(
        select(CollectionCategory).where(
            or_(
                CollectionCategory.slug == CATEGORY_SLUG,
                CollectionCategory.name == CATEGORY_NAME
            )
        )
    ).first()

    if existing:
        if existing.slug != CATEGORY_SLUG:
            existing.slug = CATEGORY_SLUG
            session.add(existing)
            session.commit()
            session.refresh(existing)
        return existing

    category = CollectionCategory(
        name=CATEGORY_NAME,
        slug=CATEGORY_SLUG,
        description="Soft rock favorites from the 70s through the 90s.",
        sort_order=0,
    )

    session.add(category)
    session.commit()
    session.refresh(category)

    return category


def get_or_create_collection(session: Session, category: CollectionCategory, name: str) -> Collection:
    slug = slugify(name)

    existing = session.exec(
        select(Collection).where(Collection.slug == slug)
    ).first()

    if existing:
        return existing

    collection = Collection(
        name=name,
        slug=slug,
        intro="Smooth soft rock favorites.",
        category_id=category.id,
    )

    session.add(collection)
    session.commit()
    session.refresh(collection)

    return collection


def find_artist(session: Session, name: str) -> Artist | None:
    return session.exec(
        select(Artist).where(Artist.artist_name == name)
    ).first()

def find_track_by_spotify_id(session: Session, spotify_id: str) -> Track | None:
    return session.exec(
        select(Track).where(Track.spotify_track_id == spotify_id)
    ).first()

def upsert_collection_ranking_locale(session, ranking_id, lang, intro_text):
    existing = session.exec(
        select(CollectionTrackRankingLocale).where(
            CollectionTrackRankingLocale.collection_track_ranking_id == ranking_id,
            CollectionTrackRankingLocale.lang == lang
        )
    ).first()

    if existing:
        existing.intro_text = intro_text
        session.add(existing)
    else:
        session.add(
            CollectionTrackRankingLocale(
                collection_track_ranking_id=ranking_id,
                lang=lang,
                intro_text=intro_text
            )
        )

def find_ranking(session: Session, collection_id: int, rank: int) -> CollectionTrackRanking | None:
    return session.exec(
        select(CollectionTrackRanking).where(
            CollectionTrackRanking.collection_id == collection_id,
            CollectionTrackRanking.ranking == rank
        )
    ).first()

# ─────────────────────────────────────────────

def main():
    data = load_collection_file(INPUT_FILE)

    with Session(engine) as session:
        category = get_or_create_category(session)

        for collection_data in data["collections"]:
            collection = get_or_create_collection(
                session,
                category,
                collection_data["collection_name"]
            )

            tracks = (
                collection_data["tracks"][:LIMIT]
                if LIMIT else collection_data["tracks"]
            )

            for item in tracks:
                artist = find_artist(session, item["artist_name"])

                if not artist:
                    artist = Artist(artist_name=item["artist_name"])
                    session.add(artist)
                    session.commit()
                    session.refresh(artist)

                spotify = get_spotify_track_data(
                    item["track_name"],
                    item["artist_name"]
                )

                if not spotify:
                    print(f"Skipping {item['track_name']}")
                    continue

                existing_track = find_track_by_spotify_id(
                    session,
                    spotify["spotify_track_id"]
                )

                if existing_track:
                    track = existing_track
                    print(f"Using existing track: {track.track_name}")
                else:
                    track = Track(
                        track_name=item["track_name"],
                        artist_id=artist.id,
                        spotify_track_id=spotify["spotify_track_id"],
                    )

                    session.add(track)
                    session.commit()
                    session.refresh(track)

                    print(f"Created track: {track.track_name}")

                intro = generate_intro(
                    rank=item["rank"],
                    collection=collection.name,
                    track=title_case(item["track_name"]),
                    artist=title_case(item["artist_name"]),
                    album=track.album_name,
                    year=track.year_released,
                )

                existing_ranking = find_ranking(session, collection.id, item["rank"])

                if existing_ranking:
                    ranking = existing_ranking
                    ranking.track_id = track.id
                    ranking.intro = intro["en"]
                    session.add(ranking)
                    session.commit()
                    session.refresh(ranking)
                    print(f"Using existing ranking: {collection.name} #{item['rank']}")
                else:
                    ranking = CollectionTrackRanking(
                        collection_id=collection.id,
                        track_id=track.id,
                        ranking=item["rank"],
                        intro=intro["en"]
                    )

                    session.add(ranking)
                    session.commit()
                    session.refresh(ranking)

                    print(f"Created ranking: {collection.name} #{item['rank']}")

                # 👉 ADD THIS
                upsert_collection_ranking_locale(session, ranking.id, "es", intro["es"])
                upsert_collection_ranking_locale(session, ranking.id, LANG_PTBR, intro[LANG_PTBR])

                session.commit()

                session.add(ranking)
                session.commit()

    print("Import complete.")


if __name__ == "__main__":
    main()