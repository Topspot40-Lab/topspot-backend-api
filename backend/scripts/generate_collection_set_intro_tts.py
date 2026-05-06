from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine
from backend.services.supabase_storage import upload_bytes
from backend.services.tts.elevenlabs_tts import generate_tts_mp3
from backend.config.tts_config import TTS_PROFILES


def normalize_lang(lang: str) -> str:
    if lang == "pt-BR":
        return "ptbr"
    return lang


def tts_profile_lang(lang: str) -> str:
    if lang == "ptbr":
        return "pt-BR"
    return lang


def voice_id_for_lang(lang: str) -> str:
    return TTS_PROFILES[tts_profile_lang(lang)]["artist"]["voice_id"]


def bucket_for_lang(lang: str) -> str:
    if lang == "es":
        return "audio-es"
    if lang == "ptbr":
        return "audio-ptbr"
    return "audio-en"

def query_for_lang(lang: str):
    if lang == "en":
        return text("""
            select id, slug, intro
            from public.collection
            where intro is not null
              and trim(intro) <> ''
            order by id
        """)

    return text("""
        select
            cl.id,
            c.slug,
            cl.intro
        from public.collection_locale cl
        join public.collection c
            on c.id = cl.collection_id
        where cl.language_code = :lang
          and cl.intro is not null
          and trim(cl.intro) <> ''
        order by c.id
    """).bindparams(lang=lang)


def main(lang: str, limit: int | None, overwrite: bool) -> None:
    lang = normalize_lang(lang)

    bucket = bucket_for_lang(lang)
    voice_id = voice_id_for_lang(lang)

    generated = 0
    skipped = 0
    errors = 0

    with Session(engine) as session:
        rows = session.exec(query_for_lang(lang)).all()

        for row in rows:
            if limit is not None and generated >= limit:
                break

            row_id = row[0]
            slug = row[1]
            intro = row[2]

            key = f"collection-set-intro/{slug}.mp3"

            print(f"\n🎯 Processing {lang}: {slug}")

            tmp_path = None

            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                    tmp_path = Path(tmp.name)

                generate_tts_mp3(
                    text=intro,
                    out_path=tmp_path,
                    voice_id=voice_id,
                    overwrite=True,
                    language=lang,
                )

                if not tmp_path.exists() or tmp_path.stat().st_size == 0:
                    raise RuntimeError(f"TTS file was not created or is empty: {tmp_path}")

                with open(tmp_path, "rb") as f:
                    audio_bytes = f.read()

                upload_bytes(
                    bucket=bucket,
                    key=key,
                    data=audio_bytes,
                    content_type="audio/mpeg",
                )

                if lang == "en":
                    session.exec(
                        text("""
                            update public.collection
                            set set_intro_tts_bucket = :bucket,
                                set_intro_tts_key = :key
                            where id = :id
                        """).bindparams(
                            bucket=bucket,
                            key=key,
                            id=row_id,
                        )
                    )
                else:
                    session.exec(
                        text("""
                            update public.collection_locale
                            set set_intro_tts_bucket = :bucket,
                                set_intro_tts_key = :key,
                                updated_at = now()
                            where id = :id
                        """).bindparams(
                            bucket=bucket,
                            key=key,
                            id=row_id,
                        )
                    )

                session.commit()
                generated += 1
                print(f"   ✅ Uploaded {bucket}/{key}")

            except Exception as exc:
                session.rollback()
                errors += 1
                print(f"   ❌ ERROR {slug}: {exc}")

            finally:
                if tmp_path and tmp_path.exists():
                    tmp_path.unlink()

    print("\nDone.")
    print(f"Generated: {generated}")
    print(f"Skipped: {skipped}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True, choices=["en", "es", "ptbr", "pt-BR"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()

    main(
        lang=args.lang,
        limit=args.limit,
        overwrite=args.overwrite,
    )