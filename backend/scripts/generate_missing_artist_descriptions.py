from __future__ import annotations

import argparse
import re

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine
from backend.services.xai_client import ask_xai


def clean_text(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\*\*", "", value)
    value = re.sub(r"\bWord count:\s*\d+\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\(\d+\s+words?\)", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value.strip(' "\n\t')


def generate_description(artist_name: str) -> str:
    prompt = f"""
Write a concise TopSpot artist description for {artist_name}.

Rules:
- 2 sentences only
- 35 to 70 words total
- Warm, informative, and suitable for spoken narration
- Mention musical style, significance, legacy, or why listeners remember them
- Do not say "this artist" or "this performer"
- Do not use markdown
"""

    text = ask_xai(
        "You are a concise music historian writing spoken TopSpot artist descriptions.",
        prompt,
    )
    return clean_text(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--min-tracks", type=int, default=2)
    parser.add_argument("--artist-ids", default=None)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    artist_ids = None
    if args.artist_ids:
        artist_ids = [int(x.strip()) for x in args.artist_ids.split(",") if x.strip()]

    if artist_ids:
        sql = text("""
            SELECT
                a.id,
                a.artist_name,
                COUNT(DISTINCT t.id) AS track_count,
                COUNT(DISTINCT ctr.collection_id) AS collection_count
            FROM artist a
            LEFT JOIN track t
                ON t.artist_id = a.id
            LEFT JOIN collection_track_ranking ctr
                ON ctr.track_id = t.id
            WHERE a.artist_description IS NULL
              AND a.id = ANY(:artist_ids)
            GROUP BY a.id, a.artist_name
            ORDER BY a.id
        """)
    else:
        sql = text("""
            SELECT
                a.id,
                a.artist_name,
                COUNT(DISTINCT t.id) AS track_count,
                COUNT(DISTINCT ctr.collection_id) AS collection_count
            FROM artist a
            JOIN track t
                ON t.artist_id = a.id
            LEFT JOIN collection_track_ranking ctr
                ON ctr.track_id = t.id
            WHERE a.artist_description IS NULL
            GROUP BY a.id, a.artist_name
            HAVING COUNT(DISTINCT t.id) >= :min_tracks
            ORDER BY
                COUNT(DISTINCT ctr.collection_id) DESC,
                COUNT(DISTINCT t.id) DESC,
                a.artist_name
            LIMIT :limit
        """)

    print("=" * 80)
    print("Generate Missing Artist Descriptions")
    print(f"Limit:      {args.limit}")
    print(f"Min tracks: {args.min_tracks}")
    print(f"Artist IDs: {artist_ids}")
    print(f"Save:       {args.save}")
    print("=" * 80)

    updated = 0

    with Session(engine) as session:
        if artist_ids:
            rows = session.exec(sql.bindparams(artist_ids=artist_ids)).mappings().all()
        else:
            rows = session.exec(
                sql.bindparams(
                    limit=args.limit,
                    min_tracks=args.min_tracks,
                )
            ).mappings().all()

        for row in rows:
            artist_id = row["id"]
            artist_name = row["artist_name"]

            print("-" * 80)
            print(f"{artist_id} | {artist_name}")
            print(f"Tracks: {row['track_count']} | Collections: {row['collection_count']}")

            try:
                description = generate_description(artist_name)
                print(description)

                if args.save:
                    session.exec(
                        text("""
                            UPDATE artist
                            SET artist_description = :description
                            WHERE id = :artist_id
                        """).bindparams(
                            description=description,
                            artist_id=artist_id,
                        )
                    )
                    session.commit()
                    updated += 1

            except Exception as exc:
                print(f"ERROR: {exc}")

    print("=" * 80)
    print(f"Updated: {updated}")
    print("=" * 80)


if __name__ == "__main__":
    main()