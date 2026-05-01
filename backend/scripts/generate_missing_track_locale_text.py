from __future__ import annotations

import argparse
import os

from openai import OpenAI
from sqlalchemy import text
from sqlmodel import Session, col, select

from backend.database import engine
from backend.models.dbmodels import Track, TrackLocale


def clean_text(value: str) -> str:
    return (
        value.replace("Ã¢â‚¬â€œ", "–")
        .replace("Ã¢â‚¬â€", "–")
        .replace("Ã¢â‚¬â„¢", "'")
        .replace("â€™", "'")
        .replace("â€œ", '"')
        .replace("â€", '"')
        .strip()
    )


def target_language_name(lang: str) -> str:
    if lang == "es":
        return "Mexican Spanish"
    if lang == "pt-BR":
        return "Brazilian Portuguese"
    raise ValueError(f"Unsupported language: {lang}")


def translate_detail(source_text: str, lang: str) -> str:
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY environment variable is not set.")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1",
    )

    target = target_language_name(lang)
    cleaned = clean_text(source_text)

    prompt = f"""
    Rewrite the following music narration in natural {target}.

    RULES:
    - Do NOT mix languages (no Spanish in the narration)
    - Keep song titles as-is (e.g., "Love Yourself", "Ella y Yo")
    - Use a warm, polished Brazilian radio host tone. Conversational, but not slangy. Avoid phrases like "Ei, galera", "bombou", or internet-style hype.
    - Prefer natural phrasing (e.g., "a música fala sobre", "passa a sensação de")
    - Avoid formal or academic wording
    - Keep it 3–5 sentences
    - Preserve meaning; do NOT add new facts

    TEXT:
    {cleaned}
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
        temperature=0.4,
    )

    result = response.choices[0].message.content
    if not result:
        raise RuntimeError("XAI returned an empty translation.")

    return result.strip()


def get_worklist_track_ids(session: Session) -> list[int]:
    rows = session.exec(
        text("""
            SELECT track_id
            FROM missing_track_locale_worklist
            ORDER BY track_id
        """)
    ).all()

    return [int(row[0]) for row in rows if row[0] is not None]


def main(lang: str, limit: int | None, track_id: int | None, overwrite: bool) -> None:
    with Session(engine) as session:
        track_ids = get_worklist_track_ids(session)

        if not track_ids:
            print("No worklist track IDs found.")
            return

        stmt = select(Track).where(col(Track.id).in_(track_ids))

        if track_id is not None:
            stmt = stmt.where(Track.id == track_id)

        tracks = session.exec(stmt).all()

        inserted_or_updated = 0
        skipped = 0
        errors = 0

        for track in tracks:
            if limit is not None and inserted_or_updated >= limit:
                break

            existing = session.exec(
                select(TrackLocale).where(
                    TrackLocale.track_id == track.id,
                    TrackLocale.language_code == lang,
                )
            ).first()

            if existing and not overwrite:
                skipped += 1
                continue

            source_detail = (track.detail or "").strip()
            if not source_detail:
                skipped += 1
                print(f"Skipped no detail: {track.id} - {track.track_name}")
                continue

            try:
                detail_text = translate_detail(source_detail, lang)
            except Exception as exc:
                errors += 1
                print(f"ERROR translating {track.id} - {track.track_name}: {exc}")
                continue

            if existing:
                existing.detail_text = detail_text
                existing.tts_bucket = None
                existing.tts_key = None
                session.add(existing)
                action = "Updated"
            else:
                session.add(
                    TrackLocale(
                        track_id=track.id,
                        language_code=lang,
                        detail_text=detail_text,
                    )
                )
                action = "Inserted"

            inserted_or_updated += 1
            print(f"{action} {lang}: {track.id} - {track.track_name}")

        session.commit()

        print("\nDone.")
        print(f"Inserted/updated: {inserted_or_updated}")
        print(f"Skipped: {skipped}")
        print(f"Errors: {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True, choices=["es", "pt-BR"])
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--track-id", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    main(
        lang=args.lang,
        limit=args.limit,
        track_id=args.track_id,
        overwrite=args.overwrite,
    )