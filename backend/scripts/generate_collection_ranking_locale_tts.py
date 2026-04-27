from __future__ import annotations

import argparse
from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import (
    Collection,
    CollectionTrackRanking,
    CollectionTrackRankingLocale,
)
import tempfile
from pathlib import Path

from backend.config.tts_config import TTS_PROFILES
from backend.services.tts.elevenlabs_tts import generate_tts_mp3
from backend.services.supabase_storage import upload_bytes


def bucket_for_lang(lang: str) -> str:
    if lang == "es":
        return "audio-es"
    if lang == "pt-BR":
        return "audio-ptbr"
    return "audio-en"


def tts_key_for(collection_slug: str, ranking: int) -> str:
    return f"collections-intros/{collection_slug}_{ranking:02d}.mp3"

def profile_for_lang(lang: str) -> dict:
    return TTS_PROFILES[lang]["intro"]


def main(lang: str, limit: int | None, overwrite: bool) -> None:
    with Session(engine) as session:
        stmt = (
            select(CollectionTrackRankingLocale, CollectionTrackRanking, Collection)
            .join(
                CollectionTrackRanking,
                CollectionTrackRanking.id == CollectionTrackRankingLocale.collection_track_ranking_id,
            )
            .join(Collection, Collection.id == CollectionTrackRanking.collection_id)
            .where(CollectionTrackRankingLocale.lang == lang)
            .order_by(Collection.slug, CollectionTrackRanking.ranking)
        )

        rows = session.exec(stmt).all()

        generated = 0
        skipped = 0
        attempted = 0

        for locale, ranking, collection in rows:
            if limit is not None and attempted >= limit:
                break

            attempted += 1

            if locale.tts_key and not overwrite:
                skipped += 1
                continue

            if not locale.intro_text:
                skipped += 1
                continue

            key = tts_key_for(collection.slug, ranking.ranking)
            bucket = bucket_for_lang(lang)

            try:
                profile = profile_for_lang(lang)
                voice_id = profile["voice_id"]
                settings = profile["settings"]

                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp_path = Path(tmp.name)

                try:
                    generate_tts_mp3(
                        text=locale.intro_text,
                        out_path=tmp_path,
                        voice_id=voice_id,
                        overwrite=True,
                        play=False,
                        settings=settings,
                        language=lang,
                    )

                    upload_bytes(
                        bucket,
                        key,
                        tmp_path.read_bytes(),
                        content_type="audio/mpeg",
                    )

                finally:
                    tmp_path.unlink(missing_ok=True)

                locale.tts_key = key
                generated += 1

                print(f"Generated {lang}: {collection.slug} #{ranking.ranking}")
                print(f"Attempted: {attempted}")

            except Exception as e:
                print(f"ERROR {collection.slug} #{ranking.ranking}: {e}")

        session.commit()

        print("\nDone.")
        print(f"Generated: {generated}")
        print(f"Skipped: {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True, choices=["es", "pt-BR"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()

    main(lang=args.lang, limit=args.limit, overwrite=args.overwrite)