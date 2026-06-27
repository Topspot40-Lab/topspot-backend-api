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
    value = re.sub(r"\bWord count:\s*\d+\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\(\d+\s+words?\)", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value.strip(' "\n\t')


def translate_artist_description(artist_name: str, description: str, language: str) -> str:
    if language == "es":
        prompt = f"""
Translate this TopSpot artist description into natural Mexican Spanish.

Rules:
- Keep it 2 sentences
- Natural spoken narration
- Preserve artist names and song titles
- Do not add facts
- Do not use markdown

Artist: {artist_name}
Text: {description}
"""
        system = "You translate music narration into natural Mexican Spanish."
    else:
        prompt = f"""
Translate this TopSpot artist description into natural Brazilian Portuguese.

Rules:
- Keep it 2 sentences
- Natural spoken narration
- Preserve artist names and song titles
- Do not add facts
- Do not use markdown

Artist: {artist_name}
Text: {description}
"""
        system = "You translate music narration into natural Brazilian Portuguese."

    return clean_text(ask_xai(system, prompt))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--language", choices=LANGS, default=None)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    languages = [args.language] if args.language else list(LANGS)

    sql = text("""
        SELECT
            a.id,
            a.artist_name,
            a.artist_description
        FROM artist a
        LEFT JOIN artist_locale al
          ON al.artist_id = a.id
         AND al.language_code = :language_code
        WHERE a.artist_description IS NOT NULL
          AND (
              al.id IS NULL
              OR al.artist_description_text IS NULL
              OR trim(al.artist_description_text) = ''
          )
        ORDER BY a.id
        LIMIT :limit
    """)

    print("=" * 80)
    print("Generate Missing Artist Locales")
    print(f"Languages: {languages}")
    print(f"Limit:     {args.limit}")
    print(f"Save:      {args.save}")
    print("=" * 80)

    total_updated = 0

    with Session(engine) as session:
        for language in languages:
            print("=" * 80)
            print(f"Language: {language}")
            print("=" * 80)

            rows = session.exec(
                sql.bindparams(
                    language_code=language,
                    limit=args.limit,
                )
            ).mappings().all()

            for row in rows:
                artist_id = row["id"]
                artist_name = row["artist_name"]
                description = row["artist_description"]

                print("-" * 80)
                print(f"{artist_id} | {artist_name} | {language}")

                try:
                    translated = translate_artist_description(
                        artist_name=artist_name,
                        description=description,
                        language=language,
                    )

                    print(translated)

                    if args.save:
                        session.exec(
                            text("""
                                INSERT INTO artist_locale (
                                    artist_id,
                                    language_code,
                                    artist_description_text
                                )
                                VALUES (
                                    :artist_id,
                                    :language_code,
                                    :artist_description_text
                                )
                                ON CONFLICT (artist_id, language_code)
                                DO UPDATE SET
                                    artist_description_text = EXCLUDED.artist_description_text
                            """).bindparams(
                                artist_id=artist_id,
                                language_code=language,
                                artist_description_text=translated,
                            )
                        )
                        session.commit()
                        total_updated += 1

                except Exception as exc:
                    print(f"ERROR: {exc}")

    print("=" * 80)
    print(f"Updated: {total_updated}")
    print("=" * 80)


if __name__ == "__main__":
    main()
