from __future__ import annotations

from sqlalchemy import text
from backend.database import engine


TITLE_NORM = """
LOWER(
    REGEXP_REPLACE(
        REGEXP_REPLACE(track_name, '[^a-zA-Z0-9]+', '', 'g'),
        '\\s+', '', 'g'
    )
)
"""


def main() -> None:
    auto = []
    review = []

    with engine.connect() as conn:
        groups = conn.execute(text("""
            SELECT
                LOWER(TRIM(artist_name)) AS normalized_name,
                STRING_AGG(id::text, ', ' ORDER BY id) AS artist_ids
            FROM artist
            GROUP BY LOWER(TRIM(artist_name))
            HAVING COUNT(*) = 2
            ORDER BY normalized_name
        """)).all()

        for normalized_name, artist_ids_text in groups:
            ids = [int(x.strip()) for x in artist_ids_text.split(",")]
            keep_id, merge_id = ids[0], ids[1]

            artists = conn.execute(text("""
                SELECT id, artist_name
                FROM artist
                WHERE id IN (:keep_id, :merge_id)
                ORDER BY id
            """), {"keep_id": keep_id, "merge_id": merge_id}).all()

            keep_name = artists[1][1] if artists[1][1][0].isupper() else artists[0][1].title()

            duplicate_rows = conn.execute(text(f"""
                WITH keep_tracks AS (
                    SELECT id, track_name, spotify_track_id, {TITLE_NORM} AS title_norm
                    FROM track
                    WHERE artist_id = :keep_id
                ),
                merge_tracks AS (
                    SELECT id, track_name, spotify_track_id, {TITLE_NORM} AS title_norm
                    FROM track
                    WHERE artist_id = :merge_id
                )
                SELECT
                    mt.id,
                    mt.track_name,
                    mt.spotify_track_id,
                    COALESCE(tr.track_ranking_count, 0) AS track_ranking_count,
                    COALESCE(cr.collection_ranking_count, 0) AS collection_ranking_count
                FROM merge_tracks mt
                JOIN keep_tracks kt ON kt.title_norm = mt.title_norm
                LEFT JOIN (
                    SELECT track_id, COUNT(*) AS track_ranking_count
                    FROM track_ranking
                    GROUP BY track_id
                ) tr ON tr.track_id = mt.id
                LEFT JOIN (
                    SELECT track_id, COUNT(*) AS collection_ranking_count
                    FROM collection_track_ranking
                    GROUP BY track_id
                ) cr ON cr.track_id = mt.id
                ORDER BY mt.id
            """), {"keep_id": keep_id, "merge_id": merge_id}).all()

            safe_delete = []
            needs_review = []

            for track_id, track_name, spotify_id, tr_count, cr_count in duplicate_rows:
                if spotify_id is None and tr_count == 0 and cr_count == 0:
                    safe_delete.append((track_id, track_name))
                else:
                    needs_review.append((track_id, track_name, spotify_id, tr_count, cr_count))

            keep_count = conn.execute(text("""
                SELECT COUNT(*) FROM track WHERE artist_id = :artist_id
            """), {"artist_id": keep_id}).scalar()

            merge_count = conn.execute(text("""
                SELECT COUNT(*) FROM track WHERE artist_id = :artist_id
            """), {"artist_id": merge_id}).scalar()

            item = {
                "name": keep_name,
                "keep_id": keep_id,
                "merge_id": merge_id,
                "keep_count": keep_count,
                "merge_count": merge_count,
                "safe_delete": safe_delete,
                "needs_review": needs_review,
            }

            if needs_review:
                review.append(item)
            else:
                auto.append(item)

    print("=" * 80)
    print("DUPLICATE ARTIST CLASSIFICATION REPORT")
    print("=" * 80)
    print(f"AUTO APPROVE: {len(auto)}")
    print(f"REQUIRES REVIEW: {len(review)}")

    print("\n" + "=" * 80)
    print("AUTO APPROVE")
    print("=" * 80)

    for item in auto:
        print(
            f'{item["name"]} | keep={item["keep_id"]} | merge={item["merge_id"]} | '
            f'keep_tracks={item["keep_count"]} | merge_tracks={item["merge_count"]} | '
            f'safe_deletes={len(item["safe_delete"])}'
        )

    print("\n" + "=" * 80)
    print("REQUIRES REVIEW")
    print("=" * 80)

    for item in review:
        print(
            f'\n{item["name"]} | keep={item["keep_id"]} | merge={item["merge_id"]} | '
            f'keep_tracks={item["keep_count"]} | merge_tracks={item["merge_count"]}'
        )
        print("Needs review:")
        for row in item["needs_review"]:
            print(f"  {row}")


if __name__ == "__main__":
    main()