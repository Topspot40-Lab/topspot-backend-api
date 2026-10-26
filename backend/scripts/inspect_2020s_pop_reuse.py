"""Read-only inventory of existing track details and artist bios for Pop additions.

    python -m backend.scripts.inspect_2020s_pop_reuse --output 2020s-pop-reuse.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text


SELECTED = (
    (6, "4Dvkj6JhhA12EX05fT7y2e", "6KImCVD70vtIoJWnq6nGn3"),
    (7, "0V3wPSX9ygBnCm8psDIegu", "06HL4z0CvFAxyc27GXpf02"),
    (8, "7DSAEUvxU8FajXtRloy8M0", "5YGY8feqx7naU7z4HrwZM6"),
    (9, "3OHfY25tqY28d16oZczHc8", "7tYKF4w9nC0nq9CsPZTHyP"),
    (10, "2oADPwknKEfMtwpMnr7xfg", "74KM79TiuVKeVCqs8QtB0B"),
    (11, "6dOtVTDdiauQNBQEDOtlAB", "6qqNVTkY8uBg9cP3Jd7DAH"),
    (12, "5vNRhkKd0yEAg8suGBpjeY", "3eVa5w3URK5duf6eyVDbu9"),
    (28, "1k2pQc5i348DCHwbn5KTdc", "7GlBOeep6PqTfFi59PTUUN"),
    (44, "6qqrTXSdwiJaq8SO0X2lSe", "0fTSzq9jAh4c36UVb4V7CB"),
    (45, "12bYYQaLqHliSXvRIYlq8G", "0du5cEVh5yTK9QJze8zA0C"),
)


def inventory(connection):
    result=[]
    for rank, spotify_track_id, spotify_artist_id in SELECTED:
        track_rows=[dict(r) for r in connection.execute(text("""
            SELECT id, track_name, artist_id, artist_display_name, spotify_track_id,
                   mode_flag::text AS mode_flag, year_released, duration_ms,
                   album_name, album_artwork, detail, short_detail
              FROM track WHERE spotify_track_id=:id
        """), {"id":spotify_track_id}).mappings().all()]
        for track in track_rows:
            track["locales"]=[dict(r) for r in connection.execute(text("""
                SELECT language_code, detail_text, tts_bucket, tts_key
                  FROM track_locale WHERE track_id=:id ORDER BY language_code
            """), {"id":track["id"]}).mappings().all()]
            track["rankings"]=[dict(r) for r in connection.execute(text("""
                SELECT dg.slug AS program_slug, tr.ranking FROM track_ranking tr
                 JOIN decade_genre dg ON dg.id=tr.decade_genre_id
                 WHERE tr.track_id=:id ORDER BY dg.slug,tr.ranking
            """), {"id":track["id"]}).mappings().all()]
        artist_rows=[dict(r) for r in connection.execute(text("""
            SELECT id, artist_name, spotify_artist_id, artist_artwork,
                   artist_description FROM artist WHERE spotify_artist_id=:id
        """), {"id":spotify_artist_id}).mappings().all()]
        for artist in artist_rows:
            artist["locales"]=[dict(r) for r in connection.execute(text("""
                SELECT language_code, artist_description_text, tts_bucket, tts_key
                  FROM artist_locale WHERE artist_id=:id ORDER BY language_code
            """), {"id":artist["id"]}).mappings().all()]
        result.append({"rank":rank,"spotify_track_id":spotify_track_id,
                       "spotify_artist_id":spotify_artist_id,
                       "database_tracks":track_rows,"database_artists":artist_rows})
        print(f"#{rank}: {len(track_rows)} matching track rows; {len(artist_rows)} matching artist rows",flush=True)
    return {"selected":result}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    from backend.database import engine
    with engine.connect() as connection:
        report=inventory(connection)
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str)+"\n",encoding="utf-8")
    print(f"Saved {args.output}")


if __name__=="__main__":
    main()
