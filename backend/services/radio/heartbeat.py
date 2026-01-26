# backend/services/radio/heartbeat.py
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from backend.state.skip import skip_event
from backend.state.playback_state import status, update_phase

logger = logging.getLogger(__name__)


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


async def track_heartbeat(
    *,
    start_ts: float,
    total_secs: float,
    lang: str,
    mode: str,
    rank: Optional[int],
    track_name: Optional[str],
    artist_name: Optional[str],
) -> None:
    """
    Updates playback_state.status elapsed/duration/percent during TRACK phase.
    On completion (elapsed >= total_secs OR skip_event set), pushes phase to idle and marks stopped.
    """
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
                logger.info("🏁 Track heartbeat complete")

                status.elapsed_seconds = float(total_secs)
                status.duration_seconds = float(total_secs)
                status.percent_complete = 1.0 if total_secs else 0.0

                status.is_playing = False
                status.is_paused = False
                status.stopped = True

                update_phase(
                    "idle",
                    current_rank=rank,
                    track_name=track_name,
                    artist_name=artist_name,
                    context=_phase_context(
                        lang=lang,
                        mode=mode,
                        rank=rank,
                        track_name=track_name,
                        artist_name=artist_name,
                        elapsed_seconds=total_secs,
                        duration_seconds=total_secs,
                    ),
                )
                return

            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        return
