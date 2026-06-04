from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from sqlmodel import Session, select

from backend.config.tts_config import TTS_PROFILES
from backend.database import engine
from backend.models.collection_models import Collection, CollectionTrackRanking
from backend.services.supabase_storage import upload_bytes
from backend.services.tts.elevenlabs_tts import generate_tts_mp3


HERITAGE_SLUGS = (
    "mexican_american_favorites",
    "traditional_mexican_favorites",
    "great_american_songbook",
    "crooner_classics",
    "traditional_hymns",
    "southern_gospel_favorites",
    "bluegrass_favorites",
    "patriotic_favorites",
    "railroad_train_songs",
    "cowboy_songs_western_favorites",
    "american_folk_heroes",
    "western_heritage_favorites",
    "civil_war_songs",
    "celtic_favorites",
    "italian_favorites",
    "german_heritage_favorites",
    "brazilian_classics",
    "african_american_heritage_favorites",
)


def bucket_for_lang() -> str:
    return "audio-en"


def tts_key_for(collection_slug: str, ranking: int) -> str:
    return f"collections-intros/{collection_slug}_{ranking:02d}.mp3"


def profile_for_lang() -> dict:
    return TTS_PROFILES["en"]["intro"]


def main(limit: int | None) -> None:
    with Session(engine) as session:
        stmt = (
            select(CollectionTrackRanking, Collection)
            .join(Collection, Collection.id == CollectionTrackRanking.collection_id)
            .where(Collection.slug.in_(HERITAGE_SLUGS))
            .order_by(Collection.slug, CollectionTrackRanking.ranking)
        )

        rows = session.exec(stmt).all()

        generated = 0
        skipped = 0
        attempted = 0

        for ranking, collection in rows:
            if limit is not None and attempted >= limit:
                break

            attempted += 1

            if not ranking.intro:
                skipped += 1
                continue

            key = tts_key_for(collection.slug, ranking.ranking)
            bucket = bucket_for_lang()

            try:
                profile = profile_for_lang()
                voice_id = profile["voice_id"]
                settings = profile["settings"]

                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp_path = Path(tmp.name)

                try:
                    generate_tts_mp3(
                        text=ranking.intro,
                        out_path=tmp_path,
                        voice_id=voice_id,
                        overwrite=True,
                        play=False,
                        settings=settings,
                        language="en",
                    )

                    upload_bytes(
                        bucket,
                        key,
                        tmp_path.read_bytes(),
                        content_type="audio/mpeg",
                    )

                finally:
                    tmp_path.unlink(missing_ok=True)

                generated += 1
                print(f"Generated en: {collection.slug} #{ranking.ranking}")
                print(f"Attempted: {attempted}")

            except Exception as e:
                print(f"ERROR {collection.slug} #{ranking.ranking}: {e}")

        print("\nDone.")
        print(f"Attempted: {attempted}")
        print(f"Generated: {generated}")
        print(f"Skipped: {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()

    main(limit=args.limit)