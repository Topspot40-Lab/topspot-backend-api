from __future__ import annotations

import argparse
import os
from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import CollectionTrackRankingLocale
from backend.services.tts.elevenlabs_tts import synthesize_to_file
from backend.services.supabase_storage import upload_bytes


def get_bucket(lang: str) -> str:
    if lang == "es":
        return "audio-es"
    if lang == "pt-BR":
        return "audio-ptbr"
    return "audio-en"


def get_voice_settings(lang: str):
    # Adjust if you want different voices later
    return {
        "voice_id": "dlGxemPxFMTY7iXagmOj",  # your working voice
        "settings": {
            "stability": 0.65,
            "similarity_boost": 0.7,
            "style": 0.25,
            "use_speaker_boost": False,
        },
    }


def main(lang: str, limit: int | None, overwrite: bool):
    bucket = get_bucket(lang)
    voice = get_voice_settings(lang)

    with Session(engine) as session:
        rows = session.exec(
            select(CollectionTrackRankingLocale)
            .where(CollectionTrackRankingLocale.language_code == lang)
        ).all()

        processed = 0
        generated = 0
        skipped = 0
        errors = 0

        for row in rows:
            if limit and processed >= limit:
                break

            text = getattr(row, "intro_text", None)
            if not text:
                skipped += 1
                continue

            ranking_id = row.collection_track_ranking_id
            key = f"collection-intro/{ranking_id}.mp3"

            print(f"\n🎯 Processing ranking_id={ranking_id}")

            # skip if already exists and not overwriting
            if row.intro_key and not overwrite:
                print("   ⏭️ Skipped (already has intro_key)")
                skipped += 1
                continue

            try:
                # generate temp file
                tmp_file = f"/tmp/{ranking_id}.mp3"

                synthesize_to_file(
                    text=text,
                    out_path=tmp_file,
                    voice_id=voice["voice_id"],
                    settings=voice["settings"],
                )

                # read bytes
                with open(tmp_file, "rb") as f:
                    audio_bytes = f.read()

                # upload to Supabase
                upload_bytes(
                    bucket=bucket,
                    key=key,
                    data=audio_bytes,
                    content_type="audio/mpeg",
                )

                # update DB
                row.intro_bucket = bucket
                row.intro_key = key

                session.add(row)
                session.commit()

                generated += 1
                print(f"   ✅ Uploaded → {bucket}/{key}")

                # cleanup temp file
                os.remove(tmp_file)

            except Exception as exc:
                errors += 1
                print(f"   ❌ ERROR: {exc}")

            processed += 1

    print("\n🎉 Done")
    print(f"Processed: {processed}")
    print(f"Generated: {generated}")
    print(f"Skipped: {skipped}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="en", choices=["en", "es", "pt-BR"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()

    main(
        lang=args.lang,
        limit=args.limit,
        overwrite=args.overwrite,
    )