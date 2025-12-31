# backend/services/radio_runtime.py
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import List, Tuple, Optional
import time

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
    safe_play,
)
from backend.services.spotify.playback import (
    play_spotify_track,
    stop_spotify_playback,
    set_device_volume,
)
from backend.services.play_policy import compute_play_seconds, sleep_with_skip
from backend.services.radio_render import render_header, box, clean_text, BOX_WIDTH
from backend.config import SPOTIFY_BED_TRACK_ID
from backend.state.skip import skip_event
from backend.state.playback_state import (
    status,
    update_phase,
    mark_playing,
)

logger = logging.getLogger(__name__)

# Single lock so intros/details/artist narrations never overlap
_narration_lock = asyncio.Lock()

logger.warning("✅ LOADED radio_runtime.py version=2025-12-25-FIX-01")

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


async def _run_voice_clip_with_skip(kind: str, bucket: str, key: str) -> bool:
    """
    Run safe_play(kind, bucket, key) cooperatively so we can honor pause/skip.
    Returns True if skip detected, else False.
    """
    play_task = asyncio.create_task(safe_play(kind, bucket, key))

    try:
        while not play_task.done():
            await _respect_user_controls()

            if skip_event.is_set():
                skip_event.clear()
                logger.info("⏭️ Skip detected during %s narration; cancelling clip.", kind)
                play_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await play_task
                return True

            await asyncio.sleep(0.1)

        await play_task
        return False

    except asyncio.CancelledError:
        play_task.cancel()
        with contextlib.suppress(Exception):
            await play_task
        raise


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
# Narration playback
# ─────────────────────────────────────────────
async def play_narrations(
    *,
    play_intro: bool,
    play_detail: bool,
    play_artist: bool,
    intro_jobs,
    detail_bucket,
    detail_key,
    artist_bucket,
    artist_key,
    lang: str = "en",
    mode: str = "decade_genre",
    rank: Optional[int] = None,
    track_name: Optional[str] = None,
    artist_name: Optional[str] = None,
    voice_style: str = "before",  # "before" | "over"
) -> None:
    """
    voice_style = "before": bed track for intro, then dry detail/artist
    voice_style = "over": assume main track already playing, duck volume and narrate over it

    IMPORTANT:
    - Narration progress (elapsed/duration/percent) is owned by safe_play().
    - radio_runtime does NOT run a narration heartbeat.
    """
    async with _narration_lock:
        try:
            # Clear stale skip
            if skip_event.is_set():
                logger.debug("🧹 Clearing stale skip_event before narration.")
                skip_event.clear()

            await _respect_user_controls()

            if skip_event.is_set():
                skip_event.clear()
                logger.info("⏭️ Skip already set — skipping narration phase.")
                return

            # ─────────────────────────────────────────────
            # MODE: VOICE OVER MAIN TRACK
            # ─────────────────────────────────────────────
            if voice_style == "over":
                ducked = False
                try:
                    any_voice = (
                        (play_intro and intro_jobs)
                        or (play_detail and detail_bucket and detail_key)
                        or (play_artist and artist_bucket and artist_key)
                    )
                    if any_voice:
                        with contextlib.suppress(Exception):
                            await set_device_volume(40)
                            ducked = True
                            logger.info("🔉 Ducking Spotify volume for voice-over.")

                    # INTRO over track
                    if play_intro and intro_jobs:
                        update_phase(
                            "intro",
                            current_rank=rank,
                            track_name=track_name,
                            artist_name=artist_name,
                            context=_phase_context(
                                lang=lang, mode=mode, rank=rank,
                                track_name=track_name, artist_name=artist_name
                            ),
                        )
                        for bkt, key, *_ in intro_jobs:
                            if skip_event.is_set():
                                skip_event.clear()
                                logger.info("⏭️ Skip hit — skipping remaining intro narration.")
                                break
                            logger.info("🎙️ Intro narration (over): %s/%s", bkt, key)
                            skipped = await _run_voice_clip_with_skip("intro", bkt, key)
                            if skipped:
                                return

                    # DETAIL over track
                    if play_detail and detail_bucket and detail_key:
                        if skip_event.is_set():
                            skip_event.clear()
                            logger.info("⏭️ Skip hit — skipping DETAIL narration (over).")
                            return
                        update_phase(
                            "detail",
                            current_rank=rank,
                            track_name=track_name,
                            artist_name=artist_name,
                            context=_phase_context(
                                lang=lang, mode=mode, rank=rank,
                                track_name=track_name, artist_name=artist_name
                            ),
                        )
                        logger.info("🎙️ Detail narration (over): %s/%s", detail_bucket, detail_key)
                        skipped = await _run_voice_clip_with_skip("detail", detail_bucket, detail_key)
                        if skipped:
                            return

                    # ARTIST over track
                    if play_artist and artist_bucket and artist_key:
                        if skip_event.is_set():
                            skip_event.clear()
                            logger.info("⏭️ Skip hit — skipping ARTIST narration (over).")
                            return
                        update_phase(
                            "artist",
                            current_rank=rank,
                            track_name=track_name,
                            artist_name=artist_name,
                            context=_phase_context(
                                lang=lang, mode=mode, rank=rank,
                                track_name=track_name, artist_name=artist_name
                            ),
                        )
                        logger.info("🎙️ Artist narration (over): %s/%s", artist_bucket, artist_key)
                        skipped = await _run_voice_clip_with_skip("artist", artist_bucket, artist_key)
                        if skipped:
                            return

                finally:
                    if ducked:
                        with contextlib.suppress(Exception):
                            await set_device_volume(100)
                        logger.info("🔊 Restored Spotify volume after voice-over narration.")

                return

            # ─────────────────────────────────────────────
            # MODE: VOICE BEFORE TRACK (DEFAULT)
            # ─────────────────────────────────────────────

            # INTRO (with bed)
            if play_intro and intro_jobs:
                update_phase(
                    "intro",
                    current_rank=rank,
                    track_name=track_name,
                    artist_name=artist_name,
                    context=_phase_context(
                        lang=lang, mode=mode, rank=rank,
                        track_name=track_name, artist_name=artist_name
                    ),
                )

                logger.info("🎧 Starting bed track BEFORE intro narration…")
                play_spotify_track(SPOTIFY_BED_TRACK_ID)

                try:
                    for bkt, key, *_ in intro_jobs:
                        if skip_event.is_set():
                            skip_event.clear()
                            logger.info("⏭️ Skip hit — skipping remaining intro.")
                            break
                        logger.info("🎙️ Intro narration: %s/%s", bkt, key)
                        skipped = await _run_voice_clip_with_skip("intro", bkt, key)
                        if skipped:
                            break
                finally:
                    logger.info("🔉 Stopping bed track after intro.")
                    with contextlib.suppress(Exception):
                        await stop_spotify_playback(fade_out_seconds=1.2)

            # DETAIL (dry)
            if play_detail and detail_bucket and detail_key:
                if skip_event.is_set():
                    skip_event.clear()
                    logger.info("⏭️ Skip hit — skipping DETAIL narration.")
                    return
                update_phase(
                    "detail",
                    current_rank=rank,
                    track_name=track_name,
                    artist_name=artist_name,
                    context=_phase_context(
                        lang=lang, mode=mode, rank=rank,
                        track_name=track_name, artist_name=artist_name
                    ),
                )
                logger.info("🎙️ Detail narration: %s/%s", detail_bucket, detail_key)
                skipped = await _run_voice_clip_with_skip("detail", detail_bucket, detail_key)
                if skipped:
                    return

            # ARTIST (dry)
            if play_artist and artist_bucket and artist_key:
                if skip_event.is_set():
                    skip_event.clear()
                    logger.info("⏭️ Skip hit — skipping ARTIST narration.")
                    return
                update_phase(
                    "artist",
                    current_rank=rank,
                    track_name=track_name,
                    artist_name=artist_name,
                    context=_phase_context(
                        lang=lang, mode=mode, rank=rank,
                        track_name=track_name, artist_name=artist_name
                    ),
                )
                logger.info("🎙️ Artist narration: %s/%s", artist_bucket, artist_key)
                skipped = await _run_voice_clip_with_skip("artist", artist_bucket, artist_key)
                if skipped:
                    return

        except asyncio.CancelledError:
            logger.info("⏹ Narration aborted.")
            with contextlib.suppress(Exception):
                await stop_spotify_playback(fade_out_seconds=1.0)
            raise
        except Exception as e:
            logger.warning("⚠️ play_narrations error: %s", e)


# ─────────────────────────────────────────────
# Track heartbeat (leave as you had it)
# ─────────────────────────────────────────────
async def _track_heartbeat(
    *,
    start_ts: float,
    total_secs: float,
    lang: str,
    mode: str,
    rank: Optional[int],
    track_name: Optional[str],
    artist_name: Optional[str],
) -> None:
    try:
        while True:
            elapsed = time.time() - start_ts

            status.elapsed_seconds = float(elapsed)
            status.duration_seconds = float(total_secs)

            # ✅ normalized 0.0 → 1.0
            status.percent_complete = float(elapsed / total_secs) if total_secs else 0.0

            update_phase(
                "track",
                current_rank=rank,
                track_name=track_name,
                artist_name=artist_name,
                context=_phase_context(
                    lang=lang,
                    mode=mode,
                    rank=rank,
                    track_name=track_name,
                    artist_name=artist_name,
                    elapsed_seconds=elapsed,
                    duration_seconds=total_secs,
                ),
            )

            if elapsed >= total_secs or (skip_event is not None and skip_event.is_set()):
                break

            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        return


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
            play_spotify_track(spotify_id)

        start_ts = time.time()
        heartbeat_task = asyncio.create_task(
            _track_heartbeat(
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
        update_phase(
            "track_finished",
            current_rank=rank_val,
            track_name=track_label,
            artist_name=artist_label,
            context=_phase_context(
                lang=lang,
                mode=mode,
                rank=rank_val,
                track_name=track_label,
                artist_name=artist_label,
                elapsed_seconds=play_secs,
                duration_seconds=play_secs,
            ),
        )

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
