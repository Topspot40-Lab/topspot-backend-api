from __future__ import annotations

import argparse
import csv
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    args = parser.parse_args()

    path = Path(args.csv)

    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    artist_found = 0
    track_found = 0

    print("=" * 80)
    print(f"Validating collection CSV: {path}")
    print(f"Rows: {len(rows)}")
    print("=" * 80)

    with Session(engine) as session:
        for i, row in enumerate(rows, start=1):
            artist_name = row["artist_name"].strip()
            track_name = row["track_name"].strip()

            artist = session.exec(
                text("""
                    SELECT id, artist_name
                    FROM artist
                    WHERE lower(artist_name) = lower(:artist_name)
                    LIMIT 1
                """).bindparams(artist_name=artist_name)
            ).first()

            track = session.exec(
                text("""
                    SELECT t.id, t.track_name, a.artist_name
                    FROM track t
                    JOIN artist a ON a.id = t.artist_id
                    WHERE lower(t.track_name) = lower(:track_name)
                      AND lower(a.artist_name) = lower(:artist_name)
                    LIMIT 1
                """).bindparams(
                    track_name=track_name,
                    artist_name=artist_name,
                )
            ).first()

            if artist:
                artist_found += 1

            if track:
                track_found += 1

            print(f"{i:02d}. {artist_name} - {track_name}")
            print(f"    Artist: {'FOUND ' + str(artist[0]) if artist else 'MISSING'}")
            print(f"    Track : {'FOUND ' + str(track[0]) if track else 'MISSING'}")

    print("=" * 80)
    print(f"Artists found: {artist_found}/{len(rows)}")
    print(f"Tracks found:  {track_found}/{len(rows)}")
    print(f"Tracks missing:{len(rows) - track_found}/{len(rows)}")
    print("=" * 80)


if __name__ == "__main__":
    main()
