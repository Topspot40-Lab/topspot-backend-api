from fastapi import APIRouter, Query
from sqlalchemy import text
from backend.database import engine
import asyncio

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

COALESCE(dg.dg_track_count, 0) AS genre_track_count,

(
    SELECT COUNT(DISTINCT t2.id)

    FROM track t2

    WHERE t2.artist_id = a.id
      AND (
          EXISTS (
              SELECT 1
              FROM track_ranking tr2
              WHERE tr2.track_id = t2.id
          )
          OR
          EXISTS (
              SELECT 1
              FROM collection_track_ranking ctr2
              WHERE ctr2.track_id = t2.id
          )
      )
) AS total_track_count

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
    genre_track_count DESC,
    total_track_count DESC,
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
        t.album_name,
        t.album_artwork,
        t.year_released,
        t.duration_ms,
        t.detail,
        a.id AS artist_id,
        a.artist_name,
        a.artist_description
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

@router.post("/play")
def play_artist_spotlight(
        artist_id: int = Query(...),
):
    sql = text("""
    SELECT DISTINCT
        t.id AS track_id,
        t.track_name,
        t.spotify_track_id,
        t.album_name,
        t.album_artwork,
        t.year_released,
        t.duration_ms,
        t.detail,
        a.id AS artist_id,
        a.artist_name,
        a.artist_description

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

    return {
        "ok": True,
        "mode": "artist_spotlight",
        "artist_id": artist_id,
        "tracks": [dict(row) for row in rows],
    }

@router.get("/radio-set")
def artist_radio_set(
        genre: str = Query(...),
):
    sql = text("""
    WITH eligible_artists AS (

        SELECT
            a.id AS artist_id,
            a.artist_name,
            COUNT(DISTINCT t.id) AS track_count

        FROM track_ranking tr

        JOIN decade_genre dg
            ON tr.decade_genre_id = dg.id

        JOIN genre g
            ON dg.genre_id = g.id

        JOIN track t
            ON tr.track_id = t.id

        JOIN artist a
            ON t.artist_id = a.id

        WHERE (
            :genre = 'ALL'
            OR g.slug = :genre
        )
        AND g.slug != 'tv_themes'

        GROUP BY a.id, a.artist_name

        HAVING COUNT(DISTINCT t.id) >= 2
    ),

    selected_artist AS (

        SELECT *
        FROM eligible_artists
        ORDER BY RANDOM()
        LIMIT 1
    )

SELECT
    t.id AS track_id,
    t.track_name,
    t.spotify_track_id,
    t.album_name,
    t.album_artwork,
    t.year_released,
    t.duration_ms,
    t.detail,
    a.id AS artist_id,
    a.artist_name,
    a.spotify_artist_id,
    a.artist_description

    FROM track t

    JOIN artist a
        ON t.artist_id = a.id

    JOIN selected_artist sa
        ON sa.artist_id = a.id

    ORDER BY RANDOM()
    """)

    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {"genre": genre},
        ).mappings().all()

    tracks = [dict(row) for row in rows]

    if not tracks:
        return {
            "ok": False,
            "error": "No eligible artist set found."
        }

    limit = 2 if len(tracks) == 2 else 3

    return {
        "ok": True,
        "mode": "artist_radio",
        "genre": genre,
        "artist_id": tracks[0]["artist_id"],
        "artist_name": tracks[0]["artist_name"],
        "track_count": len(tracks),
        "tracks": tracks[:limit],
    }

@router.post("/play-radio")
async def play_artist_radio(
        genre: str = Query(...),
        tts_language: str = Query("en"),
        play_intro: bool = Query(True),
        play_detail: bool = Query(True),
        play_artist_description: bool = Query(False),
        play_track: bool = Query(True),
):
    from backend.services.artist_radio_sequence import run_artist_radio_sequence

    asyncio.create_task(
        run_artist_radio_sequence(
            genre=genre,
            tts_language=tts_language,
            play_intro=play_intro,
            play_detail=play_detail,
            play_artist_description=play_artist_description,
            play_track=play_track,
        )
    )

    return {
        "ok": True,
        "message": "Artist Radio started",
        "genre": genre,
    }
