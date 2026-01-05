# backend/services/play_policy.py
import asyncio

def compute_play_seconds(track) -> float:
    if track and getattr(track, "duration_ms", None):
        return track.duration_ms / 1000.0
    return 30.0  # final fallback


async def sleep_with_skip(skip_event, seconds: float) -> bool:
    try:
        await asyncio.wait_for(skip_event.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False
