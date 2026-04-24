"""
Import curated Soft Rock 70s-90s collections into TopSpot40.

This version matches the newer backend schema:

Artist.artist_description              -> English artist info
ArtistLocale                           -> ES / PTBR artist info

Track.detail                           -> English track detail
TrackLocale                            -> ES / PTBR track detail

CollectionTrackRanking.intro           -> English collection intro
CollectionTrackRankingLocale           -> ES / PTBR collection intro

MP3 generation is intentionally NOT included here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

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
CATEGORY_SLUG = "soft-rock-70s-90s"

LANG_ES = "es"
LANG_PTBR = "pt-BR"


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""

    return (
        value.lower()
        .replace("'", "")
        .replace("’", "")
        .replace('"', "")
        .replace("–", "-")
        .replace("—", "-")
        .strip()
    )


def load_collection_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


# ─────────────────────────────────────────────
# Placeholder text generators
# Later: wire these to XAI.
# ─────────────────────────────────────────────

def generate_artist_info_text(artist_name: str) -> dict[str, str]:

    system = (
        "You are a knowledgeable, concise music historian for TopSpot40. "
        "Return plain text only. No Markdown, no bold, no bullet points. "
        "Use proper punctuation and contractions."
    )

    user = (
        f"Write a short artist description for a soft rock collection.\n"
        f"Limit to exactly 2–3 sentences and 35–55 words.\n"
        f"Artist: {artist_name}\n"
        f"Do not mention specific songs unless essential.\n"
        f"Focus on their musical style, era, and why listeners remember them.\n"
        f"Keep it smooth, warm, and radio-friendly."
    )

    artist_en = ask_xai(system, user, temperature=0.7)

    # cleanup
    artist_en = artist_en.replace("\n", " ").strip()
    artist_en = artist_en.replace("```", "")

    # remove word-count artifacts
    import re
    artist_en = re.sub(r"\(.*?words.*?\)", "", artist_en, flags=re.IGNORECASE)
    artist_en = re.sub(r"Total:\s*\d+\s*words\.?", "", artist_en, flags=re.IGNORECASE)
    artist_en = re.sub(r"Total words:\s*\d+\.?", "", artist_en, flags=re.IGNORECASE)

    # normalize spacing
    artist_en = re.sub(r"\s+", " ", artist_en).strip()

    # ensure clean ending
    artist_en = artist_en.rstrip(". ") + "."
    artist_en = re.sub(r"Total word count:\s*\d+\.?", "", artist_en, flags=re.IGNORECASE)

    return {
        "en": artist_en,
        "es": (
            f"{artist_name} es conocido por su estilo suave y melódico dentro del soft rock."
        ),
        "ptbr": (
            f"{artist_name} é conhecido por seu estilo suave e melódico dentro do soft rock."
        ),
    }



def generate_track_detail_text(
    track_name: str,
    artist_name: str,
    year_released: int | None,
    fit_reason: str | None,
) -> dict[str, str]:

    system = (
        "You are a knowledgeable, concise music historian for TopSpot40. "
        "Return plain text only. No Markdown, no bold, no bullet points. "
        "Use proper punctuation and contractions."
    )

    user = (
        f"Write a short song detail for a soft rock collection.\n"
        f"Limit to exactly 2–3 sentences and 35–55 words.\n"
        f"Use natural punctuation and contractions (e.g., Rafferty's, it's).\n"
        f"Track: {track_name}\n"
        f"Artist: {artist_name}\n"
        f"Year released: {year_released or 'unknown'}\n"
        f"Collection fit: {fit_reason or 'classic soft rock feel'}\n"
        f"Do not write a countdown intro. Do not mention rank. "
        f"Focus on mood, sound, and why listeners remember it."
    )

    detail_en = ask_xai(system, user, temperature=0.7)

    # cleanup
    # cleanup
    detail_en = detail_en.replace("\n", " ").strip()
    detail_en = detail_en.replace("```", "")

    # remove word-count artifacts
    detail_en = re.sub(r"\(.*?words.*?\)", "", detail_en, flags=re.IGNORECASE)
    detail_en = re.sub(r"Total:\s*\d+\s*words\.?", "", detail_en, flags=re.IGNORECASE)

    # 👉 ADD THIS LINE
    detail_en = re.sub(r"Total words:\s*\d+\.?", "", detail_en, flags=re.IGNORECASE)

    # normalize spacing
    detail_en = re.sub(r"\s+", " ", detail_en).strip()

    # ensure clean ending
    detail_en = detail_en.rstrip(". ") + "."
    detail_en = re.sub(r"Total word count:\s*\d+\.?", "", detail_en, flags=re.IGNORECASE)

    return {
        "en": detail_en,
        "es": (
            f"{track_name} de {artist_name} tiene ese sonido cálido y pulido que define "
            f"el soft rock clásico."
        ),
        "ptbr": (
            f"{track_name} de {artist_name} traz aquele som acolhedor e bem produzido "
            f"que define o soft rock clássico."
        ),
    }

def generate_collection_intro_text(
    rank: int,
    collection_name: str,
    track_name: str,
    artist_name: str,
    fit_reason: str | None,
) -> dict[str, str]:

    system = (
        "You are a friendly, concise radio DJ in the style of Casey Kasem. "
        "Return plain text only. No Markdown, no bold, no bullet points. Use proper punctuation and contractions (e.g., it's, we've)."
    )

    user = (
        f"Write a 1-2 sentence countdown intro.\n"
        f"Rank: {rank}\n"
        f"Collection: {collection_name}\n"
        f"Track: {track_name}\n"
        f"Artist: {artist_name}\n"
        f"Vibe: {fit_reason or 'classic soft rock feel'}"
    )

    intro_en = ask_xai(system, user, temperature=0.7)

    return {
        "en": intro_en,
        "es": (
            f"En el número {rank} de {collection_name}, escuchamos {track_name} "
            f"de {artist_name}."
        ),
        "ptbr": (
            f"No número {rank} de {collection_name}, ouvimos {track_name} "
            f"de {artist_name}."
        ),
    }


# ─────────────────────────────────────────────
# Find/create helpers
# ─────────────────────────────────────────────

def get_or_create_category(session: Session) -> CollectionCategory:
    existing = session.exec(
        select(CollectionCategory).where(CollectionCategory.slug == CATEGORY_SLUG)
    ).first()

    if existing:
        return existing

    category = CollectionCategory(
        name=CATEGORY_NAME,
        slug=CATEGORY_SLUG,
        intro="Soft rock favorites from the 1970s through the 1990s.",
        sort_order=0,
    )

    session.add(category)
    session.commit()
    session.refresh(category)

    print(f"Created collection category: {CATEGORY_NAME}")
    return category


def get_or_create_collection(
    session: Session,
    category: CollectionCategory,
    collection_name: str,
) -> Collection:
    slug = slugify(collection_name)

    existing = session.exec(
        select(Collection).where(Collection.slug == slug)
    ).first()

    if existing:
        if existing.category_id != category.id:
            existing.category_id = category.id
            session.add(existing)
            session.commit()
            session.refresh(existing)

        return existing

    collection = Collection(
        name=collection_name,
        slug=slug,
        intro=f"{collection_name} from the Soft Rock 70s-90s collection group.",
        category_id=category.id,
    )

    session.add(collection)
    session.commit()
    session.refresh(collection)

    print(f"Created collection: {collection_name}")
    return collection


def find_artist(session: Session, artist_name: str) -> Artist | None:
    artists = session.exec(select(Artist)).all()
    target = normalize_text(artist_name)

    for artist in artists:
        if normalize_text(artist.artist_name) == target:
            return artist

    return None


def find_track(session: Session, track_name: str, artist_id: int) -> Track | None:
    tracks = session.exec(
        select(Track).where(Track.artist_id == artist_id)
    ).all()

    target = normalize_text(track_name)

    for track in tracks:
        if normalize_text(track.track_name) == target:
            return track

    return None


def upsert_artist_locale(
    session: Session,
    artist_id: int,
    language_code: str,
    text: str,
) -> None:
    existing = session.exec(
        select(ArtistLocale).where(
            ArtistLocale.artist_id == artist_id,
            ArtistLocale.language_code == language_code,
        )
    ).first()

    if existing:
        existing.artist_description_text = text
        session.add(existing)
    else:
        session.add(
            ArtistLocale(
                artist_id=artist_id,
                language_code=language_code,
                artist_description_text=text,
            )
        )


def upsert_track_locale(
    session: Session,
    track_id: int,
    language_code: str,
    text: str,
) -> None:
    existing = session.exec(
        select(TrackLocale).where(
            TrackLocale.track_id == track_id,
            TrackLocale.language_code == language_code,
        )
    ).first()

    if existing:
        existing.detail_text = text
        session.add(existing)
    else:
        session.add(
            TrackLocale(
                track_id=track_id,
                language_code=language_code,
                detail_text=text,
            )
        )


def upsert_collection_ranking_locale(
    session: Session,
    ranking_id: int,
    lang: str,
    intro_text: str,
) -> None:
    existing = session.exec(
        select(CollectionTrackRankingLocale).where(
            CollectionTrackRankingLocale.collection_track_ranking_id == ranking_id,
            CollectionTrackRankingLocale.lang == lang,
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
                intro_text=intro_text,
            )
        )


# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# Main processing
# ─────────────────────────────────────────────

def get_or_create_artist(session: Session, artist_name: str) -> Artist:
    artist = find_artist(session, artist_name)

    if artist:
        artist_info = generate_artist_info_text(artist_name)

        artist.artist_description = artist_info["en"]
        session.add(artist)
        session.commit()

        upsert_artist_locale(session, artist.id, LANG_ES, artist_info["es"])
        upsert_artist_locale(session, artist.id, LANG_PTBR, artist_info["ptbr"])
        session.commit()

        print(f"Updated artist info: {artist_name}")
        return artist

    artist_info = generate_artist_info_text(artist_name)

    artist = Artist(
        artist_name=artist_name,
        artist_description=artist_info["en"],
        language="en",
    )

    session.add(artist)
    session.commit()
    session.refresh(artist)

    upsert_artist_locale(session, artist.id, LANG_ES, artist_info["es"])
    upsert_artist_locale(session, artist.id, LANG_PTBR, artist_info["ptbr"])
    session.commit()

    print(f"Created artist: {artist_name}")
    return artist


def get_or_create_track(
    session: Session,
    artist: Artist,
    item: dict[str, Any],
) -> Track:
    track_name = item["track_name"]
    artist_name = item["artist_name"]
    year_released = item.get("year_released")
    fit_reason = item.get("fit_reason")

    existing = find_track(session, track_name, artist.id)

    if existing:
        detail = generate_track_detail_text(
            track_name=track_name,
            artist_name=artist_name,
            year_released=year_released,
            fit_reason=fit_reason,
        )

        existing.detail = detail["en"]
        session.add(existing)
        session.commit()

        upsert_track_locale(session, existing.id, LANG_ES, detail["es"])
        upsert_track_locale(session, existing.id, LANG_PTBR, detail["ptbr"])
        session.commit()

        print(f"Updated detail: {track_name} - {artist_name}")
        return existing

    # Wire this when ready.
    spotify_data = get_spotify_track_data(track_name, artist_name)

    if not spotify_data:
        print(f"❌ Skipping (no Spotify match): {track_name} - {artist_name}")
        return None

    if not spotify_data.get("spotify_track_id"):
        raise ValueError(f"Missing spotify_track_id for {track_name} - {artist_name}")

    detail = generate_track_detail_text(
        track_name=track_name,
        artist_name=artist_name,
        year_released=year_released,
        fit_reason=fit_reason,
    )

    if spotify_data.get("spotify_artist_id") and not artist.spotify_artist_id:
        artist.spotify_artist_id = spotify_data["spotify_artist_id"]

    if spotify_data.get("artist_artwork") and not artist.artist_artwork:
        artist.artist_artwork = spotify_data["artist_artwork"]

    session.add(artist)

    track = Track(
        track_name=track_name,
        album_name=spotify_data.get("album_name"),
        artist_display_name=artist_name,
        spotify_track_id=spotify_data["spotify_track_id"],
        duration_ms=spotify_data.get("duration_ms"),
        popularity=spotify_data.get("popularity"),
        album_artwork=spotify_data.get("album_artwork"),
        year_released=spotify_data.get("year_released") or year_released,
        artist_id=artist.id,
        detail=detail["en"],
        language="en",
    )

    session.add(track)
    session.commit()
    session.refresh(track)

    upsert_track_locale(session, track.id, LANG_ES, detail["es"])
    upsert_track_locale(session, track.id, LANG_PTBR, detail["ptbr"])
    session.commit()

    print(f"Created track: {track_name} - {artist_name}")
    return track


def create_or_update_collection_ranking(
    session: Session,
    collection: Collection,
    track: Track,
    item: dict[str, Any],
) -> None:
    rank = int(item["rank"])
    track_name = item["track_name"]
    artist_name = item["artist_name"]
    fit_reason = item.get("fit_reason")

    intro = generate_collection_intro_text(
        rank=rank,
        collection_name=collection.name,
        track_name=track_name,
        artist_name=artist_name,
        fit_reason=fit_reason,
    )

    existing = session.exec(
        select(CollectionTrackRanking).where(
            CollectionTrackRanking.collection_id == collection.id,
            CollectionTrackRanking.track_id == track.id,
        )
    ).first()

    if existing:
        existing.ranking = rank
        existing.intro = intro["en"]
        ranking = existing
        session.add(ranking)
    else:
        ranking = CollectionTrackRanking(
            collection_id=collection.id,
            track_id=track.id,
            ranking=rank,
            intro=intro["en"],
        )
        session.add(ranking)
        session.commit()
        session.refresh(ranking)

    session.commit()

    upsert_collection_ranking_locale(session, ranking.id, LANG_ES, intro["es"])
    upsert_collection_ranking_locale(session, ranking.id, LANG_PTBR, intro["ptbr"])
    session.commit()


def validate_input_shape(data: dict[str, Any]) -> None:
    if "collections" not in data:
        raise ValueError("Input JSON must contain a top-level 'collections' key.")

    for collection in data["collections"]:
        if "collection_name" not in collection:
            raise ValueError("Each collection must contain 'collection_name'.")

        if "tracks" not in collection:
            raise ValueError(
                f"Collection {collection['collection_name']} is missing 'tracks'."
            )

        for item in collection["tracks"]:
            for key in ["rank", "track_name", "artist_name"]:
                if key not in item:
                    raise ValueError(
                        f"Track item in {collection['collection_name']} is missing {key}."
                    )


def main() -> None:
    data = load_collection_file(INPUT_FILE)
    validate_input_shape(data)

    with Session(engine) as session:
        category = get_or_create_category(session)

        for collection_data in data["collections"]:
            collection_name = collection_data["collection_name"]
            collection = get_or_create_collection(
                session=session,
                category=category,
                collection_name=collection_name,
            )

            print(f"\nProcessing collection: {collection_name}")

            for item in collection_data["tracks"][:3]:
                artist = get_or_create_artist(session, item["artist_name"])
                track = get_or_create_track(session, artist, item)

                if not track:
                    continue

                create_or_update_collection_ranking(
                    session=session,
                    collection=collection,
                    track=track,
                    item=item,
                )

    print("\nSoft Rock collection import complete.")


if __name__ == "__main__":
    main()
