from __future__ import annotations

import argparse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.database import engine
from backend.services.spotify.spotify_lookup import get_spotify_track_data


def get_tracks(track_ids: list[int] | None, missing_only: bool, limit: int) -> list[dict]:
    if track_ids:
        sql = text("""
            select
                t.id as track_id,
                t.track_name,
                a.id as artist_id,
                a.artist_name,
                t.spotify_track_id
            from track t
            join artist a on a.id = t.artist_id
            where t.id = any(:track_ids)
            order by t.id
        """)
        params = {"track_ids": track_ids}
    else:
        where_clause = "where t.spotify_track_id is null" if missing_only else ""
        sql = text(f"""
            select
                t.id as track_id,
                t.track_name,
                a.id as artist_id,
                a.artist_name,
                t.spotify_track_id
            from track t
            join artist a on a.id = t.artist_id
            {where_clause}
            order by t.id
            limit :limit
        """)
        params = {"limit": limit}

    with engine.begin() as conn:
        return conn.execute(sql, params).mappings().all()


def update_track(track_id: int, artist_id: int, data: dict) -> None:
    sql = text("""
        update track
        set spotify_track_id = :spotify_track_id,
            album_name = :album_name,
            album_artwork = :album_artwork,
            year_released = :year_released,
            duration_ms = :duration_ms,
            popularity = :popularity
        where id = :track_id
    """)

    artist_sql = text("""
        update artist
        set spotify_artist_id = coalesce(spotify_artist_id, :spotify_artist_id),
            artist_artwork = coalesce(artist_artwork, :artist_artwork)
        where id = :artist_id
    """)

    with engine.begin() as conn:
        conn.execute(sql, {
            "track_id": track_id,
            "spotify_track_id": data["spotify_track_id"],
            "album_name": data["album_name"],
            "album_artwork": data["album_artwork"],
            "year_released": data["year_released"],
            "duration_ms": data["duration_ms"],
            "popularity": data["popularity"],
        })

        conn.execute(artist_sql, {
            "artist_id": artist_id,
            "spotify_artist_id": data["spotify_artist_id"],
            "artist_artwork": data["artist_artwork"],
        })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--track-ids", nargs="+", type=int)
    parser.add_argument("--missing-only", action="store_true")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    tracks = get_tracks(args.track_ids, args.missing_only, args.limit)

    print(f"Found: {len(tracks)} track(s)")
    print(f"Save mode: {args.save}")
    print()

    matched = 0
    missed = 0
    saved = 0

    for track in tracks:
        track_id = track["track_id"]
        artist_id = track["artist_id"]
        track_name = track["track_name"]
        artist_name = track["artist_name"]
        current_spotify_id = track["spotify_track_id"]

        print("=" * 80)
        print(f"Track ID: {track_id}")
        print(f"Track:    {track_name}")
        print(f"Artist:   {artist_name}")
        print(f"Current:  {current_spotify_id}")

        if current_spotify_id and not args.missing_only:
            print("Already has Spotify ID. Skipping.")
            continue

        data = get_spotify_track_data(track_name, artist_name)

        if not data:
            print("❌ No Spotify match")
            missed += 1
            continue

        matched += 1

        print(f"✅ Match:   {data['spotify_track_id']}")
        print(f"Album:    {data.get('album_name')}")
        print(f"Year:     {data.get('year_released')}")
        print(f"ArtistID: {data.get('spotify_artist_id')}")

        if not args.save:
            print("DRY RUN — not saved")
            continue

        try:
            update_track(track_id, artist_id, data)
            saved += 1
            print("💾 Saved")
        except IntegrityError as exc:
            print(f"⚠️ Save failed, likely duplicate Spotify ID: {exc}")

    print()
    print("Done.")
    print(f"Matched: {matched}")
    print(f"Missed:  {missed}")
    print(f"Saved:   {saved}")


if __name__ == "__main__":
    main()