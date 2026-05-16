from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from dataclasses import dataclass, field

@dataclass(frozen=True)
class TrackRef:
    track_id: int | str
    spotify_track_id: str | None
    rank: int
    track_name: str
    artist_name: str

@dataclass(frozen=True)
class PlaybackSelection:
    language: str
    voices: list[str]
    voicePlayMode: Literal["before", "over"]
    pauseMode: Literal["pause", "continuous"]
    languages: list[str] = field(default_factory=lambda: ["en"])
