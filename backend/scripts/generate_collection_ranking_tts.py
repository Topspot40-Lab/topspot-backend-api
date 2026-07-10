from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import Collection, CollectionTrackRanking
from backend.config.tts_config import TTS_PROFILES
from backend.services.tts.elevenlabs_tts import generate_tts_mp3
from backend.services.supabase_storage import object_exists_cached, upload_bytes

def tts_key_for(collection_slug: str, ranking: int) -> str:
    return f"collections-intros/{collection_slug}_{ranking:02d}.mp3"


def main(collection_slug: str | None, limit: int | None, overwrite: bool) -> None:
    with Session(engine, expire_on_commit=False) as session:
        stmt = (
            select(CollectionTrackRanking, Collection)
            .join(Collection, Collection.id == CollectionTrackRanking.collection_id)
            .where(CollectionTrackRanking.intro != None)
            .order_by(Collection.slug, CollectionTrackRanking.ranking)
        )

        if collection_slug:
            stmt = stmt.where(Collection.slug == collection_slug)

        rows = session.exec(stmt).all()

        generated = 0
        skipped = 0
        attempted = 0

        profile = TTS_PROFILES["en"]["intro"]
        voice_id = profile["voice_id"]
        settings = profile.get("settings")

        for ranking, collection in rows:
            if not ranking.intro:
                skipped += 1
                continue

            key = tts_key_for(collection.slug, ranking.ranking)

            if not overwrite and object_exists_cached("audio-en", key):
                skipped += 1
                print(f"Skipped existing: {collection.slug} #{ranking.ranking}")
                continue

            if limit is not None and attempted >= limit:
                break

            attempted += 1

            try:
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
                        "audio-en",
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
        session.commit()

        print("\nDone.")
        print(f"Generated: {generated}")
        print(f"Skipped: {skipped}")
        print(f"Attempted: {attempted}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    main(
        collection_slug=args.collection,
        limit=args.limit,
        overwrite=args.overwrite,
    )
