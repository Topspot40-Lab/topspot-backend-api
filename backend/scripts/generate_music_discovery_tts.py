from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine
from backend.config import BUCKETS
from backend.config.tts_config import TTS_PROFILES
from backend.services.tts.elevenlabs_tts import generate_tts_mp3
from backend.services.supabase_storage import upload_bytes


PREFIX_BY_LANG = {
    "en": "Did you know? ... ",
    "es": "¿Sabías que? ... ",
    "pt-BR": "Você sabia que? ... ",
}

BUCKET_LANG = {
    "en": "en",
    "es": "es",
    "pt-BR": "pt-BR",
}

KIND = "detail"
FOLDER = "music-discovery"


def bucket_for_lang(lang: str) -> str:
    return BUCKETS[BUCKET_LANG[lang]][KIND]


def voice_for_lang(lang: str) -> str:
    return TTS_PROFILES[lang][KIND]["voice_id"]


def discovery_key(music_discovery_id: int) -> str:
    return f"{FOLDER}/{music_discovery_id}.mp3"


def tts_text_for(lang: str, discovery_text: str) -> str:
    prefix = PREFIX_BY_LANG[lang]
    return prefix + discovery_text.strip()


def main(lang: str, limit: int | None, overwrite: bool) -> None:
    if lang not in PREFIX_BY_LANG:
        raise ValueError(f"Unsupported language: {lang}")

    bucket = bucket_for_lang(lang)
    voice_id = voice_for_lang(lang)

    where_tts = "" if overwrite else "AND NULLIF(TRIM(COALESCE(mdl.tts_key, '')), '') IS NULL"
    limit_clause = "LIMIT :limit" if limit is not None else ""

    sql = text(f"""
        SELECT
            mdl.id AS locale_id,
            mdl.music_discovery_id,
            mdl.discovery_text,
            md.category,
            md.title
        FROM music_discovery_locale mdl
        JOIN music_discovery md
          ON md.id = mdl.music_discovery_id
        WHERE mdl.language_code = :lang
          AND md.is_active = true
          AND mdl.discovery_text IS NOT NULL
          AND NULLIF(TRIM(mdl.discovery_text), '') IS NOT NULL
          {where_tts}
        ORDER BY mdl.music_discovery_id
        {limit_clause}
    """)

    params = {"lang": lang}
    if limit is not None:
        params["limit"] = limit

    generated = 0
    skipped_missing = 0
    errors = 0

    with Session(engine) as session:
        rows = session.exec(sql.bindparams(**params)).all()

        print(f"Language: {lang}")
        print(f"Bucket: {bucket}")
        print(f"Rows found: {len(rows)}")
        print(f"Overwrite: {overwrite}")
        print("=" * 80)

        for row in rows:
            discovery_id = int(row.music_discovery_id)
            key = discovery_key(discovery_id)
            source_text = (row.discovery_text or "").strip()

            if not source_text:
                skipped_missing += 1
                continue

            full_text = tts_text_for(lang, source_text)

            print(f"Generating {lang}: {discovery_id} | {row.category} | {row.title}")
            print(full_text)

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                generate_tts_mp3(
                    text=full_text,
                    out_path=tmp_path,
                    voice_id=voice_id,
                    overwrite=True,
                    play=False,
                )

                upload_bytes(
                    bucket,
                    key,
                    tmp_path.read_bytes(),
                    "audio/mpeg",
                )

                session.exec(
                    text("""
                        UPDATE music_discovery_locale
                        SET tts_bucket = :tts_bucket,
                            tts_key = :tts_key,
                            updated_at = NOW()
                        WHERE id = :locale_id
                    """).bindparams(
                        tts_bucket=bucket,
                        tts_key=key,
                        locale_id=row.locale_id,
                    )
                )

                generated += 1
                print(f"Uploaded: {bucket}/{key}")

            except Exception as exc:
                errors += 1
                print(f"ERROR {lang} discovery_id={discovery_id}: {exc}")

            finally:
                tmp_path.unlink(missing_ok=True)

        session.commit()

    print()
    print("Done.")
    print(f"Generated: {generated}")
    print(f"Skipped missing: {skipped_missing}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True, choices=["en", "es", "pt-BR"])
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    main(
        lang=args.lang,
        limit=args.limit,
        overwrite=args.overwrite,
    )
