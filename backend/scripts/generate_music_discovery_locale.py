from __future__ import annotations

import argparse
import re

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine
from backend.services.xai_client import ask_xai


LANGS = ("es", "pt-BR")


def clean_text(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\*\*", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \n\t\"")


def target_language_name(lang: str) -> str:
    if lang == "es":
        return "natural Mexican Spanish"
    if lang == "pt-BR":
        return "natural Brazilian Portuguese"
    raise ValueError(f"Unsupported language: {lang}")


def translate_discovery_text(discovery_text: str, lang: str) -> str:
    target = target_language_name(lang)

    prompt = f"""
Translate this TopSpot Music Discovery Moment into {target}.

RULES:
- Preserve the meaning
- Do not add facts
- Keep proper names, song titles, album titles, and place names natural
- Natural spoken narration, not formal writing
- Warm, clear, and easy for an older listener to understand
- Do NOT start with "Did you know"
- Return only the translated discovery text

DISCOVERY_TEXT:
{discovery_text}
""".strip()

    return clean_text(
        ask_xai(
            "You are a professional bilingual music radio narrator.",
            prompt,
            temperature=0.3,
        )
    )


def main(lang: str, limit: int | None, discovery_id: int | None, overwrite: bool, save: bool) -> None:
    if lang not in LANGS:
        raise ValueError(f"Unsupported lang: {lang}. Supported: {LANGS}")

    where_id = "AND md.id = :discovery_id" if discovery_id is not None else ""

    where_missing = "" if overwrite else """
        AND NOT EXISTS (
            SELECT 1
            FROM music_discovery_locale existing
            WHERE existing.music_discovery_id = md.id
              AND existing.language_code = :lang
        )
    """

    limit_clause = "LIMIT :limit" if limit is not None else ""

    sql = text(f"""
        SELECT
            md.id,
            md.category,
            md.topic,
            md.title,
            en.discovery_text
        FROM music_discovery md
        JOIN music_discovery_locale en
          ON en.music_discovery_id = md.id
         AND en.language_code = 'en'
        WHERE md.is_active = true
          {where_id}
          {where_missing}
        ORDER BY md.id
        {limit_clause}
    """)

    params = {"lang": lang}
    if limit is not None:
        params["limit"] = limit
    if discovery_id is not None:
        params["discovery_id"] = discovery_id

    with Session(engine) as session:
        rows = session.exec(sql.bindparams(**params)).all()

        processed = 0
        inserted_or_updated = 0
        errors = 0

        for row in rows:
            processed += 1
            print("=" * 80)
            print(f"ID: {row.id}")
            print(f"Category: {row.category}")
            print(f"EN Title: {row.title}")
            print(f"EN Text: {row.discovery_text}")

            try:
                translated_text = translate_discovery_text(
                    discovery_text=row.discovery_text,
                    lang=lang,
                )

                print(f"{lang} Text: {translated_text}")

                if save:
                    existing = session.exec(
                        text("""
                            SELECT id
                            FROM music_discovery_locale
                            WHERE music_discovery_id = :music_discovery_id
                              AND language_code = :lang
                            LIMIT 1
                        """).bindparams(
                            music_discovery_id=row.id,
                            lang=lang,
                        )
                    ).first()

                    if existing:
                        session.exec(
                            text("""
                                UPDATE music_discovery_locale
                                SET discovery_text = :discovery_text,
                                    tts_bucket = NULL,
                                    tts_key = NULL
                                WHERE id = :locale_id
                            """).bindparams(
                                discovery_text=translated_text,
                                locale_id=existing.id,
                            )
                        )
                        action = "Updated"
                    else:
                        session.exec(
                            text("""
                                INSERT INTO music_discovery_locale
                                    (music_discovery_id, language_code, discovery_text)
                                VALUES
                                    (:music_discovery_id, :lang, :discovery_text)
                            """).bindparams(
                                music_discovery_id=row.id,
                                lang=lang,
                                discovery_text=translated_text,
                            )
                        )
                        action = "Inserted"

                    session.commit()
                    inserted_or_updated += 1
                    print(f"✅ {action} {lang} for ID {row.id}")

            except Exception as exc:
                errors += 1
                if save:
                    session.rollback()
                print(f"ERROR on ID {row.id}: {exc}")
                continue

        print("\nDone.")
        print(f"Language: {lang}")
        print(f"Rows processed: {processed}")
        print(f"Inserted/updated: {inserted_or_updated}")
        print(f"Errors: {errors}")
        print(f"Save mode: {save}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True, choices=LANGS)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--discovery-id", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    main(
        lang=args.lang,
        limit=args.limit,
        discovery_id=args.discovery_id,
        overwrite=args.overwrite,
        save=args.save,
    )