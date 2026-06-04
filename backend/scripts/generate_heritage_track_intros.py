from sqlalchemy import text

from backend.database import engine
import argparse

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


def main(limit: int | None) -> None:
    sql = text("""
        SELECT
            ctr.id AS ranking_id,
            ctr.ranking,
            c.name AS collection_name,
            t.track_name,
            a.artist_name
        FROM collection_track_ranking ctr
        JOIN collection c
            ON c.id = ctr.collection_id
        JOIN track t
            ON t.id = ctr.track_id
        JOIN artist a
            ON a.id = t.artist_id
        WHERE c.slug = ANY(:slugs)
        ORDER BY c.slug, ctr.ranking
LIMIT COALESCE(:limit, 999999)
    """)

    update_sql = text("""
        UPDATE collection_track_ranking
        SET intro = :intro,
            updated_at = NOW()
        WHERE id = :ranking_id
    """)

    updated = 0

    with engine.begin() as conn:
        rows = conn.execute(
            sql,
            {
                "slugs": list(HERITAGE_SLUGS),
                "limit": limit,
            },
        ).mappings().all()

        for row in rows:
            intro = (
                f"Coming in at number {row['ranking']} in "
                f"{row['collection_name']}, here is "
                f"{row['track_name']} by {row['artist_name']}."
            )

            conn.execute(
                update_sql,
                {
                    "ranking_id": row["ranking_id"],
                    "intro": intro,
                },
            )

            updated += 1

    print(f"Updated {updated} Heritage track intros.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    main(limit=args.limit)