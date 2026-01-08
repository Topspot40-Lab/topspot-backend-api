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
    Returns a single, consistent snapshot for the Car Mode poller.

    Example:
      {
        "phase": "track",
        "elapsedMs": 54000,
        "durationMs": 182000,
        "percentComplete": 0.2967,
        "track_name": "...",
        "artist_name": "...",
        "current_rank": 7,
        ...
      }
    """
    snap = asdict(status)

    # Keep backward-compatible keys your frontend may still expect
    elapsed_ms = int((snap.get("elapsed_seconds") or 0.0) * 1000)
    duration_ms = int((snap.get("duration_seconds") or 0.0) * 1000)

    return {
        **snap,
        "elapsedMs": elapsed_ms,
        "durationMs": duration_ms,
        "percentComplete": snap.get("percent_complete", 0.0),
    }

@router.post("/transfer/{device_id}")
async def transfer_playback(device_id: str):
    """
    Force Spotify playback onto a specific device.
    """
    sp = get_spotify_user_client()
    sp.transfer_playback(device_id=device_id, force_play=True)
    return {"ok": True, "device_id": device_id}
