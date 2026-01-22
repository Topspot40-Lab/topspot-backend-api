from __future__ import annotations

from dataclasses import asdict
import time
import logging

from backend.state.playback_state import status

from fastapi import APIRouter
from backend.services.spotify.spotify_auth_user import get_spotify_user_client
from backend.services.spotify.playback import (
    play_spotify_track,
    stop_spotify_playback,
    ensure_active_device,   # ✅ add
)


from backend.config import SPOTIFY_BED_TRACK_ID


router = APIRouter(prefix="/playback", tags=["Playback Status"])
logger = logging.getLogger(__name__)

_last_bed_phase: str | None = None


def update_track_clock():
    if status.is_playing and status.phase == "track":
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
    ctx = snap.get("context") or {}

    phase = snap.get("phase")
    voice_style = ctx.get("voice_style")

    # 🔥 Bed track control: ONLY for narration phases in BEFORE mode
    global _last_bed_phase

    if phase in ("intro", "detail", "artist") and voice_style == "before":
        if not getattr(status, "bed_playing", False):
            logger.info("🎧 Starting narration bed track (BEFORE mode)")
            try:
                await ensure_active_device()  # ✅ add
                await play_spotify_track(SPOTIFY_BED_TRACK_ID)  # ✅ keep
                status.bed_playing = True
            except Exception as e:
                logger.warning("⚠️ Could not start bed track: %s", e)

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

        "trackName": snap.get("track_name"),
        "artistName": snap.get("artist_name"),
        "currentRank": snap.get("current_rank"),

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
    from backend.state.playback_state import status
    from backend.state.skip import skip_event
    global _last_bed_phase

    ctx = status.context or {}
    voice_style = ctx.get("voice_style")

    logger.info(
        "🔔 Narration finished signal received (phase=%s, voice_style=%s)",
        status.phase,
        voice_style
    )

    if voice_style == "before" and getattr(status, "bed_playing", False):
        logger.info("🔉 Stopping narration bed track (BEFORE mode)")
        try:
            await stop_spotify_playback(fade_out_seconds=1.2)
        except Exception as e:
            logger.warning("⚠️ Failed to stop bed track: %s", e)

        status.bed_playing = False
        _last_bed_phase = None   # 🔥 reset latch

    skip_event.set()
    return {"ok": True}

