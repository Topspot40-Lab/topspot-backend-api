from __future__ import annotations

import argparse
import random

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import (
    Collection,
    CollectionCategory,
    CollectionTrackRanking,
    CollectionTrackRankingLocale,
)
from backend.models.dbmodels import Track


TEMPLATES_ES = [
    "En el puesto {rank}, tenemos '{track}' de {artist}, del álbum '{album}' de {year}.",
    "Llegando al número {rank}, suena '{track}' de {artist}, incluido en el álbum '{album}' ({year}).",
    "En la posición {rank}, aparece '{track}' de {artist}, del álbum '{album}' de {year}.",
    "Ahora en el puesto {rank}, '{track}' de {artist}, lanzado en el álbum '{album}' en {year}.",
]

TEMPLATES_PTBR = [
    "Na posição {rank}, temos '{track}' de {artist}, do álbum '{album}' de {year}.",
    "Chegando ao número {rank}, toca '{track}' de {artist}, do álbum '{album}' ({year}).",
    "Na posição {rank}, aparece '{track}' de {artist}, do álbum '{album}' de {year}.",
    "Agora no número {rank}, '{track}' de {artist}, lançado no álbum '{album}' em {year}.",
]


def unknown_for(lang: str) -> str:
    return "desconocido" if lang == "es" else "desconhecido"


def artist_fallback_for(lang: str) -> str:
    return "artista desconocido" if lang == "es" else "artista desconhecido"


def clean_text(value: str | None, fallback: str) -> str:
    value = (value or "").strip()

    if not value:
        return fallback

    if value.lower() in {"none", "null", "unknown", "nan"}:
        return fallback

    return value


def generate_intro(
    lang: str,
    rank: int,
    track: str | None,
    artist: str | None,
    album: str | None,
    year: int | str | None,
) -> str:
    templates = TEMPLATES_ES if lang == "es" else TEMPLATES_PTBR

    unknown = unknown_for(lang)
    artist_fallback = artist_fallback_for(lang)

    return random.choice(templates).format(
        rank=rank,
        track=clean_text(track, unknown),
        artist=clean_text(artist, artist_fallback),
        album=clean_text(album, unknown),
        year=clean_text(str(year) if year is not None else None, unknown),
    )


def locale_exists(session: Session, ranking_id: int, lang: str) -> bool:
    existing = session.exec(
        select(CollectionTrackRankingLocale).where(
            CollectionTrackRankingLocale.collection_track_ranking_id == ranking_id,
            CollectionTrackRankingLocale.lang == lang,
        )
    ).first()

    return existing is not None


def main(lang: str, limit: int | None, overwrite: bool) -> None:
    with Session(engine) as session:
        stmt = (
            select(CollectionTrackRanking, Collection, CollectionCategory, Track)
            .join(Collection, Collection.id == CollectionTrackRanking.collection_id)
            .join(CollectionCategory, CollectionCategory.id == Collection.category_id)
            .join(Track, Track.id == CollectionTrackRanking.track_id)
            .order_by(CollectionCategory.name, Collection.name, CollectionTrackRanking.ranking)
        )

        rows = session.exec(stmt).all()

        inserted = 0
        updated = 0
        skipped = 0

        for ranking, collection, category, track in rows:
            if limit is not None and (inserted + updated) >= limit:
                break

            existing = session.exec(
                select(CollectionTrackRankingLocale).where(
                    CollectionTrackRankingLocale.collection_track_ranking_id == ranking.id,
                    CollectionTrackRankingLocale.lang == lang,
                )
            ).first()

            if existing and not overwrite:
                skipped += 1
                continue

            intro_text = generate_intro(
                lang=lang,
                rank=ranking.ranking,
                track=track.track_name,
                artist=track.artist_display_name,
                album=track.album_name,
                year=track.year_released,
            )

            if existing:
                existing.intro_text = intro_text
                session.add(existing)
                updated += 1
                print(f"Updated {lang}: {category.name} / {collection.name} #{ranking.ranking}")
            else:
                locale = CollectionTrackRankingLocale(
                    collection_track_ranking_id=ranking.id,
                    lang=lang,
                    intro_text=intro_text,
                    tts_key=None,
                )

                session.add(locale)
                inserted += 1
                print(f"Added {lang}: {category.name} / {collection.name} #{ranking.ranking}")

        session.commit()

        print("\nDone.")
        print(f"Inserted: {inserted}")
        print(f"Updated: {updated}")
        print(f"Skipped existing: {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True, choices=["es", "pt-BR"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    main(lang=args.lang, limit=args.limit, overwrite=args.overwrite)