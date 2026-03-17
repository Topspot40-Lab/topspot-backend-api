from __future__ import annotations

import asyncio
import logging
import random
from sqlalchemy import select
from backend.models import (
    Decade,
    Genre,
    DecadeGenre,
    TrackRanking
)

from backend.services.decade_genre_loader import load_decade_genre_rows
from backend.services.block_builder import build_track_block
from backend.state.playback_state import status, mark_playing, update_phase
from backend.state.playback_flags import flags
from backend.state.narration import track_done_event

logger = logging.getLogger(__name__)


VALID_BUCKETS_CACHE = None

def get_valid_buckets(session):
    q = (
        select(Decade.slug, Genre.slug)
        .join(DecadeGenre, DecadeGenre.decade_id == Decade.id)
        .join(Genre, Genre.id == DecadeGenre.genre_id)
        .join(TrackRanking, TrackRanking.decade_genre_id == DecadeGenre.id)
        .group_by(Decade.slug, Genre.slug)
    )

    rows = session.exec(q).all()

    return [(d, g) for d, g in rows]


async def run_all_radio_sequence(
        *,
        tts_language: str = "en",
        category: str | None = None,
):
    """
    ALL / ALL radio mode.

    Chooses a random decade+genre bucket, builds
    an ~8-12 minute block, plays it, then repeats.
    """

    logger.info("📻 ALL-ALL RADIO MODE START")

    status.stopped = False
    status.cancel_requested = False
    status.language = tts_language

    flags.is_playing = True
    flags.stopped = False
    flags.cancel_requested = False
    flags.mode = "all_radio"

    mark_playing(
        mode="all_radio",
        language=tts_language,
        context={
            "mode": "all_radio",
            "category": category,
        }
    )

    global VALID_BUCKETS_CACHE
    previous_bucket = None
    last_played_ranking_id = None

    try:

        while True:

            # ─────────────────────────────
            # BUILD VALID BUCKET LIST
            # ─────────────────────────────
            if VALID_BUCKETS_CACHE is None:
                from backend.database import get_db_session

                with get_db_session() as session:
                    VALID_BUCKETS_CACHE = get_valid_buckets(session)

                logger.info("📚 Valid radio buckets loaded: %d", len(VALID_BUCKETS_CACHE))

                if not VALID_BUCKETS_CACHE:
                    logger.error("❌ No valid radio buckets found")
                    return

            valid_buckets = VALID_BUCKETS_CACHE

            # ─────────────────────────────
            # PICK RANDOM BUCKET
            # ─────────────────────────────
            decade, genre = random.choice(valid_buckets)

            while (decade, genre) == previous_bucket:
                decade, genre = random.choice(valid_buckets)

            previous_bucket = (decade, genre)

            logger.info("🎲 Bucket chosen: %s / %s", decade, genre)

            update_phase(
                "loading",
                track_name="",
                artist_name="",
                context={
                    "mode": "all_radio",
                    "decade": decade,
                    "genre": genre,
                },
            )

            # ─────────────────────────────
            # LOAD ROWS
            # ─────────────────────────────
            rows = await asyncio.to_thread(
                load_decade_genre_rows,
                decade=decade,
                genre=genre,
                start_rank=1,
                end_rank=40,
            )

            if not rows:
                logger.warning("No rows for %s/%s", decade, genre)
                continue

            # ─────────────────────────────
            # BUILD BLOCK
            # ─────────────────────────────
            block_rows = build_track_block(rows)

            logger.info(
                "🎯 Block built decade=%s genre=%s tracks=%d",
                decade,
                genre,
                len(block_rows),
            )

            # ─────────────────────────────
            # PLAY BLOCK
            # ─────────────────────────────
            for track, artist, tr_rank, decade_obj, genre_obj in block_rows:

                if status.cancel_requested or status.stopped:
                    logger.info("🛑 Radio mode cancelled")
                    return

                rank = tr_rank.ranking

                flags.current_rank = rank
                status.current_rank = rank
                status.current_ranking_id = tr_rank.id

                update_phase(
                    "track",
                    track_name=track.track_name,
                    artist_name=artist.artist_name,
                    current_rank=rank,
                    context={
                        "mode": "decade_genre",
                        "decade": decade,
                        "genre": genre,

                        "spotify_track_id": track.spotify_track_id,
                        "ranking_id": tr_rank.id,

                        "year": track.year_released,
                        "genre_name": genre_obj.genre_name,
                        "decade_name": decade_obj.decade_name,

                        "album_art": track.album_artwork,
                    },
                )

                logger.info(
                    "🎵 PLAY %s — %s (%s/%s)",
                    track.track_name,
                    artist.artist_name,
                    decade,
                    genre,
                )
                logger.info(
                    "📡 UI UPDATE %s — %s rank=%s",
                    track.track_name,
                    artist.artist_name,
                    rank
                )

                # Ignore duplicate finish handling
                if tr_rank.id == last_played_ranking_id:
                    continue

                last_played_ranking_id = tr_rank.id

                track_done_event.clear()
                await track_done_event.wait()

                # ─────────────────────────────
                # SINGLE MODE EXIT
                # ─────────────────────────────
                if category == "single":
                    logger.info("🛑 Single mode: stopping radio loop after one track")
                    return

    except asyncio.CancelledError:
        logger.info("⛔ ALL RADIO sequence cancelled")
        raise

    finally:
        flags.is_playing = False
        flags.stopped = True
        logger.info("📻 ALL RADIO mode stopped")
