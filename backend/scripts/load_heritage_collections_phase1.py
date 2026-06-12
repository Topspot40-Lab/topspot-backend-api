from sqlalchemy import text
from backend.database import engine
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

CSV_COLLECTIONS = [
    {
        "category_slug": "world_heritage_favorites",
        "collection_slug": "mexican_american_favorites",
        "collection_name": "Mexican-American Favorites",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "mexican_american_favorites.csv",
    },
    {
        "category_slug": "world_heritage_favorites",
        "collection_slug": "traditional_mexican_favorites",
        "collection_name": "Traditional Mexican Favorites",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "traditional_mexican_favorites.csv",
    },
    {
        "category_slug": "traditional_favorites",
        "collection_slug": "great_american_songbook",
        "collection_name": "Great American Songbook",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "great_american_songbook.csv",
    },
    {
        "category_slug": "traditional_favorites",
        "collection_slug": "crooner_classics",
        "collection_name": "Crooner Classics",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "crooner_classics.csv",
    },
    {
        "category_slug": "traditional_favorites",
        "collection_slug": "traditional_hymns",
        "collection_name": "Traditional Hymns",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "traditional_hymns.csv",
    },
    {
        "category_slug": "traditional_favorites",
        "collection_slug": "southern_gospel_favorites",
        "collection_name": "Southern Gospel Favorites",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "southern_gospel_favorites.csv",
    },
    {
        "category_slug": "traditional_favorites",
        "collection_slug": "bluegrass_favorites",
        "collection_name": "Bluegrass Favorites",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "bluegrass_favorites.csv",
    },

    {
        "category_slug": "american_heritage_favorites",
        "collection_slug": "patriotic_favorites",
        "collection_name": "Patriotic Favorites",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "patriotic_favorites.csv",
    },
    {
        "category_slug": "american_heritage_favorites",
        "collection_slug": "railroad_train_songs",
        "collection_name": "Railroad & Train Songs",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "railroad_train_songs.csv",
    },
    {
        "category_slug": "traditional_favorites",
        "collection_slug": "cowboy_songs_western_favorites",
        "collection_name": "Cowboy Songs & Western Favorites",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "cowboy_songs_western_favorites.csv",
    },
    {
        "category_slug": "american_heritage_favorites",
        "collection_slug": "american_folk_heroes",
        "collection_name": "American Folk Heroes",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "american_folk_heroes.csv",
    },
    {
        "category_slug": "american_heritage_favorites",
        "collection_slug": "western_heritage_favorites",
        "collection_name": "Western Heritage Favorites",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "western_heritage_favorites.csv",
    },
    {
        "category_slug": "american_heritage_favorites",
        "collection_slug": "civil_war_songs",
        "collection_name": "Civil War Songs",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "civil_war_songs.csv",
    },
    {
        "category_slug": "world_heritage_favorites",
        "collection_slug": "celtic_favorites",
        "collection_name": "Celtic Favorites",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "celtic_favorites.csv",
    },
    {
        "category_slug": "world_heritage_favorites",
        "collection_slug": "italian_favorites",
        "collection_name": "Italian Favorites",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "italian_favorites.csv",
    },
    {
        "category_slug": "world_heritage_favorites",
        "collection_slug": "german_heritage_favorites",
        "collection_name": "German Heritage Favorites",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "german_heritage_favorites.csv",
    },
    {
        "category_slug": "world_heritage_favorites",
        "collection_slug": "brazilian_classics",
        "collection_name": "Brazilian Classics",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "brazilian_classics.csv",
    },
    {
        "category_slug": "world_heritage_favorites",
        "collection_slug": "african_american_heritage_favorites",
        "collection_name": "African-American Heritage Favorites",
        "csv_file": BASE_DIR / "backend" / "data" / "heritage_collections" / "african_american_heritage_favorites.csv",
    },
]


def load_tracks_from_csv(csv_file: Path) -> list[dict]:
    tracks = []

    with csv_file.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            tracks.append(
                {
                    "rank": int(row["ranking"]),
                    "title": row["title"].strip(),
                    "artist": row["artist"].strip(),
                }
            )

    return tracks


def seed_collection_category(conn, category_slug: str) -> int:
    result = conn.execute(
        text("""
            INSERT INTO collection_category (slug, name)
            VALUES (:slug, :name)
            ON CONFLICT (slug) DO UPDATE
            SET name = EXCLUDED.name
            RETURNING id
        """),
        {
            "slug": category_slug,
            "name": category_slug.replace("_", " ").title(),
        },
    )

    return result.scalar_one()


def seed_collection(conn, collection_slug: str, collection_name: str, category_id: int) -> int:
    result = conn.execute(
        text("""
            INSERT INTO collection (slug, name, category_id)
            VALUES (:slug, :name, :category_id)
            ON CONFLICT (slug) DO UPDATE
            SET name = EXCLUDED.name,
                category_id = EXCLUDED.category_id
            RETURNING id
        """),
        {
            "slug": collection_slug,
            "name": collection_name,
            "category_id": category_id,
        },
    )

    return result.scalar_one()


def get_or_create_artist(conn, artist_name: str) -> int:
    result = conn.execute(
        text("""
            INSERT INTO artist (artist_name)
            VALUES (:artist_name)
            ON CONFLICT (artist_name) DO UPDATE
            SET artist_name = EXCLUDED.artist_name
            RETURNING id
        """),
        {"artist_name": artist_name},
    )

    return result.scalar_one()


def get_or_create_track(conn, title: str, artist_id: int) -> int:
    existing = conn.execute(
        text("""
            SELECT id
            FROM track
            WHERE track_name = :track_name
              AND artist_id = :artist_id
            LIMIT 1
        """),
        {
            "track_name": title,
            "artist_id": artist_id,
        },
    ).scalar_one_or_none()

    if existing is not None:
        return existing

    result = conn.execute(
        text("""
            INSERT INTO track (track_name, artist_id)
            VALUES (:track_name, :artist_id)
            RETURNING id
        """),
        {
            "track_name": title,
            "artist_id": artist_id,
        },
    )

    return result.scalar_one()


def seed_collection_track(conn, collection_id: int, track_id: int, rank: int) -> None:
    existing = conn.execute(
        text("""
            SELECT id
            FROM collection_track_ranking
            WHERE collection_id = :collection_id
              AND ranking = :ranking
            LIMIT 1
        """),
        {
            "collection_id": collection_id,
            "ranking": rank,
        },
    ).scalar_one_or_none()

    if existing is not None:
        conn.execute(
            text("""
                UPDATE collection_track_ranking
                SET track_id = :track_id,
                    updated_at = NOW()
                WHERE id = :id
            """),
            {
                "id": existing,
                "track_id": track_id,
            },
        )
        return

    conn.execute(
        text("""
            INSERT INTO collection_track_ranking (collection_id, track_id, ranking)
            VALUES (:collection_id, :track_id, :ranking)
        """),
        {
            "collection_id": collection_id,
            "track_id": track_id,
            "ranking": rank,
        },
    )


def main() -> None:
    with engine.begin() as conn:
        for collection in CSV_COLLECTIONS:
            category_id = seed_collection_category(
                conn,
                collection["category_slug"],
            )

            collection_id = seed_collection(
                conn,
                collection["collection_slug"],
                collection["collection_name"],
                category_id,
            )

            tracks = load_tracks_from_csv(collection["csv_file"])
            for track in tracks:
                artist_id = get_or_create_artist(conn, track["artist"])
                track_id = get_or_create_track(conn, track["title"], artist_id)

                seed_collection_track(
                    conn,
                    collection_id,
                    track_id,
                    track["rank"],
                )

            print(
                f"Loaded {len(tracks)} tracks into "
                f"{collection['collection_name']}"
            )


if __name__ == "__main__":
    main()
