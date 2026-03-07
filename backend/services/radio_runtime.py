# backend/services/radio_runtime.py
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import List, Tuple, Optional
import time

logger = logging.getLogger(__name__)   # ✅ DEFINE LOGGER FIRST

from sqlmodel import Session as SQLSession

from backend.database import engine
from backend.services.localization import get_localized_texts
from backend.services.playback_helpers import (
    bucket_for,
    key_for,
    build_intro_filename,
    build_collection_intro_filename,
    build_detail_filename,
    build_artist_filename,
)

from backend.services.spotify.playback import (
    play_spotify_track,
    stop_spotify_playback,
    set_device_volume,
)
from backend.services.play_policy import compute_play_seconds, sleep_with_skip
from backend.services.radio_render import render_header, box, clean_text, BOX_WIDTH
from backend.state.skip import skip_event
from backend.state.playback_state import (
    status,
    update_phase,
    mark_playing,
)
from backend.services.radio.heartbeat import track_heartbeat
from backend.services.radio.narration import play_narrations


_play_task: asyncio.Task | None = None

def start_playback_sequence(coro) -> None:
    """
    Register the main playback coroutine so skip_to_next / skip_to_prev can cancel it.
    """
    global _play_task

    # Cancel any previous running sequence
    if _play_task and not _play_task.done():
        logger.info("🔁 Cancelling old playback task")
        _play_task.cancel()

    _play_task = asyncio.create_task(coro)
    logger.info("▶️ Playback sequence started")


logger.warning("🧨 RADIO RUNTIME LOADED – TRACK HEARTBEAT FIX ACTIVE 🧨")


# ─────────────────────────────────────────────
# Safety guard: ensure Spotify volume is sane
# ─────────────────────────────────────────────
async def _ensure_volume_ok() -> None:
    """Safety guard so Spotify is never left muted."""
    with contextlib.suppress(Exception):
        await set_device_volume(100)


from backend.state.playback_flags import flags


async def _respect_user_controls() -> None:
    """
    Central cooperative checkpoint for pause / stop.
    IMPORTANT: Do NOT abort if a new playback session is actively running.
    """
    while status.is_paused:
        await asyncio.sleep(0.25)

    # Only stop if no active playback is intended
    if status.stopped and not flags.is_playing:
        logger.info("🛑 Playback stopped by user.")
        raise asyncio.CancelledError("Playback stopped")


def _phase_context(
    *,
    lang: str | None = None,
    mode: str | None = None,
    rank: Optional[int] = None,
    track_name: Optional[str] = None,
    artist_name: Optional[str] = None,
    elapsed_seconds: Optional[float] = None,
    duration_seconds: Optional[float] = None,
) -> dict:
    ctx: dict = {}
    if lang is not None:
        ctx["lang"] = lang
    if mode is not None:
        ctx["mode"] = mode
    if rank is not None:
        ctx["rank"] = rank
    if track_name is not None:
        ctx["track_name"] = track_name
    if artist_name is not None:
        ctx["artist_name"] = artist_name
    if elapsed_seconds is not None:
        ctx["elapsed_seconds"] = float(elapsed_seconds)
    if duration_seconds is not None:
        ctx["duration_seconds"] = float(duration_seconds)
    return ctx


# ─────────────────────────────────────────────
# Collection logging helpers
# ─────────────────────────────────────────────
def log_collection_header_and_texts(
    *,
    collection,
    ctr,
    track,
    artist,
    intro: str | None = None,
    detail_text: str | None = None,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    header_lines = [
        "┌" + "─" * (BOX_WIDTH - 2),
        "│ TopSpot — Collection",
        f"│  Name : {getattr(collection, 'name', collection.slug)}",
        f"│  Slug : {collection.slug}",
        f"│  Rank : #{ctr.ranking:02d}",
        f"│  Track: {track.track_name} — {getattr(artist, 'artist_name', '')}",
        f"│  Spotify Track ID: {getattr(track, 'spotify_track_id', '') or '—'}",
        "└" + "─" * (BOX_WIDTH - 2),
    ]
    logger.info("\n%s", "\n".join(header_lines))

    intro_text = clean_text(intro or getattr(ctr, "intro", None))
    if intro_text:
        logger.info(box("INTRO", intro_text, width=BOX_WIDTH))

    detail_text2 = clean_text(detail_text or getattr(track, "detail", None))
    if detail_text2:
        logger.info(box("DETAIL", detail_text2, width=BOX_WIDTH))

    artist_text = clean_text(getattr(artist, "artist_description", None))
    if artist_text:
        logger.info(box("ARTIST", artist_text, width=BOX_WIDTH))

    return intro_text, detail_text2, artist_text


def collection_intro_jobs(*, lang: str, collection_slug: str, rank: int):
    if lang != "en":
        return []

    bucket = bucket_for(lang, "collections_intro")
    filename = build_collection_intro_filename(collection_slug, rank)
    key = key_for("collections_intro", filename)

    if not (bucket and key):
        return []

    return [(bucket, key, collection_slug, collection_slug, rank)]


# ─────────────────────────────────────────────
# Decade/Genre header logging
# ─────────────────────────────────────────────
def log_header_and_texts(
    *,
    lang: str,
    track,
    artist,
    tr_rows,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    header_text = render_header(
        track_name=track.track_name,
        artist_name=getattr(artist, "artist_name", None)
        or getattr(artist, "artist_name", "Unknown Artist"),
        track_id=track.spotify_track_id,
        lang=lang,
        tr_rows=tr_rows or [],
    )
    logger.debug("\n%s", header_text)

    intro_text_loc: str | None = None
    detail_text_loc: str | None = None

    if tr_rows:
        first_rk = tr_rows[0][0]
        with SQLSession(engine) as s_loc:
            intro_text_loc, detail_text_loc = get_localized_texts(
                s_loc, lang, first_rk, track
            )

    logger.debug(
        "[intro:%s %s] [detail:%s %s]",
        lang,
        "OK" if intro_text_loc else "FALLBACK",
        lang,
        "OK" if detail_text_loc else "FALLBACK/EN",
    )

    if intro_text_loc:
        logger.debug(box("INTRO", clean_text(intro_text_loc), width=BOX_WIDTH))

    detail_text = (
        clean_text(detail_text_loc)
        if detail_text_loc
        else clean_text(getattr(track, "detail", None))
    )
    if detail_text:
        logger.debug(box("DETAIL", detail_text, width=BOX_WIDTH))

    artist_text = clean_text(getattr(artist, "artist_description", None))
    if artist_text:
        logger.debug(box("ARTIST", artist_text, width=BOX_WIDTH))

    return intro_text_loc, detail_text, artist_text


# ─────────────────────────────────────────────
# Narration asset builders
# ─────────────────────────────────────────────
def build_intro_jobs(*, lang: str, tr_rows) -> List[Tuple[str, str, str, str, int]]:
    jobs: List[Tuple[str, str, str, str, int]] = []
    if not tr_rows:
        return jobs

    for tr, decade_name, genre_name in tr_rows:
        intro_filename = build_intro_filename(decade_name, genre_name, tr.ranking)
        bucket = bucket_for(lang, "intro")
        key = key_for("intro", intro_filename)
        if bucket and key:
            jobs.append((bucket, key, decade_name, genre_name, tr.ranking))

    return jobs


def narration_keys_for(*, lang: str, track, artist):
    detail_filename = build_detail_filename(track.spotify_track_id)
    artist_filename = build_artist_filename(artist.spotify_artist_id)

    detail_key = key_for("detail", detail_filename) if detail_filename else None
    artist_key = key_for("artist", artist_filename) if artist_filename else None

    detail_bucket = bucket_for(lang, "detail") if detail_key else None
    artist_bucket = bucket_for(lang, "artist") if artist_key else None

    return detail_bucket, detail_key, artist_bucket, artist_key


# ─────────────────────────────────────────────
# Track playback with skip / pause / stop
# ─────────────────────────────────────────────
async def play_track_with_skip(
    track,
    *,
    lang: str = "en",
    mode: str = "decade_genre",
    rank: Optional[int] = None,
    track_name: Optional[str] = None,
    artist_name: Optional[str] = None,
    full_flag: bool = True,
    already_playing: bool = False,
) -> bool:
    heartbeat_task: Optional[asyncio.Task] = None

    try:
        rank_val = rank if rank is not None else getattr(track, "ranking", None)
        track_label = track_name or getattr(track, "track_name", None)
        artist_label = artist_name or getattr(track, "artist_name", None)
        spotify_id = getattr(track, "spotify_track_id", None)

        if not spotify_id:
            logger.warning("⚠️ No spotify_track_id — skipping track playback.")
            return True

        mark_playing(mode=mode, language=lang)

        play_secs = compute_play_seconds(track)

        status.elapsed_seconds = 0.0
        status.duration_seconds = float(play_secs)
        status.percent_complete = 0.0

        update_phase(
            "track",
            current_rank=rank_val,
            track_name=track_label,
            artist_name=artist_label,
            context=_phase_context(
                lang=lang,
                mode=mode,
                rank=rank_val,
                track_name=track_label,
                artist_name=artist_label,
                elapsed_seconds=0.0,
                duration_seconds=play_secs,
            ),
        )

        await _respect_user_controls()

        logger.info(
            "🎵 Now playing track: %s (%s) for %ss (full=%s, already_playing=%s)",
            track_label or "Unknown Track",
            spotify_id,
            play_secs,
            full_flag,
            already_playing,
        )

        if not already_playing:
            await _ensure_volume_ok()
            await play_spotify_track(spotify_id)

        start_ts = time.time()
        heartbeat_task = asyncio.create_task(
            track_heartbeat(
                start_ts=start_ts,
                total_secs=play_secs,
                lang=lang,
                mode=mode,
                rank=rank_val,
                track_name=track_label,
                artist_name=artist_label,
            )
        )

        skipped = await sleep_with_skip(skip_event, play_secs)

        if skipped:
            logger.info("⏭️ Track skipped → fading out Spotify.")
            with contextlib.suppress(Exception):
                await stop_spotify_playback(fade_out_seconds=1.5)
            return True

        if already_playing:
            logger.info("🔇 Track finished (over-style) — stopping Spotify cleanly.")
            with contextlib.suppress(Exception):
                await stop_spotify_playback(fade_out_seconds=1.0)

        logger.info("✅ Track finished normally.")

        # Do NOT mark_stopped() here.
        # The sequence runner (the thing looping ranks) should decide when playback is finished.
        return False


    except asyncio.CancelledError:
        logger.info("🛑 Track playback cancelled.")
        with contextlib.suppress(Exception):
            await stop_spotify_playback(fade_out_seconds=1.5)
        return True
    except Exception as e:
        logger.warning("⚠️ play_track_with_skip error: %s", e)
        with contextlib.suppress(Exception):
            await stop_spotify_playback(fade_out_seconds=1.5)
        return True
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await heartbeat_task


def skip_to_next() -> None:
    """
    Signals the currently running narration/track loop to skip.
    Does NOT start new sequences. The active sequence runner (if any)
    will advance to the next rank on its own.
    """
    logger.info("⏭ skip_to_next requested")
    skip_event.set()


def skip_to_prev() -> None:
    """
    Signals skip. True 'prev' requires the sequence runner to support jumping.
    For now, treat as skip (same behavior as next).
    """
    logger.info("⏮ skip_to_prev requested")
    skip_event.set()
