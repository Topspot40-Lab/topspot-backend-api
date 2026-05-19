# backend/services/artist_radio_sequence.py

import asyncio
import logging
from sqlalchemy import text

from backend.database import engine
from backend.state.narration import track_done_event
from backend.services.spotify.playback import play_spotify_track
from backend.state.playback_state import update_phase, begin_track

logger = logging.getLogger(__name__)


def load_artist_radio_set(
        genre: str,
        artist_id: int | None = None,
        spotify_artist_id: str | None = None,
) -> dict:
    sql = text("""
    WITH eligible_artists AS (
        SELECT
            a.id AS artist_id,
            a.artist_name,
            COUNT(DISTINCT t.id) AS track_count
        FROM track_ranking tr
        JOIN decade_genre dg ON tr.decade_genre_id = dg.id
        JOIN genre g ON dg.genre_id = g.id
        JOIN track t ON tr.track_id = t.id
        JOIN artist a ON t.artist_id = a.id
        WHERE (:genre = 'ALL' OR g.slug = :genre)
          AND g.slug != 'tv_themes'
          AND (:artist_id IS NULL OR a.id = :artist_id)
          AND (:spotify_artist_id IS NULL OR a.spotify_artist_id = :spotify_artist_id)
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
    JOIN artist a ON t.artist_id = a.id
    JOIN selected_artist sa ON sa.artist_id = a.id
    ORDER BY RANDOM()
    """)

    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "genre": genre,
                "artist_id": artist_id,
                "spotify_artist_id": spotify_artist_id,
            }
        ).mappings().all()

    tracks = [dict(row) for row in rows]

    if not tracks:
        return {"ok": False, "error": "No eligible artist set found."}

    limit = 2 if len(tracks) == 2 else 3

    return {
        "ok": True,
        "mode": "artist_radio",
        "genre": genre,
        "artist_id": tracks[0]["artist_id"],
        "artist_name": tracks[0]["artist_name"],
        "artist_description": tracks[0].get("artist_description"),
        "track_count": len(tracks),
        "tracks": tracks[:limit],
    }


async def run_artist_radio_sequence(
        *,
        genre: str,
        artist_id: int | None = None,
        spotify_artist_id: str | None = None,
        tts_language: str = "en",
        play_intro: bool = True,
        play_detail: bool = True,
        play_artist_description: bool = False,
        play_track: bool = True,
):
    radio_set = load_artist_radio_set(
        genre,
        artist_id,
        spotify_artist_id,
    )

    if not radio_set.get("ok"):
        logger.warning("Artist Radio failed: %s", radio_set)
        return radio_set

    artist_name = radio_set["artist_name"]
    artist_description = radio_set.get("artist_description")
    tracks = radio_set["tracks"]

    logger.info("🎙️ Artist Radio set started: %s (%s tracks)", artist_name, len(tracks))

    # V1 artist set intro: text-only for now
    update_phase(
        phase="artist",
        is_playing=True,
        current_rank=0,
        context={
            "type": "artist_radio",
            "programType": "RADIO_ARTIST",
            "genre": genre,

            # Fake card metadata for the set intro
            "artist_id": tracks[0]["artist_id"],
            "artist_name": artist_name,
            "spotify_artist_id": tracks[0].get("spotify_artist_id"),
            "track_id": tracks[0]["track_id"],
            "track_name": f"{artist_name} Artist Spotlight",
            "spotify_track_id": tracks[0]["spotify_track_id"],
            "album_artwork": tracks[0].get("album_artwork"),
            "duration_ms": 3000,

            # Actual narration text
            "artist_text": artist_description,
            "artistText": artist_description,
            "audio_url": None,
        },
    )

    await asyncio.sleep(3)

    for index, track in enumerate(tracks, start=1):
        track_done_event.clear()

        update_phase(
            phase="detail",
            is_playing=True,
            current_rank=index,
            context={
                "type": "artist_radio",
                "programType": "RADIO_ARTIST",
                "genre": genre,
                "artist_id": track["artist_id"],
                "artist_name": track["artist_name"],
                "spotify_artist_id": track.get("spotify_artist_id"),
                "track_id": track["track_id"],
                "track_name": track["track_name"],
                "artist_text": track.get("artist_description"),
                "artistText": track.get("artist_description"),
                "detail": track.get("detail"),
                "spotify_track_id": track["spotify_track_id"],
                "album_artwork": track.get("album_artwork"),
                "duration_ms": track.get("duration_ms"),
            },
        )

        await asyncio.sleep(2)

        if play_track and track.get("spotify_track_id"):
            update_phase(
                phase="track",
                is_playing=True,
                current_rank=index,
                duration_seconds=(track.get("duration_ms") or 0) / 1000,
                elapsed_seconds=0,
                context={
                    "type": "artist_radio",
                    "programType": "RADIO_ARTIST",
                    "genre": genre,
                    "artist_id": track["artist_id"],
                    "artist_name": track["artist_name"],
                    "spotify_artist_id": track.get("spotify_artist_id"),
                    "track_id": track["track_id"],
                    "track_name": track["track_name"],
                    "artist_text": track.get("artist_description"),
                    "artistText": track.get("artist_description"),
                    "detail": track.get("detail"),
                    "spotify_track_id": track["spotify_track_id"],
                    "album_artwork": track.get("album_artwork"),
                    "duration_ms": track.get("duration_ms"),
                },
            )

            await play_spotify_track(track["spotify_track_id"])

            duration_seconds = (track.get("duration_ms") or 0) / 1000
            begin_track(duration_seconds)

            logger.info("🎵 Artist Radio playing: %s - %s", track["artist_name"], track["track_name"])

            await track_done_event.wait()

    update_phase(
        phase="idle",
        is_playing=False,
        context={
            "type": "artist_radio",
            "programType": "RADIO_ARTIST",
            "genre": genre,
            "artist_name": artist_name,
        },
    )

    logger.info("✅ Artist Radio set finished: %s", artist_name)

    return {"ok": True, "artist_name": artist_name, "tracks": tracks}
