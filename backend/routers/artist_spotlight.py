from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from backend.database import engine
import asyncio
from backend.state.playback_runtime import bind_request_user, bind_task, current_user_id

from sqlmodel import Session, select
from backend.models.dbmodels import Artist, ArtistStory

router = APIRouter(
    prefix="/artist-spotlight",
    tags=["artist-spotlight"],
)


@router.get("/artists-by-genre")
def artists_by_genre(
        genre: str | None = Query(None),
        min_tracks: int = Query(3, ge=1),
        max_tracks: int | None = Query(None, ge=1),
        featured_only: bool = Query(True),
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

            WHERE (
                :genre IS NULL
                OR :genre = 'all'
                OR g.slug = :genre
            )

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

EXISTS (
    SELECT 1
    FROM artist_story s
    WHERE s.artist_id = a.id
      AND s.language_code = 'en'
) AS has_story,

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

  AND (
        :featured_only = false
        OR EXISTS (
            SELECT 1
            FROM artist_story s
            WHERE s.artist_id = a.id
              AND s.language_code = 'en'
        )
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
                "featured_only": featured_only,
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


@router.post("/play-radio", dependencies=[Depends(bind_request_user)])
async def play_artist_radio(
        genre: str = Query(...),
        artist_id: int | None = Query(None),
        spotify_artist_id: str | None = Query(None),
        tts_language: str = Query("en"),
        play_intro: bool = Query(True),
        play_detail: bool = Query(True),
        play_artist_description: bool = Query(False),
        play_track: bool = Query(True),
):
    from backend.services.artist_radio_sequence import run_artist_radio_sequence

    task = asyncio.create_task(
        run_artist_radio_sequence(
            genre=genre,
            tts_language=tts_language,
            play_intro=play_intro,
            play_detail=play_detail,
            play_artist_description=play_artist_description,
            play_track=play_track,
            artist_id=artist_id,
            spotify_artist_id=spotify_artist_id,
        )
    )
    bind_task(task, current_user_id())

    return {
        "ok": True,
        "message": "Artist Radio started",
        "genre": genre,
    }

@router.get("/artist-story")
def artist_story(
        artist_id: int = Query(...),
        language: str = Query("en"),
):
    sql = text("""
        SELECT
            s.id AS story_id,
            s.artist_id,
            s.language_code,
            s.title,
            s.story_type,
            s.duration_seconds,
            s.tts_bucket,
            s.tts_key
        FROM artist_story s
        WHERE s.artist_id = :artist_id
          AND s.language_code = :language
          AND s.tts_key IS NOT NULL
        LIMIT 1
    """)

    with engine.connect() as conn:
        row = conn.execute(
            sql,
            {
                "artist_id": artist_id,
                "language": language,
            },
        ).mappings().first()

    if not row:
        return {
            "ok": False,
            "has_story": False,
            "artist_id": artist_id,
            "language": language,
        }

    return {
        "ok": True,
        "has_story": True,
        **dict(row),
    }

@router.post("/play-artist-story")
def play_artist_story(
        artist_id: int = Query(...),
        language: str = Query("en"),
):
    with Session(engine) as session:
        result = session.exec(
            select(ArtistStory, Artist)
            .join(Artist, Artist.id == ArtistStory.artist_id)
            .where(ArtistStory.artist_id == artist_id)
            .where(ArtistStory.language_code == language)
            .where(ArtistStory.tts_key.is_not(None))
        ).first()

        if not result:
            return {
                "ok": False,
                "message": "Artist story not found"
            }

        story, artist = result
        return {
            "ok": True,
            "story_id": story.id,
            "title": story.title,
            "story_text": story.story_text,
            "duration_seconds": story.duration_seconds,
            "tts_bucket": story.tts_bucket,
            "tts_key": story.tts_key,
            "bed_bucket": "audio-en",
            "bed_key": "bed-tracks/docuseries/bed_01.mp3",
            "artist_id": artist.id,
            "artist_name": artist.artist_name,
            "artist_artwork": artist.artist_artwork,
        }