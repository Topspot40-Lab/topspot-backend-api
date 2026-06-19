# backend/state/playback_state.py
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Literal

import logging

logger = logging.getLogger(__name__)

Phase = Literal[
    "idle",
    "loading",
    "prelude",
    "set_intro",
    "liner",
    "intro",
    "detail",
    "artist",
    "track",
    "ended",
    "music",
]
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
#status = PlaybackStatus()

statuses: dict[str, PlaybackStatus] = {}
def get_status(user_id: str) -> PlaybackStatus:
    if user_id not in statuses:
        statuses[user_id] = PlaybackStatus()
    return statuses[user_id]


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _touch(user_id: str) -> None:
    s = get_status(user_id)
    s.last_action_ts = time.time()


def begin_track(user_id: str, track_duration_seconds: float) -> None:
    """
    Call this EXACTLY when a new Spotify track starts playing.
    This arms the per-track clock.
    """
    s = get_status(user_id)
    s.track_start_ts = time.time()
    s.track_elapsed_seconds = 0.0
    s.track_duration_seconds = track_duration_seconds
    s.track_percent_complete = 0.0
    _touch(user_id)


def update_track_clock(user_id: str) -> None:
    """
    Advances the per-track clock. Safe to call repeatedly.
    """
    s = get_status(user_id)
    if (
            s.is_playing
            and s.phase == "track"
            and s.track_start_ts > 0
    ):
        s.track_elapsed_seconds = time.time() - s.track_start_ts

        if s.track_duration_seconds > 0:
            s.track_percent_complete = min(
                100.0,
                (s.track_elapsed_seconds / s.track_duration_seconds) * 100.0,
            )


def update_phase(user_id: str, phase: Phase, **kwargs) -> None:
    #status.phase = phase
    s = get_status(user_id)
    s.phase = phase

    # Apply direct attributes first
    for k, v in kwargs.items():
        setattr(s, k, v)

    if "context" in kwargs:
        s.context = kwargs["context"]

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
        s.elapsed_seconds = float(elapsed)

    if duration is not None:
        s.duration_seconds = float(duration)

    if s.duration_seconds > 0:
        s.percent_complete = min(
            100.0,
            (s.elapsed_seconds / s.duration_seconds) * 100.0,
        )
    else:
        s.percent_complete = 0.0

    _touch(user_id)


def mark_playing(
        *,
        user_id: str,
        mode: Mode,
        language: str,
        context: Optional[dict[str, Any]] = None,
) -> None:
    s = get_status(user_id)
    s.is_playing = True
    s.is_paused = False
    s.stopped = False
    s.sequence_done = False
    s.mode = mode
    s.language = language
    if context is not None:
        s.context = context
    _touch(user_id)


def mark_paused(user_id: str) -> None:
    s = get_status(user_id)
    s.is_playing = False
    s.is_paused = True
    _touch(user_id)


def mark_stopped(user_id: str) -> None:
    s = get_status(user_id)
    s.is_playing = False
    s.is_paused = False
    s.stopped = True
    s.cancel_requested = False
    s.sequence_done = True
    s.phase = "idle"

    # Reset GLOBAL clocks
    s.elapsed_seconds = 0.0
    s.duration_seconds = 0.0
    s.percent_complete = 0.0

    # Reset TRACK clocks
    s.track_start_ts = 0.0
    s.track_elapsed_seconds = 0.0
    s.track_duration_seconds = 0.0
    s.track_percent_complete = 0.0

    _touch(user_id)
