from __future__ import annotations

import argparse
import re

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine
from backend.services.xai_client import ask_xai


LANGS = ("en", "es", "pt-BR")


def clean_text(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\*\*", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \n\t\"")


def make_english_short_detail(track_name: str, artist: str | None, year: int | None, detail: str) -> str:
    prompt = f"""
Create a TopSpot short detail for this song.

RULES:
- One sentence only
- 20 to 35 words
- Include the track name naturally
- Usually do not include the artist unless it helps the sentence
- Sounds good when spoken before the song
- Focus on facts, achievements, inspiration, recording history, chart success, or cultural impact
- Do NOT reuse radio-host phrases from the source text
- Do NOT use phrases like "Let's", "Now", "Imagine", "Picture this", or similar narration setup language
- No DJ filler
- No "stay tuned", "keep listening", "folks", "right here", or sign-off lines
- Do not add facts that are not supported by the source text
- Return only the sentence

TRACK:
{track_name}

ARTIST:
{artist or ""}

YEAR:
{year or ""}

SOURCE DETAIL:
{detail}
""".strip()

    return clean_text(
        ask_xai(
            "You are a concise music radio script editor for TopSpot.",
            prompt,
            temperature=0.3,
        )
    )


def translate_short_detail(short_detail: str, lang: str) -> str:
    if lang == "es":
        target = "natural Mexican Spanish"
    elif lang == "pt-BR":
        target = "natural Brazilian Portuguese"
    else:
        raise ValueError(f"Unsupported translation language: {lang}")

    prompt = f"""
Translate this TopSpot short song detail into {target}.

RULES:
- One sentence only
- Preserve the meaning
- Do not add facts
- Keep song titles as-is when appropriate
- Natural spoken narration, not formal writing
- No DJ filler
- Return only the translated sentence

TEXT:
{short_detail}
""".strip()

    return clean_text(
        ask_xai(
            "You are a professional bilingual music radio narrator.",
            prompt,
            temperature=0.3,
        )
    )


def main(limit: int | None, track_id: int | None, overwrite: bool, save: bool, langs: list[str]) -> None:
    bad_langs = [lang for lang in langs if lang not in LANGS]
    if bad_langs:
        raise ValueError(f"Unsupported lang(s): {bad_langs}. Supported: {LANGS}")

    where_track = "AND t.id = :track_id" if track_id is not None else ""

    if overwrite:
        where_missing = ""
    else:
        conditions = []
        if "en" in langs:
            conditions.append("NULLIF(TRIM(COALESCE(t.short_detail, '')), '') IS NULL")
        if "es" in langs:
            conditions.append("""
                EXISTS (
                    SELECT 1 FROM track_locale tl
                    WHERE tl.track_id = t.id
                      AND tl.language_code = 'es'
                      AND NULLIF(TRIM(COALESCE(tl.short_detail_text, '')), '') IS NULL
                )
            """)
        if "pt-BR" in langs:
            conditions.append("""
                EXISTS (
                    SELECT 1 FROM track_locale tl
                    WHERE tl.track_id = t.id
                      AND tl.language_code = 'pt-BR'
                      AND NULLIF(TRIM(COALESCE(tl.short_detail_text, '')), '') IS NULL
                )
            """)
        where_missing = "AND (" + " OR ".join(conditions) + ")" if conditions else ""

    limit_clause = "LIMIT :limit" if limit is not None else ""

    sql = text(f"""
        SELECT
            t.id,
            t.track_name,
            t.artist_display_name,
            t.year_released,
            t.detail,
            t.short_detail
        FROM track t
        WHERE t.detail IS NOT NULL
          AND NULLIF(TRIM(t.detail), '') IS NOT NULL
          {where_missing}
          {where_track}
          AND (
            EXISTS (SELECT 1 FROM track_ranking tr WHERE tr.track_id = t.id)
            OR EXISTS (SELECT 1 FROM collection_track_ranking ctr WHERE ctr.track_id = t.id)
          )
        ORDER BY t.id
        {limit_clause}
    """)

    params = {}
    if limit is not None:
        params["limit"] = limit
    if track_id is not None:
        params["track_id"] = track_id

    with Session(engine) as session:
        rows = session.exec(sql.bindparams(**params)).all()

        processed = 0
        updated = 0
        errors = 0

        for row in rows:
            processed += 1
            row_updates = 0

            print("=" * 80)
            print(f"ID: {row.id}")
            print(f"Track: {row.track_name}")
            print(f"Artist: {row.artist_display_name}")
            print(f"Year: {row.year_released}")

            english_short = (row.short_detail or "").strip()

            try:
                if "en" in langs and (overwrite or not english_short):
                    english_short = make_english_short_detail(
                        track_name=row.track_name,
                        artist=row.artist_display_name,
                        year=row.year_released,
                        detail=row.detail,
                    )
                    print(f"EN: {english_short}")

                    if save:
                        session.execute(
                            text("""
                                UPDATE track
                                SET short_detail = :short_detail
                                WHERE id = :track_id
                            """),
                            {"short_detail": english_short, "track_id": row.id},
                        )
                        updated += 1
                        row_updates += 1
                else:
                    print(f"EN existing: {english_short}")

                if not english_short:
                    print("SKIP translations: no English short_detail available.")
                    if save and row_updates > 0:
                        session.commit()
                        print(f"✅ Saved ID {row.id}")
                    continue

                for lang in langs:
                    if lang == "en":
                        continue

                    existing_locale = session.execute(
                        text("""
                            SELECT id, short_detail_text
                            FROM track_locale
                            WHERE track_id = :track_id
                              AND language_code = :lang
                            LIMIT 1
                        """),
                        {"track_id": row.id, "lang": lang},
                    ).first()

                    if not existing_locale:
                        print(f"{lang}: SKIP no track_locale row")
                        continue

                    existing_text = (existing_locale.short_detail_text or "").strip()
                    if existing_text and not overwrite:
                        print(f"{lang} existing: {existing_text}")
                        continue

                    translated = translate_short_detail(english_short, lang)
                    print(f"{lang}: {translated}")

                    if save:
                        session.execute(
                            text("""
                                UPDATE track_locale
                                SET short_detail_text = :short_detail_text
                                WHERE id = :locale_id
                            """),
                            {
                                "short_detail_text": translated,
                                "locale_id": existing_locale.id,
                            },
                        )
                        updated += 1
                        row_updates += 1

                if save and row_updates > 0:
                    session.commit()
                    print(f"✅ Saved ID {row.id} ({row_updates} field(s))")
                elif save:
                    print(f"ℹ️ No updates needed for ID {row.id}")

            except Exception as exc:
                errors += 1
                if save:
                    session.rollback()
                print(f"ERROR on ID {row.id}: {exc}")
                continue

        print("\nDone.")
        print(f"Rows processed: {processed}")
        print(f"Fields updated: {updated}")
        print(f"Errors: {errors}")
        print(f"Save mode: {save}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--langs", nargs="+", default=["en"], choices=LANGS)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--track-id", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    main(
        limit=args.limit,
        track_id=args.track_id,
        overwrite=args.overwrite,
        save=args.save,
        langs=args.langs,
    )