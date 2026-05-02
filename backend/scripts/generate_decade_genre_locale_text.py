from __future__ import annotations

import argparse
import os

from openai import OpenAI
from sqlalchemy import text
from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import DecadeGenre


def target_language_name(lang: str) -> str:
    if lang == "es":
        return "Mexican Spanish"
    if lang == "pt-BR":
        return "Brazilian Portuguese"
    raise ValueError(f"Unsupported language: {lang}")


def transition_hint(lang: str) -> str:
    if lang == "es":
        return "Use phrases like 'Y ahora...', 'A continuación...', or 'Aquí vamos...'"
    if lang == "pt-BR":
        return "Use phrases like 'E agora...', 'A seguir...', or 'Aqui vamos nós...'"
    raise ValueError(f"Unsupported language: {lang}")


def translate_decade_genre(source_text: str, lang: str) -> str:
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY environment variable is not set.")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1",
    )

    target = target_language_name(lang)

    prompt = f"""
    Rewrite the following short radio intro in natural {target}.

    RULES:
    - EXACTLY 2 sentences
    - Keep the SAME tone, meaning, and structure
    - Keep it SHORT and smooth for radio playback
    - Do NOT add new information
    - Spell out decades in words (e.g., "anos oitenta", "los años ochenta")
    - Do NOT use exclamation marks
    - Use "..." (three dots), not special characters
    - Use natural radio phrasing (avoid overly formal words)
    - Keep spelling clean and correct (no duplicated letters)

    {transition_hint(lang)}

    TEXT:
    {source_text}
    """.strip()

    response = client.chat.completions.create(
        model="grok-3-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a professional bilingual music radio narrator.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )

    result = response.choices[0].message.content
    if not result:
        raise RuntimeError("XAI returned an empty response.")

    return result.strip()


def main(lang: str | None, limit: int | None, overwrite: bool) -> None:
    languages = [lang] if lang else ["es", "pt-BR"]

    with Session(engine) as session:
        rows = session.exec(
            text("""
                SELECT id, slug, description
                FROM public.decade_genre
                WHERE description IS NOT NULL
                AND trim(description) <> ''
                ORDER BY id
            """)
        ).all()

        processed = 0
        inserted_or_updated = 0
        skipped = 0
        errors = 0

        for row in rows:
            if limit is not None and processed >= limit:
                break

            row_id = row[0]
            slug = row[1]
            source_description = row[2]

            if not source_description:
                skipped += 1
                continue

            print(f"\n🎯 Processing {slug}")

            for language_code in languages:
                existing = session.exec(
                    text("""
                        SELECT id
                        FROM public.decade_genre_locale
                        WHERE decade_genre_id = :id
                        AND language_code = :lang
                    """).bindparams(
                        id=row_id,
                        lang=language_code,
                    )
                ).first()

                if existing and not overwrite:
                    print(f"   ⏭️ Skipped existing {language_code}")
                    skipped += 1
                    continue

                try:
                    localized = translate_decade_genre(
                        source_description,
                        language_code,
                    )

                    # 🔧 CLEANUP GOES HERE
                    if language_code == "pt-BR":
                        localized = (
                            localized
                            .replace("mmil", "mil")
                            .replace("!", "")
                            .replace("…", "...")
                            .replace("Aqui vamos nós...", "E agora...")
                            .replace("narrativas", "histórias")
                            .strip()
                        )

                    if language_code == "es":
                        localized = localized.replace("…", "...")

                except Exception as exc:
                    errors += 1
                    print(f"   ❌ ERROR {language_code}: {exc}")
                    continue

                session.exec(
                    text("""
                        INSERT INTO public.decade_genre_locale (
                            decade_genre_id,
                            language_code,
                            description
                        )
                        VALUES (:id, :lang, :desc)
                        ON CONFLICT (decade_genre_id, language_code)
                        DO UPDATE SET description = EXCLUDED.description
                    """).bindparams(
                        id=row_id,
                        lang=language_code,
                        desc=localized,
                    )
                )

                inserted_or_updated += 1
                print(f"   ✅ {language_code}: {localized}")

            processed += 1

        session.commit()

    print("\nDone.")
    print(f"Processed decade_genre rows: {processed}")
    print(f"Inserted/updated locale rows: {inserted_or_updated}")
    print(f"Skipped: {skipped}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=["es", "pt-BR"], default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    main(
        lang=args.lang,
        limit=args.limit,
        overwrite=args.overwrite,
    )