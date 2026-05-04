from __future__ import annotations

from dataclasses import asdict
import time
import logging

from backend.state.playback_state import status

from fastapi import APIRouter
from backend.services.spotify.spotify_auth_user import get_spotify_user_client
from backend.services.spotify.playback import (
    stop_spotify_playback
)

from backend.state.narration import narration_done_event

router = APIRouter(prefix="/playback", tags=["Playback Status"])
logger = logging.getLogger(__name__)


def update_track_clock():
    if status.is_playing and status.phase == "track":
        if status.track_start_ts is None:
            status.track_elapsed_seconds = 0
        else:
            status.track_elapsed_seconds = time.time() - status.track_start_ts


@router.get("/devices")
async def get_devices():
    """
    List available Spotify playback devices for the user.
    """
    sp = get_spotify_user_client()
    data = sp.devices()
    return {
        "devices": data.get("devices", [])
    }


@router.get("/status")
async def get_status():
    update_track_clock()

    snap = asdict(status)

    ctx = snap.get("context") or status.context or {}
    ctx["ranking_id"] = snap.get("current_ranking_id")

    # logger.info(f"📡 STATUS CONTEXT OUT: {ctx}")

    phase = snap.get("phase")
    voice_style = ctx.get("voice_style")

    # 🔥 Bed track control:
    # Backend only marks bed active.
    # Frontend actually plays bed_audio_url.
    if phase in ("set_intro", "liner", "intro", "detail", "artist") and voice_style == "before":
        if not getattr(status, "bed_playing", False):
            status.bed_playing = True
            logger.info("🎧 Bed marked active; frontend will play bed_audio_url")

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
    sp = get_spotify_user_client()
    sp.transfer_playback(device_id=device_id, force_play=True)
    return {"ok": True, "device_id": device_id}


@router.post("/narration-finished")
async def narration_finished():
    ctx = status.context or {}
    voice_style = ctx.get("voice_style")

    logger.info(
        "🔔 Narration finished signal received (phase=%s, voice_style=%s)",
        status.phase,
        voice_style
    )

    # 🛑 NEW: ignore if paused
    if status.is_paused:
        logger.info("⏸️ Ignoring narration-finished because system is paused")
        return {"ok": True}

    last_narration_phase = getattr(status, "last_narration_phase", None)

    should_stop_bed = (
        voice_style == "before"
        and getattr(status, "bed_playing", False)
        and (
            not last_narration_phase
            or status.phase == last_narration_phase
        )
    )

    if should_stop_bed:
        logger.info("🔉 Marking bed as stopped (frontend will fade out)")
        status.bed_playing = False
    else:
        logger.info(
            "🔁 Keeping narration bed running | phase=%s last=%s bed_playing=%s",
            status.phase,
            last_narration_phase,
            getattr(status, "bed_playing", False),
        )

    # ✅ ONLY fire event if NOT paused
    narration_done_event.set()

    return {"ok": True}


from backend.state.narration import track_done_event


@router.post("/track-finished")
async def track_finished():
    logger.info("🎵 Track finished signal received")
    logger.info(f"TRACK DONE EVENT ID (router): {id(track_done_event)}")

    # Signal backend sequence loop that Spotify track is done
    track_done_event.set()

    return {"ok": True}
