"""Read-only snapshot of the 2020s Pop program before filling its ten vacancies.

    python -m backend.scripts.inspect_2020s_pop_gaps --output 2020s-pop-audit.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text


def inspect(connection):
    programs = connection.execute(text("""
        SELECT dg.id, d.slug AS decade, g.slug AS genre
          FROM decade_genre dg JOIN decade d ON d.id=dg.decade_id
          JOIN genre g ON g.id=dg.genre_id
         WHERE d.slug='2020s' AND g.slug='pop'
    """)).mappings().all()
    if len(programs) != 1:
        raise ValueError(f"Expected one 2020s Pop program, got {len(programs)}")
    program = dict(programs[0])
    rows = connection.execute(text("""
        SELECT tr.id AS ranking_id, tr.ranking, tr.track_id, tr.tracklist_id,
               tr.intro AS en_intro, t.track_name, t.artist_display_name,
               t.spotify_track_id, t.year_released, t.duration_ms,
               t.album_name, t.artist_id, a.artist_name, a.spotify_artist_id,
               t.detail IS NOT NULL AS has_detail
          FROM track_ranking tr JOIN track t ON t.id=tr.track_id
          JOIN artist a ON a.id=t.artist_id
         WHERE tr.decade_genre_id=:id ORDER BY tr.ranking
    """), {"id": program["id"]}).mappings().all()
    rankings = [dict(r) for r in rows]
    for row in rankings:
        row["locales"] = [dict(loc) for loc in connection.execute(text("""
            SELECT language_code, intro_text, tts_bucket, tts_key
              FROM track_ranking_locale WHERE track_ranking_id=:id
             ORDER BY language_code
        """), {"id": row["ranking_id"]}).mappings().all()]
    ranks = [r["ranking"] for r in rankings]
    if len(ranks) != len(set(ranks)):
        raise ValueError("Duplicate rank in 2020s Pop")
    missing = [r for r in range(1, 46) if r not in ranks]
    return {"program": program, "count": len(rankings), "target": 45,
            "missing_ranks": missing, "rankings": rankings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from backend.database import engine
    with engine.connect() as connection:
        report = inspect(connection)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(f"2020s Pop: {report['count']} songs; missing through #45: {report['missing_ranks']}")
    for row in report["rankings"]:
        print(f"  #{row['ranking']}: {row['track_name']} — {row['artist_name']} ({row['year_released']})")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
