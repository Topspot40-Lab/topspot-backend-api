from __future__ import annotations

import argparse
from sqlalchemy import text
from backend.database import engine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    sql = text("""
        select
            c.name as collection_name,
            c.slug,
            count(*) filter (where ctr.ranking <= 45) as active_tracks,
            count(*) filter (where ctr.ranking between 900 and 1000) as retired_tracks,
            count(*) filter (where ctr.ranking <= 45 and t.spotify_track_id is not null) as playable_tracks,
            count(*) filter (where ctr.ranking <= 45 and t.spotify_track_id is null) as missing_spotify_ids,
            count(*) filter (where ctr.ranking <= 45 and coalesce(t.detail, '') = '') as missing_detail_text,
            count(*) filter (where ctr.ranking <= 45 and coalesce(t.short_detail, '') = '') as missing_short_detail_text,
            count(*) filter (where ctr.ranking <= 45 and t.spotify_track_id is not null and coalesce(t.short_detail_tts_key, '') = '') as missing_short_detail_mp3
        from collection c
        join collection_track_ranking ctr on ctr.collection_id = c.id
        join track t on t.id = ctr.track_id
        where c.slug = :slug
        group by c.name, c.slug
    """)

    with engine.begin() as conn:
        row = conn.execute(sql, {"slug": args.slug}).mappings().first()

    if not row:
        raise SystemExit(f"Collection not found: {args.slug}")

    issues = (
        row["missing_spotify_ids"]
        + row["missing_detail_text"]
        + row["missing_short_detail_text"]
        + row["missing_short_detail_mp3"]
    )

    print("=" * 72)
    print("Collection Certification Report")
    print("=" * 72)
    print()
    print(f"Collection: {row['collection_name']}")
    print(f"Slug:       {row['slug']}")
    print()
    print(f"Active tracks:             {row['active_tracks']}")
    print(f"Retired tracks:            {row['retired_tracks']}")
    print(f"Playable tracks:           {row['playable_tracks']}")
    print()
    print(f"Missing Spotify IDs:       {row['missing_spotify_ids']}")
    print(f"Missing detail text:       {row['missing_detail_text']}")
    print(f"Missing short detail text: {row['missing_short_detail_text']}")
    print("Missing detail MP3:        not checked")
    print(f"Missing short detail MP3:  {row['missing_short_detail_mp3']}")
    print()

    if issues == 0:
        print("Status: ✅ CERTIFIED")
    else:
        print("Status: ⚠️ NEEDS REVIEW")


if __name__ == "__main__":
    main()