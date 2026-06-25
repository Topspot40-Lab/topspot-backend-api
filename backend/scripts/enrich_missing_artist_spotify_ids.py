from __future__ import annotations

import argparse

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.database import engine
from backend.services.spotify.spotify_lookup import get_spotify_artist_candidates
from backend.services.spotify.spotify_lookup import get_artist_artwork, sp


def get_artists(artist_ids: list[int] | None, missing_only: bool, limit: int) -> list[dict]:
    if artist_ids:
        sql = text("""
            select
                id as artist_id,
                artist_name,
                spotify_artist_id,
                artist_artwork
            from artist
            where id = any(:artist_ids)
            order by id
        """)
        params = {"artist_ids": artist_ids}
    else:
        where_clause = "where spotify_artist_id is null" if missing_only else ""
        sql = text(f"""
            select
                id as artist_id,
                artist_name,
                spotify_artist_id,
                artist_artwork
            from artist
            {where_clause}
            order by id
            limit :limit
        """)
        params = {"limit": limit}

    with engine.begin() as conn:
        return conn.execute(sql, params).mappings().all()


def find_spotify_artist(artist_name: str, interactive: bool) -> dict | None:
    candidates = get_spotify_artist_candidates(artist_name, limit=5)

    if not candidates:
        return None

    if not interactive:
        for candidate in candidates:
            if candidate["artist_name"].strip().lower() == artist_name.strip().lower():
                return candidate
        return candidates[0]

    print()
    print("Candidates:")
    for i, candidate in enumerate(candidates, start=1):
        print(
            f"  {i}. {candidate['artist_name']} "
            f"({candidate['spotify_artist_id']}) "
            f"followers={candidate.get('followers')} "
            f"genres={', '.join(candidate.get('genres', [])[:5])}"
        )

    choice = input("Choose 1-5, or s to skip: ").strip().lower()

    if choice == "s":
        return None

    if choice in {"1", "2", "3", "4", "5"}:
        index = int(choice) - 1
        if index < len(candidates):
            return candidates[index]

    print("Invalid choice. Skipping.")
    return None


def update_artist(artist_id: int, spotify_artist: dict) -> None:
    sql = text("""
        update artist
        set spotify_artist_id = :spotify_artist_id,
            artist_artwork = :artist_artwork
        where id = :artist_id
    """)

    with engine.begin() as conn:
        conn.execute(sql, {
            "artist_id": artist_id,
            "spotify_artist_id": spotify_artist["spotify_artist_id"],
            "artist_artwork": spotify_artist["artist_artwork"],
        })

def get_artist_id_from_existing_track(artist_id: int) -> dict | None:
    sql = text("""
        select
            t.track_name,
            t.spotify_track_id
        from track t
        where t.artist_id = :artist_id
          and t.spotify_track_id is not null
        order by t.id
        limit 1
    """)

    with engine.begin() as conn:
        row = conn.execute(sql, {"artist_id": artist_id}).mappings().first()

    if not row:
        return None

    track_data = sp.track(row["spotify_track_id"])
    artists = track_data.get("artists", [])

    if not artists:
        return None

    spotify_artist = artists[0]
    spotify_artist_id = spotify_artist["id"]

    return {
        "spotify_artist_id": spotify_artist_id,
        "artist_name": spotify_artist["name"],
        "artist_artwork": get_artist_artwork(spotify_artist_id),
        "genres": [],
        "followers": None,
        "source": f"track:{row['track_name']}",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artist-ids", nargs="+", type=int)
    parser.add_argument("--missing-only", action="store_true")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()

    artists = get_artists(args.artist_ids, args.missing_only, args.limit)

    print(f"Found: {len(artists)} artist(s)")
    print(f"Save mode: {args.save}")
    print()

    matched = 0
    missed = 0
    saved = 0

    for row in artists:
        artist_id = row["artist_id"]
        artist_name = row["artist_name"]
        current_spotify_id = row["spotify_artist_id"]

        print("=" * 80)
        print(f"Artist ID: {artist_id}")
        print(f"Artist:    {artist_name}")
        print(f"Current:   {current_spotify_id}")

        if current_spotify_id and args.missing_only:
            print("Already has Spotify Artist ID. Skipping.")
            continue

        spotify_artist = get_artist_id_from_existing_track(artist_id)

        if spotify_artist:
            print(f"✅ Derived from existing track: {spotify_artist.get('source')}")
        else:
            spotify_artist = find_spotify_artist(artist_name, args.interactive)

        if not spotify_artist:
            print("❌ No Spotify artist match")
            missed += 1
            continue

        matched += 1

        print(f"✅ Match:   {spotify_artist.get('artist_name')}")
        print(f"Source:    {spotify_artist.get('source', 'artist search')}")
        print(f"ArtistID:  {spotify_artist.get('spotify_artist_id')}")
        print(f"Followers: {spotify_artist.get('followers')}")
        print(f"Genres:    {', '.join(spotify_artist.get('genres', []))}")

        if not args.save:
            print("DRY RUN — not saved")
            continue

        try:
            update_artist(artist_id, spotify_artist)
            saved += 1
            print("💾 Saved")
        except IntegrityError as exc:
            print(f"⚠️ Save failed, likely duplicate Spotify Artist ID: {exc}")

    print()
    print("Done.")
    print(f"Matched: {matched}")
    print(f"Missed:  {missed}")
    print(f"Saved:   {saved}")


if __name__ == "__main__":
    main()