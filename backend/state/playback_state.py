from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Literal

import logging

logger = logging.getLogger(__name__)

Phase = Literal["idle", "intro", "detail", "artist", "track", "ended", "music"]
Mode = Literal["decade_genre", "collection"]


# REMOVE this module-level var (it does NOT attach to status)
# requested_rank: int | None = None

@dataclass
class PlaybackStatus:
    # Core flags
    is_playing: bool = False
    is_paused: bool = False
    stopped: bool = True
    cancel_requested: bool = False
    sequence_done: bool = True

    bed_playing: bool = False

    # ✅ ADD this (attaches to status instance)
    requested_rank: int | None = None

    # Context
    language: str = "en"
    mode: Optional[Mode] = None
    context: dict[str, Any] = field(default_factory=dict)
    current_rank: Optional[int] = None
    current_ranking_id: int | None = None

    # ✅ ADD THIS
    total_tracks: int = 0

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

    # 🔥 ADD THESE
    intro: str | None = None
    detail: str | None = None
    artist_text: str | None = None

    # Timing
    last_action_ts: float = field(default_factory=time.time)

    # 🔵 RADIO tracking
    set_number: int = 0
    previous_bucket: tuple[str, str] | None = None


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

    # Apply direct attributes first
    for k, v in kwargs.items():
        setattr(status, k, v)

    status.context = kwargs.get("context", {})

    # 🎯 Global (show-level) progress handling
    elapsed = None
    duration = None

    # 1️⃣ Prefer explicit kwargs
    if "elapsed_seconds" in kwargs:
        elapsed = kwargs["elapsed_seconds"]

    if "duration_seconds" in kwargs:
        duration = kwargs["duration_seconds"]

    # 2️⃣ Fallback to context if present
    ctx = kwargs.get("context")
    if isinstance(ctx, dict):
        elapsed = ctx.get("elapsedSeconds", elapsed)
        duration = ctx.get("durationSeconds", duration)

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
