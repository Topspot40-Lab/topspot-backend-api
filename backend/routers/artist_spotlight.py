from fastapi import APIRouter, Query
from sqlalchemy import text
from backend.database import engine
import asyncio

from sqlmodel import Session, select
from backend.models.dbmodels import Artist, ArtistStory
from backend.models.studio_models import (
    StudioProductionAsset,
)

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
        WITH nostalgia_counts AS (
            SELECT
                a.id AS artist_id,
                COUNT(DISTINCT tr.track_id) AS nostalgia_track_count
            FROM track_ranking tr
            JOIN decade_genre dg ON tr.decade_genre_id = dg.id
            JOIN genre g ON dg.genre_id = g.id
            JOIN track t ON tr.track_id = t.id
            JOIN artist a ON t.artist_id = a.id
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
            JOIN collection c ON ctr.collection_id = c.id
            JOIN track t ON ctr.track_id = t.id
            JOIN artist a ON t.artist_id = a.id
            WHERE (
                :genre IS NULL
                OR :genre = 'all'
                OR c.artist_spotlight_genre = :genre
            )
            GROUP BY a.id
        ),

        artist_counts AS (
            SELECT
                a.id AS artist_id,
                a.artist_name,

                COALESCE(nc.nostalgia_track_count, 0)
                + COALESCE(cc.collection_track_count, 0)
                AS genre_track_count,

                EXISTS (
                    SELECT 1
                    FROM artist_story s
                    WHERE s.artist_id = a.id
                      AND s.language_code = 'en'
                ) AS has_story,

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
                                  AND ctr2.ranking BETWEEN 1 AND 100
                            )
                      )
                ) AS total_track_count

            FROM artist a
            LEFT JOIN nostalgia_counts nc ON a.id = nc.artist_id
            LEFT JOIN collection_counts cc ON a.id = cc.artist_id
        )

        SELECT
            artist_id,
            artist_name,
            has_story,
            genre_track_count,
            total_track_count
        FROM artist_counts
        WHERE genre_track_count >= :min_tracks
          AND (
                :max_tracks IS NULL
                OR genre_track_count <= :max_tracks
              )
          AND (
                :featured_only = false
                OR has_story = true
              )
        ORDER BY
            genre_track_count DESC,
            total_track_count DESC,
            artist_name
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
        a.artist_description,
        jsonb_build_object(
            'en', jsonb_build_object(
                'intro', NULL,
                'detail', t.detail,
                'artist', a.artist_description
            ),
            'es', jsonb_build_object(
                'intro', NULL,
                'detail', COALESCE(tl_es.detail_text, t.detail),
                'artist', COALESCE(al_es.artist_description_text, a.artist_description)
            ),
            'ptbr', jsonb_build_object(
                'intro', NULL,
                'detail', COALESCE(tl_ptbr.detail_text, t.detail),
                'artist', COALESCE(al_ptbr.artist_description_text, a.artist_description)
            )
        ) AS texts_by_language
    FROM track t
    JOIN artist a
        ON t.artist_id = a.id
    LEFT JOIN track_locale tl_es
        ON tl_es.track_id = t.id
       AND tl_es.language_code = 'es'
    LEFT JOIN track_locale tl_ptbr
        ON tl_ptbr.track_id = t.id
       AND tl_ptbr.language_code = 'pt-BR'
    LEFT JOIN artist_locale al_es
        ON al_es.artist_id = a.id
       AND al_es.language_code = 'es'
    LEFT JOIN artist_locale al_ptbr
        ON al_ptbr.artist_id = a.id
       AND al_ptbr.language_code = 'pt-BR'
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
                AND ctr.ranking BETWEEN 1 AND 100
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


@router.get("/artist-summary")
def artist_summary(
        artist_id: int = Query(...),
        language: str = Query("en"),
):
    locale_code = "pt-BR" if language in ("ptbr", "pt-BR") else language

    artist_sql = text("""
        SELECT
            a.id AS artist_id,
            a.artist_name,
            NULL AS artist_artwork,
            COALESCE(al.artist_description_text, a.artist_description) AS artist_description
        FROM artist a
        LEFT JOIN artist_locale al
            ON al.artist_id = a.id
           AND al.language_code = :locale_code
        WHERE a.id = :artist_id
    """)

    nostalgia_sql = text("""
        SELECT
            d.decade_name || ' ' || g.genre_name AS program_name,
            tr.ranking AS rank,
            t.track_name
        FROM track_ranking tr
        JOIN decade_genre dg ON tr.decade_genre_id = dg.id
        JOIN decade d ON dg.decade_id = d.id
        JOIN genre g ON dg.genre_id = g.id
        JOIN track t ON tr.track_id = t.id
            WHERE t.artist_id = :artist_id
                AND tr.ranking BETWEEN 1 AND 100
        ORDER BY d.decade_name, g.genre_name, tr.ranking
    """)

    collection_sql = text("""
        SELECT
            c.name AS program_name,
            ctr.ranking AS rank,
            t.track_name
        FROM collection_track_ranking ctr
        JOIN collection c ON ctr.collection_id = c.id
        JOIN track t ON ctr.track_id = t.id
        WHERE t.artist_id = :artist_id
        ORDER BY c.name, ctr.ranking
    """)

    with engine.connect() as conn:
        artist = conn.execute(
            artist_sql,
            {
                "artist_id": artist_id,
                "locale_code": locale_code,
            },
        ).mappings().first()

        if not artist:
            return {
                "ok": False,
                "artist_id": artist_id,
                "message": "Artist not found",
            }

        nostalgia_rows = conn.execute(
            nostalgia_sql,
            {"artist_id": artist_id},
        ).mappings().all()

        collection_rows = conn.execute(
            collection_sql,
            {"artist_id": artist_id},
        ).mappings().all()

    return {
        "ok": True,
        "artist": dict(artist),
        "nostalgiaAppearances": [dict(row) for row in nostalgia_rows],
        "collectionAppearances": [dict(row) for row in collection_rows],
        "appearanceCount": len(nostalgia_rows) + len(collection_rows),
    }


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
                      AND ctr.ranking BETWEEN 1 AND 100
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
        artist_id: int | None = Query(None),
        spotify_artist_id: str | None = Query(None),
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
            artist_id=artist_id,
            spotify_artist_id=spotify_artist_id,
        )
    )

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

    with Session(engine) as session:
        youtube_asset = session.exec(
            select(StudioProductionAsset)
            .where(
                StudioProductionAsset.production_type
                == "artist"
            )
            .where(
                StudioProductionAsset.source_id
                == artist_id
            )
            .where(
                StudioProductionAsset.asset_type
                == "localized_video"
            )
            .where(
                StudioProductionAsset.language_code
                == language
            )
            .where(
                StudioProductionAsset.status
                == "published"
            )
            .where(
                StudioProductionAsset.is_current
                == True
            )
        ).first()

    youtube_url = (
        youtube_asset.youtube_url
        if youtube_asset
        else None
    )
    youtube_fields = {
        "has_youtube_video": bool(youtube_url),
        "youtube_video_id": (
            youtube_asset.youtube_video_id
            if youtube_asset
            else None
        ),
        "youtube_url": youtube_url,
    }

    if not row:
        return {
            "ok": True,
            "has_story": False,
            "artist_id": artist_id,
            "language": language,
            **youtube_fields,
        }

    return {
        "ok": True,
        "has_story": True,
        **dict(row),
        **youtube_fields,
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
