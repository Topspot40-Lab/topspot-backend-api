from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Literal

Phase = Literal["idle", "intro", "detail", "artist", "track", "ended", "music"]
Mode  = Literal["decade_genre", "collection"]


@dataclass
class PlaybackStatus:
    # Core flags
    is_playing: bool = False
    is_paused: bool = False
    stopped: bool = True
    cancel_requested: bool = False
    sequence_done: bool = True

    # Context
    language: str = "en"
    mode: Optional[Mode] = None
    context: dict[str, Any] = field(default_factory=dict)
    current_rank: Optional[int] = None

    # 🔵 GLOBAL show progress
    elapsed_seconds: float = 0.0
    duration_seconds: float = 0.0
    percent_complete: float = 0.0

    # 🟢 TRACK progress
    track_start_ts: float = 0.0
    track_elapsed_seconds: float = 0.0
    track_duration_seconds: float = 0.0
    track_percent_complete: float = 0.0

    # Phase + labels
    phase: Phase = "idle"
    track_name: str = ""
    artist_name: str = ""

    # Timing
    last_action_ts: float = field(default_factory=time.time)


# 🔴 SINGLE GLOBAL INSTANCE
status = PlaybackStatus()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _touch() -> None:
    status.last_action_ts = time.time()


def begin_track(track_duration_seconds: float) -> None:
    """
    Call this EXACTLY when a new Spotify track starts playing.
    This arms the per-track clock.
    """
    status.track_start_ts = time.time()
    status.track_elapsed_seconds = 0.0
    status.track_duration_seconds = track_duration_seconds
    status.track_percent_complete = 0.0
    _touch()


def update_track_clock() -> None:
    """
    Advances the per-track clock. Safe to call repeatedly.
    """
    if (
        status.is_playing
        and status.phase == "track"
        and status.track_start_ts > 0
    ):
        status.track_elapsed_seconds = time.time() - status.track_start_ts

        if status.track_duration_seconds > 0:
            status.track_percent_complete = min(
                100.0,
                (status.track_elapsed_seconds / status.track_duration_seconds) * 100.0,
            )


def update_phase(phase: Phase, **kwargs) -> None:
    status.phase = phase

    for k, v in kwargs.items():
        setattr(status, k, v)

    # Global (show-level) progress handling
    ctx = kwargs.get("context")
    if isinstance(ctx, dict):
        elapsed = ctx.get("elapsedSeconds")
        duration = ctx.get("durationSeconds")

        if elapsed is not None:
            status.elapsed_seconds = float(elapsed)

        if duration is not None:
            status.duration_seconds = float(duration)

        if status.duration_seconds > 0:
            status.percent_complete = min(
                100.0,
                (status.elapsed_seconds / status.duration_seconds) * 100.0,
            )
        else:
            status.percent_complete = 0.0

    _touch()


def mark_playing(
    *,
    mode: Mode,
    language: str,
    context: Optional[dict[str, Any]] = None,
) -> None:
    status.is_playing = True
    status.is_paused = False
    status.stopped = False
    status.sequence_done = False
    status.mode = mode
    status.language = language
    if context is not None:
        status.context = context
    _touch()


def mark_paused() -> None:
    status.is_playing = False
    status.is_paused = True
    _touch()


def mark_stopped() -> None:
    status.is_playing = False
    status.is_paused = False
    status.stopped = True
    status.cancel_requested = False
    status.sequence_done = True
    status.phase = "idle"

    # Reset GLOBAL clocks
    status.elapsed_seconds = 0.0
    status.duration_seconds = 0.0
    status.percent_complete = 0.0

    # Reset TRACK clocks
    status.track_start_ts = 0.0
    status.track_elapsed_seconds = 0.0
    status.track_duration_seconds = 0.0
    status.track_percent_complete = 0.0

    _touch()
