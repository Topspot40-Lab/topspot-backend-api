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
        SELECT
            a.id AS artist_id,
            a.artist_name,
            COUNT(DISTINCT tr.track_id) AS track_count
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
        GROUP BY a.id, a.artist_name
        HAVING COUNT(DISTINCT tr.track_id) >= :min_tracks
           AND (:max_tracks IS NULL OR COUNT(DISTINCT tr.track_id) <= :max_tracks)
        ORDER BY track_count DESC, a.artist_name
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