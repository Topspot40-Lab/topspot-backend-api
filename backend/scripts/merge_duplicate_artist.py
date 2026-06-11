from __future__ import annotations

import argparse
from sqlalchemy import text
from backend.database import engine


def norm_title_sql() -> str:
    return """
        LOWER(
            REGEXP_REPLACE(
                REGEXP_REPLACE(track_name, '[^a-zA-Z0-9]+', '', 'g'),
                '\\s+', '', 'g'
            )
        )
    """


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-id", type=int, required=True)
    parser.add_argument("--merge-id", type=int, required=True)
    parser.add_argument("--keep-name", type=str, required=True)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    keep_id = args.keep_id
    merge_id = args.merge_id
    keep_name = args.keep_name

    title_norm = norm_title_sql()

    with engine.connect() as conn:
        print("=" * 80)
        print("MERGE DUPLICATE ARTIST")
        print(f"KEEP:  {keep_id}")
        print(f"MERGE: {merge_id}")
        print(f"NAME:  {keep_name}")
        print(f"SAVE:  {args.save}")
        print("=" * 80)

        print("\nArtists:")
        for row in conn.execute(text("""
            SELECT id, artist_name
            FROM artist
            WHERE id IN (:keep_id, :merge_id)
            ORDER BY id
        """), {"keep_id": keep_id, "merge_id": merge_id}):
            print(row)

        print("\nTracks before:")
        for row in conn.execute(text("""
            SELECT artist_id, id, track_name, spotify_track_id
            FROM track
            WHERE artist_id IN (:keep_id, :merge_id)
            ORDER BY artist_id, LOWER(track_name)
        """), {"keep_id": keep_id, "merge_id": merge_id}):
            print(row)

        duplicate_rows = conn.execute(text(f"""
            WITH keep_tracks AS (
                SELECT id, {title_norm} AS title_norm
                FROM track
                WHERE artist_id = :keep_id
            ),
            merge_tracks AS (
                SELECT id, track_name, spotify_track_id, {title_norm} AS title_norm
                FROM track
                WHERE artist_id = :merge_id
            )
            SELECT
                mt.id,
                mt.track_name,
                mt.spotify_track_id,
                COALESCE(tr.track_ranking_count, 0) AS track_ranking_count,
                COALESCE(cr.collection_ranking_count, 0) AS collection_ranking_count,
                COALESCE(tl.locale_count, 0) AS locale_count
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
            LEFT JOIN (
                SELECT track_id, COUNT(*) AS locale_count
                FROM track_locale
                GROUP BY track_id
            ) tl ON tl.track_id = mt.id
            ORDER BY mt.id
        """), {"keep_id": keep_id, "merge_id": merge_id}).all()

        safe_delete_ids = []
        review_ids = []

        print("\nDuplicate title candidates:")
        if not duplicate_rows:
            print("(none)")
        else:
            for row in duplicate_rows:
                track_id, track_name, spotify_id, tr_count, cr_count, locale_count = row
                print(row)

                if spotify_id is None and tr_count == 0 and cr_count == 0:
                    safe_delete_ids.append(track_id)
                else:
                    review_ids.append(track_id)

        print("\nSafe duplicate tracks to delete:")
        print(safe_delete_ids or "(none)")

        print("\nDuplicate tracks requiring review / preserved:")
        print(review_ids or "(none)")

    if not args.save:
        print("\nDRY RUN ONLY. No changes made.")
        print("Add --save to apply.")
        return

    with engine.begin() as conn:
        if safe_delete_ids:
            conn.execute(text("""
                DELETE FROM track_locale
                WHERE track_id = ANY(:track_ids)
            """), {"track_ids": safe_delete_ids})

            conn.execute(text("""
                DELETE FROM track
                WHERE id = ANY(:track_ids)
            """), {"track_ids": safe_delete_ids})

        conn.execute(text("""
            UPDATE track
            SET artist_id = :keep_id
            WHERE artist_id = :merge_id
        """), {"keep_id": keep_id, "merge_id": merge_id})

        # Move any artist stories from duplicate artist to canonical artist.
        # If this creates duplicate stories later, we can clean those separately.
        conn.execute(text("""
            UPDATE artist_story
            SET artist_id = :keep_id
            WHERE artist_id = :merge_id
        """), {"keep_id": keep_id, "merge_id": merge_id})

        # Move artist genre rows, avoiding duplicate genre rows.
        conn.execute(text("""
            DELETE FROM artist_genre ag
            WHERE ag.artist_id = :merge_id
              AND EXISTS (
                  SELECT 1
                  FROM artist_genre keep_ag
                  WHERE keep_ag.artist_id = :keep_id
                    AND keep_ag.genre_id = ag.genre_id
              )
        """), {"keep_id": keep_id, "merge_id": merge_id})

        conn.execute(text("""
            UPDATE artist_genre
            SET artist_id = :keep_id
            WHERE artist_id = :merge_id
        """), {"keep_id": keep_id, "merge_id": merge_id})

        # Move featured artist references too.
        conn.execute(text("""
            UPDATE track
            SET featured_artist_id = :keep_id
            WHERE featured_artist_id = :merge_id
        """), {"keep_id": keep_id, "merge_id": merge_id})

        conn.execute(text("""
            DELETE FROM artist_locale
            WHERE artist_id = :merge_id
        """), {"merge_id": merge_id})

        conn.execute(text("""
            DELETE FROM artist
            WHERE id = :merge_id
        """), {"merge_id": merge_id})

        conn.execute(text("""
            UPDATE artist
            SET artist_name = :keep_name
            WHERE id = :keep_id
        """), {"keep_id": keep_id, "keep_name": keep_name})

    print("\nSAVE COMPLETE.")

    with engine.connect() as conn:
        print("\nVerify:")
        print("Artists:")
        for row in conn.execute(text("""
            SELECT id, artist_name
            FROM artist
            WHERE id IN (:keep_id, :merge_id)
            ORDER BY id
        """), {"keep_id": keep_id, "merge_id": merge_id}):
            print(row)

        print("\nTracks:")
        for row in conn.execute(text("""
            SELECT artist_id, COUNT(*)
            FROM track
            WHERE artist_id IN (:keep_id, :merge_id)
            GROUP BY artist_id
            ORDER BY artist_id
        """), {"keep_id": keep_id, "merge_id": merge_id}):
            print(row)

        print("\nArtist locale:")
        for row in conn.execute(text("""
            SELECT artist_id, COUNT(*)
            FROM artist_locale
            WHERE artist_id IN (:keep_id, :merge_id)
            GROUP BY artist_id
            ORDER BY artist_id
        """), {"keep_id": keep_id, "merge_id": merge_id}):
            print(row)


if __name__ == "__main__":
    main()