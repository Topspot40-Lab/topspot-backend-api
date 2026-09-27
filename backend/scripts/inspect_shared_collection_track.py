"""Read-only report on the shared recording miscredited to Muddy Waters.

    python -m backend.scripts.inspect_shared_collection_track \
        --output shared-track-2315.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text


def select_rows(conn, statement, params):
    return [dict(r) for r in conn.execute(text(statement), params).mappings()]


def inspect(conn):
    tid = 2315
    track = select_rows(conn, """
        SELECT t.id, t.track_name, t.spotify_track_id, t.artist_display_name,
               t.artist_id, a.artist_name, t.detail, t.short_detail, t.short_detail_tts_key
          FROM track t JOIN artist a ON a.id=t.artist_id WHERE t.id=:tid
    """, {"tid": tid})
    if len(track) != 1 or track[0]["spotify_track_id"] != "2nvcTDmZkRWKNMAL29sLHo":
        raise ValueError("Shared track no longer matches the inspected recording")
    collection = select_rows(conn, """
        SELECT ctr.id, c.name AS collection, c.slug, ctr.ranking, ctr.intro
          FROM collection_track_ranking ctr JOIN collection c ON c.id=ctr.collection_id
         WHERE ctr.track_id=:tid ORDER BY c.name
    """, {"tid": tid})
    nostalgia = select_rows(conn, """
        SELECT tr.id, tr.ranking, tr.intro, d.decade_name, d.slug AS decade_slug,
               g.genre_name, g.slug AS genre_slug
          FROM track_ranking tr
          JOIN decade_genre dg ON dg.id=tr.decade_genre_id
          JOIN decade d ON d.id=dg.decade_id
          JOIN genre g ON g.id=dg.genre_id
         WHERE tr.track_id=:tid ORDER BY d.decade_name, g.genre_name
    """, {"tid": tid})
    collection_locales = select_rows(conn, """
        SELECT ctr.id AS ranking_id, l.lang, l.intro_text, l.tts_key
          FROM collection_track_ranking ctr
          JOIN collection_track_ranking_locale l ON l.collection_track_ranking_id=ctr.id
         WHERE ctr.track_id=:tid ORDER BY ctr.id, l.lang
    """, {"tid": tid})
    nostalgia_locales = select_rows(conn, """
        SELECT tr.id AS ranking_id, l.language_code, l.intro_text, l.tts_bucket, l.tts_key
          FROM track_ranking tr JOIN track_ranking_locale l ON l.track_ranking_id=tr.id
         WHERE tr.track_id=:tid ORDER BY tr.id, l.language_code
    """, {"tid": tid})
    track_locales = select_rows(conn, """
        SELECT language_code, detail_text, short_detail_text, tts_bucket, tts_key,
               short_detail_tts_key FROM track_locale WHERE track_id=:tid ORDER BY language_code
    """, {"tid": tid})
    band = select_rows(conn, "SELECT id, artist_name, spotify_artist_id FROM artist WHERE id=2899", {})
    return {"track": track[0], "the_band_artist": band,
            "collections": collection, "collection_locales": collection_locales,
            "nostalgia": nostalgia, "nostalgia_locales": nostalgia_locales,
            "track_locales": track_locales}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    from backend.database import engine
    with engine.connect() as conn:
        report = inspect(conn)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Shared track used by {len(report['collections'])} Collections and {len(report['nostalgia'])} Nostalgia rankings")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
