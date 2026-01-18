from __future__ import annotations

from dataclasses import asdict
import time

from backend.state.playback_state import status

from fastapi import APIRouter
from backend.services.spotify.spotify_auth_user import get_spotify_user_client

router = APIRouter(prefix="/playback", tags=["Playback Status"])

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


# router = APIRouter(prefix="/playback", tags=["Playback Status"])


@router.get("/status")
async def get_status():
    update_track_clock()

    snap = asdict(status)

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
        "phase": snap.get("phase"),

        "trackName": snap.get("track_name"),
        "artistName": snap.get("artist_name"),
        "currentRank": snap.get("current_rank"),

        "elapsedMs": elapsed_ms,
        "durationMs": duration_ms,
        "progress": progress,

        # 🔥 this is what feeds your poller
        "context": snap.get("context"),
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
    """
    Called by frontend when narration audio ends in BEFORE mode.
    This releases safe_play() so Spotify can start.
    """
    from backend.state.playback_state import status, update_phase

    if status.phase in ("intro", "detail", "artist", "collections_intro"):
        update_phase("music", is_playing=False)

    return {"ok": True, "phase": status.phase}


@router.post("/next")
async def next_track():
    from backend.routers.playback_control import cancel_for_skip
    cancel_for_skip()
    return {"ok": True, "action": "next"}


@router.post("/prev")
async def prev_track():
    from backend.routers.playback_control import cancel_for_skip
    cancel_for_skip()
    return {"ok": True, "action": "prev"}

