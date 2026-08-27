"""Canonical shared opening renderer using the established opening-card pipeline."""
from __future__ import annotations

import json
import hashlib

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.studio.factory.production_execution import ProductionExecution
from backend.studio.render.build_opening import concatenate_videos, render_black, render_card
from backend.studio.stations.build_opening_cards import (
    build_languages_card,
    build_logo_card,
)
from backend.studio.studio_config import BLACK_SECONDS, LANGUAGE_SECONDS, LOGO_SECONDS
from backend.studio.timeline import build_opening_timeline

VISUAL_RENDER_STATION = "visual_render"
OPENING_VIDEO_ARTIFACT = "shared.opening_video"
OPENING_RENDER_VERSION = "hook-opening-v2"
OpeningRenderer = Callable[[Any, Path], None]


def render_opening(production: Any, output: Path) -> None:
    """Render the legacy three-card opening into the canonical shared output."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        cards = (work / "01_logo.png", work / "02_languages.png")
        build_logo_card(production, cards[0])
        build_languages_card(production, cards[1])
        timeline = build_opening_timeline(
            logo=cards[0], languages=cards[1],
            logo_seconds=LOGO_SECONDS, language_seconds=LANGUAGE_SECONDS,
            black_seconds=BLACK_SECONDS,
        )
        parts: list[Path] = []
        for index, item in enumerate(timeline.items, start=1):
            part = work / f"{index:02d}.mp4"
            if item.kind == "card":
                if item.source is None:
                    raise RuntimeError(f"Timeline card has no source: {item.name}")
                render_card(source=item.source, destination=part, duration=item.duration_seconds or 0.0)
            elif item.kind == "black":
                render_black(destination=part, duration=item.duration_seconds or 0.0)
            else:
                raise RuntimeError(f"Unsupported opening timeline item: {item.kind}")
            parts.append(part)
        concatenate_videos(parts, output)


def run_opening_render(
    production: Any,
    execution: ProductionExecution,
    *,
    renderer: OpeningRenderer | None = None,
) -> bool:
    execution.resume()
    sidecar = execution.factory_root / "shared" / "opening.inputs.json"
    expected = {"version": OPENING_RENDER_VERSION}
    if OPENING_VIDEO_ARTIFACT not in execution.pending_artifacts(station=VISUAL_RENDER_STATION):
        execution.require_verified_completed(station=VISUAL_RENDER_STATION, artifact_id=OPENING_VIDEO_ARTIFACT)
        try:
            if json.loads(sidecar.read_text(encoding="utf-8")) == expected:
                return False
        except (OSError, json.JSONDecodeError):
            pass
        execution.requeue_artifact(station=VISUAL_RENDER_STATION, artifact_id=OPENING_VIDEO_ARTIFACT, reason="Opening render version changed or is missing")
    session = production.session
    session.start_station(VISUAL_RENDER_STATION)
    claimed = False
    try:
        output = execution.start_artifact(station=VISUAL_RENDER_STATION, artifact_id=OPENING_VIDEO_ARTIFACT)
        claimed = True
        (renderer or render_opening)(production, output)
        execution.complete_artifact(station=VISUAL_RENDER_STATION, artifact_id=OPENING_VIDEO_ARTIFACT)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps(expected) + "\n", encoding="utf-8")
    except Exception as exc:
        if claimed:
            try:
                execution.fail_artifact(station=VISUAL_RENDER_STATION, artifact_id=OPENING_VIDEO_ARTIFACT, error_summary=f"{type(exc).__name__}: {exc}")
            except RuntimeError:
                pass
        session.finish_station(VISUAL_RENDER_STATION, success=False)
        raise
    session.artifact(OPENING_VIDEO_ARTIFACT, output, station=VISUAL_RENDER_STATION)
    session.finish_station(VISUAL_RENDER_STATION, success=True)
    execution.require_verified_completed(station=VISUAL_RENDER_STATION, artifact_id=OPENING_VIDEO_ARTIFACT)
    return True