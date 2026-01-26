from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Literal

from backend.services.decade_genre_loader import load_decade_genre_rows
from backend.services.playback_ordering import order_rows_for_mode

# Legacy flags (still used by runtime helpers)
from backend.state.playback_flags import flags

from backend.services.radio_runtime import (
    log_header_and_texts,
    build_intro_jobs,
    narration_keys_for,
)

from backend.services.audio_urls import resolve_audio_ref, is_remote_audio

from backend.state.playback_state import (
    status,
    mark_playing,
    update_phase,
)

from backend.state.narration import narration_done_event


logger = logging.getLogger(__name__)


def _extract_bucket_key(job):
    """
    Supports:
      - tuple/list: (bucket, key, ...)
      - dict: {"bucket": "...", "key": "..."} (or object_path)
      - object: .bucket / .key / .object_path
    """
    if job is None:
        return None, None

    if isinstance(job, (tuple, list)) and len(job) >= 2:
        return job[0], job[1]

    if isinstance(job, dict):
        return job.get("bucket"), job.get("key") or job.get("object_path")

    bucket = getattr(job, "bucket", None)
    key = getattr(job, "key", None) or getattr(job, "object_path", None)
    return bucket, key


async def publish_narration_phase(
    phase: Literal["intro", "detail", "artist"],
    *,
    track,
    artist,
    rank: int,
    decade: str,
    genre: str,
    bucket: str,
    key: str,
    voice_style: Literal["before", "over"],
):
    audio_url = resolve_audio_ref(bucket, key)

    update_phase(
        phase,
        track_name=track.track_name,
        artist_name=artist.artist_name,
        current_rank=int(rank),
        context={
            "lang": getattr(status, "language", None),
            "mode": "decade_genre",
            "decade": decade,
            "genre": genre,
            "rank": int(rank),
            "track_name": track.track_name,
            "artist_name": artist.artist_name,
            "bucket": bucket,
            "key": key,
            "audio_url": audio_url,
            "source": "remote" if is_remote_audio() else "local",
            "voice_style": voice_style,
        },
    )

    logger.info("🎙 Published %s frame: %s", phase.upper(), audio_url)

    # Same behavior as collections:
    # - "before": backend waits until frontend signals narration finished
    # - "over": do not wait (narration overlaps track)
    if voice_style == "before":
        narration_done_event.clear()
        await narration_done_event.wait()


# ─────────────────────────────────────────────
# PAUSE / CANCEL HELPERS
# ─────────────────────────────────────────────
async def _wait_if_paused() -> None:
    """Cooperative pause loop driven by playback_state.status."""
    while getattr(status, "is_paused", False):
        await asyncio.sleep(0.25)


def _is_cancelled_or_stopped() -> bool:
    """
    Unified cancel / stop check.

    NOTE:
    We must check BOTH playback_state (new)
    and playback_flags (legacy) because runtime helpers
    still rely on flags during Option A.
    """
    if getattr(status, "stopped", False):
        return True
    if getattr(status, "cancel_requested", False):
        return True

    if getattr(flags, "stopped", False):
        return True
    if getattr(flags, "cancel_requested", False):
        return True

    return False


# ─────────────────────────────────────────────
# MAIN SEQUENCE ENGINE (DECADE / GENRE)
# Publisher-style (like collections):
# Publishes intro/detail/artist/track frames for ONE rank, then returns.
# Frontend controls actual playback and Next/Prev navigation.
# ─────────────────────────────────────────────
async def run_decade_genre_sequence(
    *,
    decade: str,
    genre: str,
    start_rank: int,
    end_rank: int,
    mode: Literal["count_up", "count_down", "random"],
    tts_language: str,
    play_intro: bool,
    play_detail: bool,
    play_artist_description: bool,
    play_track: bool,
    voice_style: Literal["before", "over"] = "before",
) -> None:
    logger.info(
        "🎧 Starting sequence (publisher): %s/%s %d-%d mode=%s lang=%s voice=%s",
        decade,
        genre,
        start_rank,
        end_rank,
        mode,
        tts_language,
        voice_style,
    )

    # ─────────── RESET PLAYBACK STATE ───────────
    status.stopped = False
    status.cancel_requested = False
    status.language = tts_language

    # 🔥 HARD RESET PHASE STATE
    status.phase = None
    status.bed_playing = False

    # 🔁 TEMP: Reset legacy flags (critical)
    flags.is_playing = True
    flags.stopped = False
    flags.cancel_requested = False
    flags.current_rank = start_rank
    flags.mode = "decade_genre"

    mark_playing(
        mode="decade_genre",
        language=tts_language,
        context={
            "decade": decade,
            "genre": genre,
            "start_rank": start_rank,
            "end_rank": end_rank,
            "order": mode,
        },
    )

    update_phase(
        "loading",
        current_rank=start_rank,
        track_name="",
        artist_name="",
        context={
            "lang": tts_language,
            "mode": "decade_genre",
            "decade": decade,
            "genre": genre,
        },
    )

    try:
        # ─────────── LOAD TRACK ROWS ───────────
        logger.info(
            "🧨 Loading rows decade=%r genre=%r start=%d end=%d",
            decade,
            genre,
            start_rank,
            end_rank,
        )

        t0 = time.time()
        try:
            rows = await asyncio.wait_for(
                asyncio.to_thread(
                    load_decade_genre_rows,
                    decade=decade,
                    genre=genre,
                    start_rank=start_rank,
                    end_rank=end_rank,
                ),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.error("⏱️ load_decade_genre_rows timeout (>30s)")
            return

        logger.info("📦 Loaded %d rows in %.2fs", len(rows), time.time() - t0)

        if not rows:
            logger.error("❌ NO TRACK ROWS — decade=%s genre=%s", decade, genre)
            return

        if _is_cancelled_or_stopped():
            logger.info("🛑 Cancelled/stopped before publish")
            return

        await _wait_if_paused()

        # Order rows in the same way the old engine did
        rows = order_rows_for_mode(rows, mode)

        # Pick ONE row to publish (publisher behavior)
        # - count_up: first row in ordered list
        # - count_down: first row after ordering (ordering already reversed)
        # - random: shuffle already handled by order_rows_for_mode; if not, do it here
        if mode == "random":
            random.shuffle(rows)

        track, artist, tr_rank, decade_obj, genre_obj = rows[0]
        rank = int(tr_rank.ranking)
        flags.current_rank = rank

        logger.info("▶ Publish Rank #%02d: %s — %s", rank, track.track_name, artist.artist_name)

        update_phase(
            "prelude",
            is_playing=True,
            current_rank=rank,
            track_name=track.track_name,
            artist_name=artist.artist_name,
            context={
                "lang": tts_language,
                "mode": "decade_genre",
                "rank": rank,
                "track_name": track.track_name,
                "artist_name": artist.artist_name,
                "decade": decade,
                "genre": genre,
                "voice_style": voice_style,
            },
        )

        # ─────────── NARRATION KEYS ───────────
        log_header_and_texts(
            lang=tts_language,
            track=track,
            artist=artist,
            tr_rows=[(tr_rank, decade_obj.decade_name, genre_obj.genre_name)],
        )

        intro_jobs = build_intro_jobs(
            lang=tts_language,
            tr_rows=[(tr_rank, decade_obj.decade_name, genre_obj.genre_name)],
        )

        detail_bucket, detail_key, artist_bucket, artist_key = narration_keys_for(
            lang=tts_language,
            track=track,
            artist=artist,
        )

        # ───────── INTRO (publish) ─────────
        if play_intro and intro_jobs:
            ib, ik = _extract_bucket_key(intro_jobs[0])
            if ib and ik:
                await publish_narration_phase(
                    "intro",
                    track=track,
                    artist=artist,
                    rank=rank,
                    decade=decade,
                    genre=genre,
                    bucket=ib,
                    key=ik,
                    voice_style=voice_style,
                )

        # ───────── DETAIL (publish) ─────────
        if play_detail and detail_bucket and detail_key:
            await publish_narration_phase(
                "detail",
                track=track,
                artist=artist,
                rank=rank,
                decade=decade,
                genre=genre,
                bucket=detail_bucket,
                key=detail_key,
                voice_style=voice_style,
            )

        # ───────── ARTIST (publish) ─────────
        if play_artist_description and artist_bucket and artist_key:
            await publish_narration_phase(
                "artist",
                track=track,
                artist=artist,
                rank=rank,
                decade=decade,
                genre=genre,
                bucket=artist_bucket,
                key=artist_key,
                voice_style=voice_style,
            )

        # ───────── TRACK (publish spotify id) ─────────
        if play_track and track.spotify_track_id:
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
                },
            )
            logger.info("🎯 PUBLISHED track frame rank=%s spotify=%s", rank, track.spotify_track_id)

        logger.info("✅ Decade/genre publish finished (single-rank).")

    except asyncio.CancelledError:
        logger.info("⛔ Sequence task cancelled")
        raise
    except Exception:
        logger.exception("⚠️ Sequence error for %s/%s", decade, genre)
    finally:
        # reset legacy flags (keep your existing behavior)
        flags.is_playing = False
        flags.stopped = True
        logger.debug("🧹 Playback flags reset for %s/%s", decade, genre)
