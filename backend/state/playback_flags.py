# backend/state/playback_flags.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional
import time

from backend.state.playback_runtime import RuntimeObjectProxy


@dataclass
class PlaybackFlags:
    # Core playback state
    is_playing: bool = False
    is_paused: bool = False
    stopped: bool = True
    cancel_requested: bool = False

    # Context & metadata
    language: Literal["en", "es", "ptbr", "pt-BR"] = "en"
    mode: Optional[str] = None
    context: Optional[dict] = None
    current_rank: Optional[int] = None
    last_action_ts: float = 0.0

    # Car Mode UI helpers
    elapsed_seconds: float = 0.0
    duration_seconds: float = 0.0
    percent_complete: float = 0.0

    # Phase + labels
    current_phase: str = "idle"
    track_name: str = ""
    artist_name: str = ""


#flags = PlaybackFlags()
flags_by_user: dict[str, PlaybackFlags] = {}
def get_flags(user_id: str) -> PlaybackFlags:
    if user_id not in flags_by_user:
        flags_by_user[user_id] = PlaybackFlags()
    return flags_by_user[user_id]

flags = RuntimeObjectProxy("flags")


def touch():
    flags.last_action_ts = time.time()


def reset_for_single_track():
    flags.is_playing = True
    flags.is_paused = False
    flags.stopped = False
    flags.cancel_requested = False
