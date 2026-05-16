from fastapi import APIRouter, Query
from sqlalchemy import text
from backend.database import engine

router = APIRouter(
    prefix="/artist-spotlight",
    tags=["artist-spotlight"],
)


@router.get("/artists-by-genre")
def artists_by_genre(
        genre: str = Query(...),
        min_tracks: int = Query(3, ge=1),
        max_tracks: int | None = Query(None, ge=1),
):
    sql = text("""
        WITH dg_counts AS (

            SELECT
                a.id AS artist_id,
                COUNT(DISTINCT tr.track_id) AS dg_track_count

            FROM track_ranking tr

            JOIN decade_genre dg
                ON tr.decade_genre_id = dg.id

            JOIN genre g
                ON dg.genre_id = g.id

            JOIN track t
                ON tr.track_id = t.id

            JOIN artist a
                ON t.artist_id = a.id

            WHERE g.slug = :genre

            GROUP BY a.id
        ),

        collection_counts AS (

            SELECT
                a.id AS artist_id,
                COUNT(DISTINCT ctr.track_id) AS collection_track_count

            FROM collection_track_ranking ctr

            JOIN track t
                ON ctr.track_id = t.id

            JOIN artist a
                ON t.artist_id = a.id

            GROUP BY a.id
        )

        SELECT
            a.id AS artist_id,
            a.artist_name,

            COALESCE(dg.dg_track_count, 0) AS dg_track_count,

            COALESCE(cc.collection_track_count, 0) AS collection_track_count

        FROM artist a

        JOIN dg_counts dg
            ON a.id = dg.artist_id

        LEFT JOIN collection_counts cc
            ON a.id = cc.artist_id

        WHERE dg.dg_track_count >= :min_tracks
          AND (
                :max_tracks IS NULL
                OR dg.dg_track_count <= :max_tracks
              )

        ORDER BY
            dg.dg_track_count DESC,
            collection_track_count DESC,
            a.artist_name
    """)

    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "genre": genre,
                "min_tracks": min_tracks,
                "max_tracks": max_tracks,
            },
        ).mappings().all()

    return [dict(row) for row in rows]


@router.get("/artist-tracks")
def artist_tracks(
        artist_id: int = Query(...),
):
    sql = text("""
        SELECT DISTINCT
            t.id AS track_id,
            t.track_name,
            t.spotify_track_id,
            t.duration_ms,
            a.id AS artist_id,
            a.artist_name
        FROM track t
        JOIN artist a
            ON t.artist_id = a.id
        WHERE a.id = :artist_id
          AND (
              EXISTS (
                  SELECT 1
                  FROM track_ranking tr
                  WHERE tr.track_id = t.id
              )
              OR
              EXISTS (
                  SELECT 1
                  FROM collection_track_ranking ctr
                  WHERE ctr.track_id = t.id
              )
          )
        ORDER BY t.track_name
    """)

    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {"artist_id": artist_id},
        ).mappings().all()

    return [dict(row) for row in rows]
