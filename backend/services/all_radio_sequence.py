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

from backend.config.playback_block_config import MIN_TRACKS_PER_BLOCK
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
        genre_filter: str | None = None,   # 👈 ADD THIS
):
    # 🎛️ Get selection from playback state (set by frontend)
    selection = getattr(status, "selection", {}) or {}

    voices = selection.get("voices", [])

    play_intro = "intro" in voices
    play_detail = "detail" in voices
    play_artist = "artist" in voices

    logger.info(
        "🎛️ RADIO FLAGS | intro=%s detail=%s artist=%s",
        play_intro,
        play_detail,
        play_artist
    )

    logger.info(
        "🎛️ RADIO FLAGS | intro=%s detail=%s artist=%s",
        play_intro,
        play_detail,
        play_artist
    )

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

                if not VALID_BUCKETS_CACHE:
                    logger.error("❌ No valid radio buckets found")
                    return

            # ALWAYS assign first
            valid_buckets = VALID_BUCKETS_CACHE

            # 🎯 Apply genre filter (once, clean)
            if genre_filter and genre_filter != "ALL":
                logger.info("🎸 GENRE FILTER ACTIVE: %s", genre_filter)
                valid_buckets = [(d, g) for (d, g) in valid_buckets if g == genre_filter]

            # 🕒 Build station clock from filtered buckets
            genres = list({g for _, g in valid_buckets})
            random.shuffle(genres)

            logger.debug("🕒 Station clock genres: %s", genres)

            clock_index = 0

            valid_buckets = VALID_BUCKETS_CACHE
            # 🎯 Apply genre filter
            if genre_filter and genre_filter != "ALL":
                valid_buckets = [(d, g) for (d, g) in valid_buckets if g == genre_filter]

            # 🎯 Apply genre filter (for Nostalgia Radio station selection)
            if genre_filter and genre_filter != "ALL":
                valid_buckets = [(d, g) for (d, g) in valid_buckets if g == genre_filter]

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

            # Only apply filter if it doesn't shrink too much
            if len(filtered_block) >= MIN_TRACKS_PER_BLOCK:
                block_rows = filtered_block

            # SINGLE MODE → only keep one track
            if category == "single" and flags.mode != "all_radio":
                block_rows = block_rows[:1]

            total_ms = sum(row[0].duration_ms for row in block_rows if row[0].duration_ms)

            logger.info(
                "🎼 SET %d | %s / %s | %d tracks | %.1f min",
                set_number,
                decade,
                genre,
                len(block_rows),
                total_ms / 60000,
            )

            # ─────────────────────────────
            # PLAY BLOCK
            # ─────────────────────────────
            for idx, (track, artist, tr_rank, decade_obj, genre_obj) in enumerate(block_rows, start=1):

                if status.stopped:
                    logger.info("🛑 Radio mode stopped")
                    return

                # if status.cancel_requested:
                #     logger.info("⏭ Skip requested → moving to next track")
                #     status.cancel_requested = False
                #
                #     # 🔥 FORCE IMMEDIATE ADVANCE
                #     track_done_event.clear()
                #     continue

                rank = tr_rank.ranking

                flags.current_rank = rank
                status.current_rank = rank
                status.current_ranking_id = tr_rank.id

                logger.info(
                    "🎵 TRACK %d/%d | %s — %s",
                    idx,
                    len(block_rows),
                    track.track_name,
                    artist.artist_name
                )

                update_phase(
                    "track",
                    track_name=track.track_name,
                    artist_name=artist.artist_name,
                    current_rank=rank,

                    # 🔥 ADD THESE
                    intro=tr_rank.intro,
                    detail=track.detail,
                    artist_text=artist.artist_description,

                    context={
                        "mode": "all_radio",
                        "decade_slug": decade,
                        "genre_slug": genre,
                        "decade_name": decade_obj.decade_name,
                        "genre_name": genre_obj.genre_name,
                        "set_number": set_number,
                        "block_size": len(block_rows),
                        "block_position": idx,
                        "spotify_track_id": track.spotify_track_id,
                        "ranking_id": tr_rank.id,
                        "year": track.year_released,
                        "album_artwork": track.album_artwork,
                    },
                )

                recent_artists.append(artist.artist_name)

                if len(recent_artists) > MAX_RECENT_ARTISTS:
                    recent_artists.pop(0)


                # Ignore duplicate finish handling
                if tr_rank.id == last_played_ranking_id:
                    continue

                last_played_ranking_id = tr_rank.id

                logger.info(
                    "📡 RADIO publishing track to UI rank=%s intro=%s detail=%s artist=%s",
                    rank,
                    play_intro,
                    play_detail,
                    play_artist,
                )

                # ─────────────────────────────────────────────
                # 3. WAIT FOR TRACK TO FINISH
                # ─────────────────────────────────────────────
                # 🔥 Ensure we are waiting for a NEW signal
                track_done_event.clear()


                while True:
                    await track_done_event.wait()

                    # Only break if this was triggered AFTER clear()
                    if track_done_event.is_set():
                        break

    except asyncio.CancelledError:
        logger.info("⛔ ALL RADIO sequence cancelled")
        raise

    finally:
        flags.is_playing = False
        flags.stopped = True
        logger.info("📻 ALL RADIO mode stopped")
