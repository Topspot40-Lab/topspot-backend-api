from __future__ import annotations

import argparse
import os

from openai import OpenAI
from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine

def normalize_lang(lang: str) -> str:
    if lang == "pt-BR":
        return "ptbr"
    return lang


def target_language_name(lang: str) -> str:
    if lang == "es":
        return "Mexican Spanish"
    if lang == "ptbr":
        return "Brazilian Portuguese"
    raise ValueError(f"Unsupported language: {lang}")


def translate_collection_intro(source_text: str, lang: str) -> str:
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY environment variable is not set.")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1",
    )

    target = target_language_name(lang)

    prompt = f"""
Rewrite the following TopSpot40 Collections Radio intro in natural {target}.

RULES:
- Keep the same meaning, tone, and structure
- Keep it smooth for spoken radio playback
- Do NOT add new information
- Do NOT use exclamation marks
- Use natural radio phrasing
- Keep "TopSpot40" unchanged
- Translate "Collections Radio" naturally
- Translate "collection group" naturally
- Keep artist, collection, and period names clear
- Use "..." only if needed, not special ellipsis characters

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

    cleaned = (
        result.strip()
        .replace("…", "...")
        .replace("!", "")
        .replace("\r\n", " ")
        .replace("\n", " ")
    )

    cleaned = " ".join(cleaned.split())

    return cleaned


def main(lang: str | None, limit: int | None, overwrite: bool) -> None:
    if lang:
        lang = normalize_lang(lang)

    languages = [lang] if lang else ["es", "ptbr"]

    with Session(engine) as session:
        rows = session.exec(
            text("""
                select
                    cl.id as locale_id,
                    c.id as collection_id,
                    c.slug,
                    c.intro as source_intro,
                    cl.language_code,
                    cl.intro as existing_intro
                from public.collection_locale cl
                join public.collection c
                    on c.id = cl.collection_id
                where c.intro is not null
                  and trim(c.intro) <> ''
                  and cl.language_code = any(:langs)
                order by c.id, cl.language_code
            """).bindparams(langs=languages)
        ).all()

        processed = 0
        updated = 0
        skipped = 0
        errors = 0

        for row in rows:
            if limit is not None and processed >= limit:
                break

            locale_id = row[0]
            slug = row[2]
            source_intro = row[3]
            language_code = row[4]
            existing_intro = row[5]

            if existing_intro and not overwrite:
                print(f"⏭️ Skipped existing {language_code}: {slug}")
                skipped += 1
                continue

            print(f"\n🎯 Processing {language_code}: {slug}")

            try:
                localized = translate_collection_intro(
                    source_text=source_intro,
                    lang=language_code,
                )

                session.exec(
                    text("""
                        update public.collection_locale
                        set intro = :intro,
                            updated_at = now()
                        where id = :id
                    """).bindparams(
                        intro=localized,
                        id=locale_id,
                    )
                )

                updated += 1
                print(f"   ✅ {localized}")

            except Exception as exc:
                errors += 1
                print(f"   ❌ ERROR {language_code} {slug}: {exc}")

            processed += 1

        session.commit()

    print("\nDone.")
    print(f"Processed locale rows: {processed}")
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=["es", "ptbr", "pt-BR"], default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    main(
        lang=args.lang,
        limit=args.limit,
        overwrite=args.overwrite,
    )