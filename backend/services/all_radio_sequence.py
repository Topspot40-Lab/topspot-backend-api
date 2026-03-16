from __future__ import annotations

import asyncio
import logging
import random

from backend.services.decade_genre_loader import load_decade_genre_rows
from backend.services.block_builder import build_track_block
from backend.state.playback_state import status, mark_playing, update_phase
from backend.state.playback_flags import flags
from backend.state.narration import track_done_event

logger = logging.getLogger(__name__)

DECADES = [
    "1950s","1960s","1970s","1980s",
    "1990s","2000s","2010s","2020s"
]

GENRES = [
    "rock","pop","country","rnb",
    "blues_jazz","tv_themes","stage_screen","latin"
]


async def run_all_radio_sequence(
    *,
    tts_language: str = "en",
    play_track: bool = True,
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
        context={"mode": "all_radio"},
    )

    previous_bucket = None

    try:

        while True:

            # ─────────────────────────────
            # PICK RANDOM BUCKET
            # ─────────────────────────────
            while True:
                decade = random.choice(DECADES)
                genre = random.choice(GENRES)

                if (decade, genre) != previous_bucket:
                    break

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
                        "mode": "spotify",
                        "decade": decade,
                        "genre": genre,
                        "spotify_track_id": track.spotify_track_id,
                        "ranking_id": tr_rank.id,
                    },
                )

                logger.info(
                    "🎵 PLAY %s — %s (%s/%s)",
                    track.track_name,
                    artist.artist_name,
                    decade,
                    genre,
                )

                track_done_event.clear()
                await track_done_event.wait()

    except asyncio.CancelledError:
        logger.info("⛔ ALL RADIO sequence cancelled")
        raise

    finally:
        flags.is_playing = False
        flags.stopped = True
        logger.info("📻 ALL RADIO mode stopped")