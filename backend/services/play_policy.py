# backend/services/play_policy.py
import asyncio

def compute_play_seconds(track) -> float:
    # fallback: play 30 seconds
    return 30.0

async def sleep_with_skip(skip_event, seconds: float) -> bool:
    try:
        await asyncio.wait_for(skip_event.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False
