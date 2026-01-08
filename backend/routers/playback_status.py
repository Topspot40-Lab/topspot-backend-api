from __future__ import annotations

from dataclasses import asdict

from backend.state.playback_state import status

from fastapi import APIRouter
from backend.services.spotify.spotify_auth_user import get_spotify_user_client

router = APIRouter(prefix="/playback", tags=["Playback Status"])

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
    """
    Returns a clean, normalized snapshot for the Car Mode poller.
    Single source of truth. No duplicate fields.
    """

    snap = asdict(status)

    elapsed_ms = int((snap.get("elapsed_seconds") or 0.0) * 1000)
    duration_ms = int((snap.get("duration_seconds") or 0.0) * 1000)

    progress = (
        elapsed_ms / duration_ms
        if duration_ms > 0
        else 0.0
    )

    return {
        # playback state
        "isPlaying": snap.get("is_playing", False),
        "isPaused": snap.get("is_paused", False),
        "stopped": snap.get("stopped", False),
        "phase": snap.get("phase"),

        # track metadata
        "trackName": snap.get("track_name"),
        "artistName": snap.get("artist_name"),
        "currentRank": snap.get("current_rank"),

        # timing (ONLY these)
        "elapsedMs": elapsed_ms,
        "durationMs": duration_ms,
        "progress": progress,
    }


@router.post("/transfer/{device_id}")
async def transfer_playback(device_id: str):
    """
    Force Spotify playback onto a specific device.
    """
    sp = get_spotify_user_client()
    sp.transfer_playback(device_id=device_id, force_play=True)
    return {"ok": True, "device_id": device_id}
