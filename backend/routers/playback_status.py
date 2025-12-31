from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter

from backend.state.playback_state import status

router = APIRouter(prefix="/playback", tags=["Playback Status"])


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
