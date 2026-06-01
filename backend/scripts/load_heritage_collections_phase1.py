from sqlalchemy import text
from backend.database import engine


HERITAGE_COLLECTIONS = [
    {
        "category_slug": "american_heritage_favorites",
        "collection_slug": "mexican_american_favorites",
        "collection_name": "Mexican-American Favorites",
        "tracks": [
            {"rank": 1, "title": "La Bamba", "artist": "Ritchie Valens"},
            # more tracks go here
        ],
    },
]


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
        for collection in HERITAGE_COLLECTIONS:
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

            for track in collection["tracks"]:
                artist_id = get_or_create_artist(conn, track["artist"])
                track_id = get_or_create_track(conn, track["title"], artist_id)

                seed_collection_track(
                    conn,
                    collection_id,
                    track_id,
                    track["rank"],
                )

            print(
                f"Loaded {len(collection['tracks'])} tracks into "
                f"{collection['collection_name']}"
            )


if __name__ == "__main__":
    main()