from __future__ import annotations

import argparse
import csv
from pathlib import Path

from sqlalchemy import text

from backend.database import engine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Curation CSV file path")
    parser.add_argument("--save", action="store_true", help="Actually update database")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    csv_path = Path(args.csv)

    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    print(f"CSV:       {csv_path}")
    print(f"Save mode: {args.save}")
    print()

    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    with engine.begin() as conn:
        for row in rows:
            action = (row.get("action") or "").strip().upper()
            ranking_id = int(row["collection_track_ranking_id"])
            replacement_track_id = (row.get("replacement_track_id") or "").strip()
            note = row.get("note") or ""

            current = conn.execute(
                text("""
                    select
                        ctr.id,
                        ctr.collection_id,
                        c.name as collection_name,
                        ctr.ranking,
                        ctr.track_id,
                        t.track_name,
                        a.artist_name
                    from collection_track_ranking ctr
                    join collection c on c.id = ctr.collection_id
                    join track t on t.id = ctr.track_id
                    join artist a on a.id = t.artist_id
                    where ctr.id = :ranking_id
                """),
                {"ranking_id": ranking_id},
            ).mappings().first()

            if not current:
                print(f"❌ Ranking not found: {ranking_id}")
                continue

            print("=" * 80)
            print(f"Action:     {action}")
            print(f"Ranking ID: {ranking_id}")
            print(f"Collection: {current['collection_name']}")
            print(f"Rank:       {current['ranking']}")
            print(f"Current:    {current['track_id']} | {current['track_name']} — {current['artist_name']}")
            print(f"Note:       {note}")

            if action == "RETIRE":
                if args.save:
                    conn.execute(
                        text("""
                            update collection_track_ranking
                            set ranking = 900 + ranking,
                                updated_at = now()
                            where id = :ranking_id
                              and ranking < 900
                        """),
                        {"ranking_id": ranking_id},
                    )

                    conn.execute(
                        text("""
                            update collection_track_ranking_locale
                            set intro_text = '[RETIRED - regenerate if restored]',
                                tts_key = null
                            where collection_track_ranking_id = :ranking_id
                        """),
                        {"ranking_id": ranking_id},
                    )

                print("✅ Would retire ranking row and clear locale intro assets" if not args.save else "💾 Retired")

            elif action == "REPLACE":
                if not replacement_track_id:
                    print("❌ Missing replacement_track_id for REPLACE")
                    continue

                replacement = conn.execute(
                    text("""
                        select
                            t.id as track_id,
                            t.track_name,
                            a.artist_name,
                            t.spotify_track_id
                        from track t
                        join artist a on a.id = t.artist_id
                        where t.id = :track_id
                    """),
                    {"track_id": int(replacement_track_id)},
                ).mappings().first()

                if not replacement:
                    print(f"❌ Replacement track not found: {replacement_track_id}")
                    continue

                print(
                    f"Replacement:{replacement['track_id']} | "
                    f"{replacement['track_name']} — {replacement['artist_name']} | "
                    f"{replacement['spotify_track_id']}"
                )

                if not replacement["spotify_track_id"]:
                    print("⚠️ Replacement has no Spotify ID. Skipping.")
                    continue

                if args.save:
                    conn.execute(
                        text("""
                            update collection_track_ranking
                            set track_id = :replacement_track_id,
                                updated_at = now()
                            where id = :ranking_id
                        """),
                        {
                            "replacement_track_id": int(replacement_track_id),
                            "ranking_id": ranking_id,
                        },
                    )

                    conn.execute(
                        text("""
                            update collection_track_ranking_locale
                            set intro_text = '[REPLACED - regenerate]',
                                tts_key = null
                            where collection_track_ranking_id = :ranking_id
                        """),
                        {"ranking_id": ranking_id},
                    )

                print("✅ Would replace and clear locale intro assets" if not args.save else "💾 Replaced")

            else:
                print(f"❌ Unknown action: {action}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()