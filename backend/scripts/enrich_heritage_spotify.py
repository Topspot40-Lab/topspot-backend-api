from sqlalchemy import text
from backend.database import engine
from backend.services.spotify.spotify_lookup import get_spotify_track_data
from sqlalchemy.exc import IntegrityError

HERITAGE_SLUGS = (
    "mexican_american_favorites",
    "traditional_mexican_favorites",
    "great_american_songbook",
    "crooner_classics",
    "traditional_hymns",
    "southern_gospel_favorites",
    "bluegrass_favorites",
    "patriotic_favorites",
    "railroad_train_songs",
    "cowboy_songs_western_favorites",
    "american_folk_heroes",
    "western_heritage_favorites",
    "civil_war_songs",
    "celtic_favorites",
    "italian_favorites",
    "german_heritage_favorites",
    "brazilian_classics",
    "african_american_heritage_favorites",
)


def get_missing_heritage_tracks(limit: int = 10) -> list[dict]:
    sql = text("""
        SELECT DISTINCT
            t.id AS track_id,
            t.track_name,
            a.id AS artist_id,
            a.artist_name
        FROM collection_track_ranking ctr
        JOIN collection c
            ON c.id = ctr.collection_id
        JOIN track t
            ON t.id = ctr.track_id
        JOIN artist a
            ON a.id = t.artist_id
        WHERE c.slug = ANY(:slugs)
          AND t.spotify_track_id IS NULL
        ORDER BY t.id
        LIMIT :limit
    """)

    with engine.begin() as conn:
        return conn.execute(
            sql,
            {
                "slugs": list(HERITAGE_SLUGS),
                "limit": limit,
            },
        ).mappings().all()


def update_track_spotify_data(track_id: int, artist_id: int, data: dict) -> None:
    sql = text("""
        UPDATE track
        SET spotify_track_id = :spotify_track_id,
            album_name = :album_name,
            album_artwork = :album_artwork,
            year_released = :year_released,
            duration_ms = :duration_ms,
            popularity = :popularity
        WHERE id = :track_id
    """)

    artist_sql = text("""
        UPDATE artist
        SET spotify_artist_id = :spotify_artist_id,
            artist_artwork = :artist_artwork
        WHERE id = :artist_id
    """)

    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "track_id": track_id,
                "spotify_track_id": data["spotify_track_id"],
                "album_name": data["album_name"],
                "album_artwork": data["album_artwork"],
                "year_released": data["year_released"],
                "duration_ms": data["duration_ms"],
                "popularity": data["popularity"],
            },
        )

        conn.execute(
            artist_sql,
            {
                "artist_id": artist_id,
                "spotify_artist_id": data["spotify_artist_id"],
                "artist_artwork": data["artist_artwork"],
            },
        )


def main() -> None:
    tracks = get_missing_heritage_tracks(limit=250)

    matched = 0
    missed = 0

    for track in tracks:
        track_id = track["track_id"]
        artist_id = track["artist_id"]
        track_name = track["track_name"]
        artist_name = track["artist_name"]

        print(f"🔎 Searching: {track_name} — {artist_name}")

        spotify_data = get_spotify_track_data(track_name, artist_name)

        if spotify_data is None:
            print(f"❌ No match: {track_name} — {artist_name}")
            missed += 1
            continue

        try:
            update_track_spotify_data(track_id, artist_id, spotify_data)

            print(
                f"✅ Updated: {track_name} — {artist_name} "
                f"({spotify_data['spotify_track_id']})"
            )

            matched += 1

        except IntegrityError:
            print(
                f"⚠️ Duplicate Spotify ID already exists, skipped: "
                f"{track_name} — {artist_name} "
                f"({spotify_data['spotify_track_id']})"
            )
            missed += 1

    print()
    print(f"Matched: {matched}")
    print(f"Missed: {missed}")


if __name__ == "__main__":
    main()
