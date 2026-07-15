from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


TimelineKind = Literal[
    "card",
    "black",
    "audio",
    "pause",
    "image",
]


@dataclass(frozen=True)
class TimelineItem:
    kind: TimelineKind
    name: str
    duration_seconds: float | None = None
    source: Path | None = None
    language_code: str | None = None


@dataclass(frozen=True)
class Timeline:
    items: list[TimelineItem]

    @property
    def known_duration_seconds(self) -> float:
        return sum(
            item.duration_seconds or 0.0
            for item in self.items
        )

    def describe(self) -> None:
        print("🎬 TopSpot40 Studio Timeline")
        print()

        for index, item in enumerate(self.items, start=1):
            duration = (
                f"{item.duration_seconds:.1f} sec"
                if item.duration_seconds is not None
                else "duration from media"
            )

            source = (
                f" | {item.source}"
                if item.source is not None
                else ""
            )

            print(
                f"{index:02d}. "
                f"{item.kind:<6} "
                f"{item.name:<24} "
                f"{duration}{source}"
            )

        print()
        print(
            "Known timeline duration:",
            f"{self.known_duration_seconds:.1f} seconds",
        )


def build_opening_timeline(
    *,
    logo: Path,
    languages: Path,
    title: Path,
    logo_seconds: float,
    language_seconds: float,
    title_seconds: float,
    black_seconds: float,
) -> Timeline:
    return Timeline(
        items=[
            TimelineItem(
                kind="card",
                name="TopSpot40 logo",
                duration_seconds=logo_seconds,
                source=logo,
            ),
            TimelineItem(
                kind="card",
                name="Language selection",
                duration_seconds=language_seconds,
                source=languages,
            ),
            TimelineItem(
                kind="card",
                name="Documentary title",
                duration_seconds=title_seconds,
                source=title,
            ),
            TimelineItem(
                kind="black",
                name="Black transition",
                duration_seconds=black_seconds,
            ),
        ]
    )
