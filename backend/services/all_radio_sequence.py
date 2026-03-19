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
    genres = []
    clock_index = 0

    previous_bucket = None
    last_played_ranking_id = None
    set_number = 0

    recent_decades = []
    MAX_RECENT_DECADES = 3

    recent_artists = []
    MAX_RECENT_ARTISTS = 5

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

                # 🕒 Build station clock from DB genres
                genres = list({g for _, g in VALID_BUCKETS_CACHE})
                random.shuffle(genres)

                logger.info("🕒 Station clock genres: %s", genres)

                clock_index = 0

            valid_buckets = VALID_BUCKETS_CACHE

            # ─────────────────────────────
            # PICK RANDOM BUCKET
            # ─────────────────────────────
            # avoid repeating recent decades
            filtered = [
                (d, g) for (d, g) in valid_buckets
                if d not in recent_decades
            ]

            if not filtered:
                filtered = valid_buckets

            if genres:
                target_genre = genres[clock_index]
                clock_index = (clock_index + 1) % len(genres)

                candidates = [(d, g) for (d, g) in filtered if g == target_genre]
            else:
                candidates = filtered

            if not candidates:
                candidates = filtered

            decade, genre = random.choice(candidates)

            while (decade, genre) == previous_bucket:
                decade, genre = random.choice(valid_buckets)

            previous_bucket = (decade, genre)
            set_number += 1

            recent_decades.append(decade)

            if len(recent_decades) > MAX_RECENT_DECADES:
                recent_decades.pop(0)

            logger.info("🎲 Bucket chosen: %s / %s", decade, genre)

            update_phase(
                "loading",
                track_name="",
                artist_name="",
                context={
                    "mode": "all_radio",
                    "decade": decade,
                    "genre": genre,
                    "set_number": set_number,
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

            # avoid repeating recent artists
            filtered_block = [
                row for row in block_rows
                if row[1].artist_name not in recent_artists
            ]

            if filtered_block:
                block_rows = filtered_block

            # SINGLE MODE → only keep one track
            if category == "single":
                block_rows = block_rows[:1]

            logger.info(
                "🎯 Block built decade=%s genre=%s tracks=%d",
                decade,
                genre,
                len(block_rows),
            )

            total_ms = sum(row[0].duration_ms for row in block_rows if row[0].duration_ms)

            logger.info(
                "📻 Radio block: %d tracks • %.1f minutes",
                len(block_rows),
                total_ms / 60000
            )

            # ─────────────────────────────
            # PLAY BLOCK
            # ─────────────────────────────
            for idx, (track, artist, tr_rank, decade_obj, genre_obj) in enumerate(block_rows, start=1):

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
                        "mode": "all_radio",
                        "decade": decade,
                        "genre": genre,
                        "set_number": set_number,
                        "block_size": len(block_rows),
                        "block_position": idx,

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

                recent_artists.append(artist.artist_name)

                if len(recent_artists) > MAX_RECENT_ARTISTS:
                    recent_artists.pop(0)

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

                # Wait for track to finish
                track_done_event.clear()
                logger.info(f"⏳ WAITING FOR TRACK END: {id(track_done_event)}")
                await track_done_event.wait()

                # Enter paused state
                update_phase(
                    "paused",
                    track_name=track.track_name,
                    artist_name=artist.artist_name,
                    current_rank=rank,
                    context={
                        "mode": "all_radio",
                        "decade": decade,
                        "genre": genre,
                        "set_number": set_number,
                        "block_size": len(block_rows),
                        "block_position": idx,
                    },
                )

                logger.info("⏸ Paused — waiting for NEXT button")

                # 🔥 THIS IS THE MISSING PIECE
                track_done_event.clear()
                await track_done_event.wait()

                logger.info("▶️ NEXT received — advancing to next track")


    except asyncio.CancelledError:
        logger.info("⛔ ALL RADIO sequence cancelled")
        raise

    finally:
        flags.is_playing = False
        flags.stopped = True
        logger.info("📻 ALL RADIO mode stopped")
