# backend/routers/playback_status.py
from __future__ import annotations

from dataclasses import asdict
import time
import logging

from backend.state.playback_state import get_status as get_playback_status

from fastapi import APIRouter, Depends
from backend.services.spotify.spotify_auth_user import get_spotify_user_client
from backend.services.spotify.playback import (
    stop_spotify_playback
)

from backend.state.narration import narration_done_event, track_done_event
from backend.state.playback_runtime import bind_request_user, current_user_id

router = APIRouter(
    prefix="/playback",
    tags=["Playback Status"],
    dependencies=[Depends(bind_request_user)],
)
logger = logging.getLogger(__name__)


def update_track_clock(user_id: str):
    s = get_playback_status(user_id)
    if s.is_playing and s.phase == "track":
        if s.track_start_ts is None:
            s.track_elapsed_seconds = 0
        else:
            s.track_elapsed_seconds = time.time() - s.track_start_ts


@router.get("/devices")
async def get_devices():
    """
    List available Spotify playback devices for the user.
    """
    user_id = current_user_id()
    sp = await get_spotify_user_client(user_id)
    data = sp.devices()
    return {
        "devices": data.get("devices", [])
    }


@router.get("/status")
async def get_status():
    user_id = current_user_id()
    update_track_clock(user_id)

    s = get_playback_status(user_id)

    snap = asdict(s)

    ctx = snap.get("context") or s.context or {}
    ctx["ranking_id"] = snap.get("current_ranking_id")

    # logger.info(f"📡 STATUS CONTEXT OUT: {ctx}")

    phase = snap.get("phase")
    voice_style = ctx.get("voice_style")

    # 🔥 Bed track control:
    # Backend only marks bed active.
    # Frontend actually plays bed_audio_url.
    if phase in ("set_intro", "liner", "intro", "detail", "artist") and voice_style == "before":
        if not getattr(s, "bed_playing", False):
            s.bed_playing = True
            logger.debug("🎧 Bed marked active; frontend will play bed_audio_url")

    # Otherwise do nothing here; bed is stopped explicitly by narration-finished

    # Pick which clock to expose
    if snap["phase"] == "track":
        elapsed_ms = int((snap.get("track_elapsed_seconds") or 0.0) * 1000)
        duration_ms = int((snap.get("track_duration_seconds") or 0.0) * 1000)
    else:
        elapsed_ms = int((snap.get("elapsed_seconds") or 0.0) * 1000)
        duration_ms = int((snap.get("duration_seconds") or 0.0) * 1000)

    progress = elapsed_ms / duration_ms if duration_ms > 0 else 0.0

    return {
        "isPlaying": snap.get("is_playing", False),
        "isPaused": snap.get("is_paused", False),
        "stopped": snap.get("stopped", False),
        "phase": phase,

        "track_name": snap.get("track_name"),
        "artist_name": snap.get("artist_name"),
        "current_rank": snap.get("current_rank"),

        # 🔥 ADD THIS — NARRATION FIELDS
        "intro": snap.get("intro"),
        "detail": snap.get("detail"),
        "artist_text": snap.get("artist_text"),

        # ✅ ADD THIS
        "totalTracks": snap.get("total_tracks"),

        # ⭐ ADD THESE (THIS IS THE FIX)
        "setNumber": ctx.get("set_number"),
        "blockPosition": ctx.get("block_position"),
        "blockSize": ctx.get("block_size"),

        "decadeSlug": ctx.get("decade_slug"),
        "genreSlug": ctx.get("genre_slug"),
        "decadeName": ctx.get("decade_name"),
        "genreName": ctx.get("genre_name"),

        "elapsedMs": elapsed_ms,
        "durationMs": duration_ms,
        "progress": progress,

        "context": ctx,
    }


@router.post("/transfer/{device_id}")
async def transfer_playback(device_id: str):
    """
    Force Spotify playback onto a specific device.
    """
    user_id = current_user_id()
    sp = await get_spotify_user_client(user_id)
    sp.transfer_playback(device_id=device_id, force_play=True)
    return {"ok": True, "device_id": device_id}


@router.post("/narration-finished")
async def narration_finished():
    user_id = current_user_id()
    s = get_playback_status(user_id)
    ctx = s.context or {}
    voice_style = ctx.get("voice_style")

    logger.info(
        "🔔 Narration finished signal received (phase=%s, voice_style=%s)",
        s.phase,
        voice_style
    )

    # 🛑 NEW: ignore if paused
    if s.is_paused:
        logger.info("⏸️ Ignoring narration-finished because system is paused")
        return {"ok": True}

    last_narration_phase = getattr(s, "last_narration_phase", None)

    should_stop_bed = (
        voice_style == "before"
        and getattr(s, "bed_playing", False)
        and (
            not last_narration_phase
            or s.phase == last_narration_phase
        )
    )

    if should_stop_bed:
        logger.debug("🔉 Marking bed as stopped (frontend will fade out)")
        s.bed_playing = False
    else:
        logger.debug(
            "🔁 Keeping narration bed running | phase=%s last=%s bed_playing=%s",
            s.phase,
            last_narration_phase,
            getattr(s, "bed_playing", False),
        )

    # ✅ ONLY fire event if NOT paused
    narration_done_event(user_id).set()

    return {"ok": True}


#from backend.state.narration import track_done_event


@router.post("/track-finished")
async def track_finished():
    user_id = current_user_id()
    logger.info("🎵 Track finished signal received")
    event = track_done_event(user_id)
    logger.info(f"TRACK DONE EVENT ID (router): {id(event)}")

    s = get_playback_status(user_id)


    current_phase = getattr(s, "phase", None)
    current_ranking_id = getattr(s, "current_ranking_id", None)
    current_spotify_id = getattr(s, "spotify_track_id", None)
    track_start_ts = getattr(s, "track_start_ts", None)

    track_age = None
    if track_start_ts is not None:
        track_age = time.time() - track_start_ts

    logger.info(
        "🎵 track-finished check: phase=%s ranking_id=%s spotify=%s track_age=%s",
        current_phase,
        current_ranking_id,
        current_spotify_id,
        round(track_age, 2) if track_age is not None else None,
    )

    if current_phase != "track":
        logger.info("🚫 Ignoring track-finished because phase=%s", current_phase)
        return {"ok": True, "ignored": True, "reason": "not_in_track_phase"}

    if track_start_ts is None:
        logger.info("🚫 Ignoring track-finished because track clock has not started")
        return {"ok": True, "ignored": True, "reason": "track_clock_not_started"}

    if track_age < 10:
        logger.info("🚫 Ignoring track-finished because track_age=%.2fs is too young", track_age)
        return {"ok": True, "ignored": True, "reason": "track_too_young"}

    # Signal backend sequence loop that Spotify track is done
    event.set()

    return {"ok": True}
