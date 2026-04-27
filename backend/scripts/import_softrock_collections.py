from __future__ import annotations

import json
import re
import random
import sys
from pathlib import Path
from typing import Any

from sqlmodel import Session, select
from sqlalchemy import or_, func

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


if len(sys.argv) > 1:
    INPUT_FILE = Path(sys.argv[1])
else:
    INPUT_FILE = Path("data/softrock/softrock_70s_90s_collections.json")

CATEGORY_NAME = "Soft Rock 70s-90s"
CATEGORY_SLUG = "soft_rock_70s_90s"

LANG_ES = "es"
LANG_PTBR = "pt-BR"

LIMIT = 45  # set to None for full run


# ─────────────────────────────────────────────

def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower().strip()).strip("-")

def title_case(value: str) -> str:
    value_clean = value.lower().strip()

    special = {
        "bee gees": "Bee Gees",
        "foreigner": "Foreigner",
        "michael mcdonald": "Michael McDonald",
        "arthur's theme (best that you can do)": "Arthur's Theme (Best That You Can Do)",
        "you're the inspiration": "You're the Inspiration",
        "if ever you're in my arms again": "If Ever You're in My Arms Again",
        "i just called to say i love you": "I Just Called to Say I Love You",
        "earth wind and fire": "Earth, Wind & Fire",
        "nsync": "NSYNC",
    }

    if value_clean in special:
        return special[value_clean]

    return value.title().replace("'S", "'s")

def artist_pt_phrase(artist: str) -> str:
    special = {
        "Bee Gees": "dos Bee Gees",
        "Foreigner": "de Foreigner",
    }
    return special.get(artist, f"de {artist}")


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
    text = re.sub(r"\*\*", "", text)

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
    text = re.sub(r"\*\*", "", text)

    return {
        "en": text,
        "es": f"{track_name} de {artist_name} tiene un sonido suave y emocional.",
        "ptbr": f"{track_name} de {artist_name} tem um som suave e emocional.",
    }

TEMPLATES_EN = [
    "Coming in at number {rank}, it's '{track}' by {artist}, from '{album}' released in {year}, a standout in {collection}.",
    "Holding the number {rank} spot, '{track}' by {artist}, from '{album}' released in {year}, shines in {collection}.",
    "At number {rank}, we’ve got '{track}' by {artist}, off '{album}' from {year}, right here in {collection}.",
    "Did you know? '{track}' by {artist}, at rank {rank}, from '{album}' ({year}), is a {collection} classic.",
]

TEMPLATES_ES = [
    "En el puesto {rank}, '{track}' de {artist}, del álbum '{album}' ({year}), destaca en {collection}.",
    "¿Sabías que '{track}' de {artist}, en el puesto {rank}, del álbum '{album}' lanzado en {year}, es un clásico de {collection}?",
]

TEMPLATES_PTBR = [
    "Na posição {rank}, '{track}' {artist}, do álbum '{album}' ({year}), é um dos destaques do soft rock romântico.",
    "Você sabia? '{track}' {artist}, na posição {rank}, do álbum '{album}' lançado em {year}, é um clássico do soft rock romântico.",
]


def generate_intro(rank, collection, track, artist, album, year):
    collection_es = "Canciones románticas de soft rock"
    collection_ptbr = "Canções românticas de soft rock"
    artist_ptbr = artist_pt_phrase(artist)

    en = random.choice(TEMPLATES_EN).format(
        rank=rank,
        collection=collection,
        track=track,
        artist=artist,
        album=album,
        year=year,
    )

    es = random.choice(TEMPLATES_ES).format(
        rank=rank,
        collection=collection_es,
        track=track,
        artist=artist,
        album=album,
        year=year,
    )

    ptbr = random.choice(TEMPLATES_PTBR).format(
        rank=rank,
        collection=collection_ptbr,
        track=track,
        artist=artist_ptbr,
        album=album,
        year=year,
    )

    return {
        "en": en,
        "es": es,
        "ptbr": ptbr,
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
        select(Artist).where(
            func.lower(Artist.artist_name) == name.lower()
        )
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
                artist_name = title_case(item["artist_name"])
                track_name = title_case(item["track_name"])

                artist = find_artist(session, artist_name)

                if not artist:
                    artist = Artist(artist_name=artist_name)
                    session.add(artist)
                    session.commit()
                    session.refresh(artist)

                if not artist.artist_description:
                    artist_info = generate_artist_info_text(artist_name)
                    artist.artist_description = artist_info["en"]
                    session.add(artist)
                    session.commit()
                    print(f"Updated artist description: {artist_name}")

                spotify = get_spotify_track_data(track_name, artist_name)

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
                        track_name=title_case(item["track_name"]),
                        album_name=spotify.get("album_name"),
                        artist_display_name=title_case(item["artist_name"]),
                        spotify_track_id=spotify["spotify_track_id"],
                        duration_ms=spotify.get("duration_ms"),
                        popularity=spotify.get("popularity"),
                        album_artwork=spotify.get("album_artwork"),
                        year_released=item.get("year_released") or spotify.get("year_released"),
                        artist_id=artist.id,
                        language="en",
                    )

                    session.add(track)
                    session.commit()
                    session.refresh(track)

                    print(f"Created track: {track.track_name}")

                if not track.detail:
                    detail = generate_track_detail_text(
                        track_name=track_name,
                        artist_name=artist_name,
                    )
                    track.detail = detail["en"]
                    session.add(track)
                    session.commit()
                    print(f"Updated track detail: {track_name}")

                intro = generate_intro(
                    rank=item["rank"],
                    collection=collection.name,
                    track=track_name,
                    artist=artist_name,
                    album=item.get("album_name") or track.album_name,
                    year=item.get("year_released") or track.year_released,
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

                # Upsert localized intros
                upsert_collection_ranking_locale(session, ranking.id, "es", intro["es"])
                upsert_collection_ranking_locale(session, ranking.id, LANG_PTBR, intro["ptbr"])

                session.commit()

    print("Import complete.")


if __name__ == "__main__":
    main()