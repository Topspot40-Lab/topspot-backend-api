"""Canonical station owning only shared/visual_research.json."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.studio.factory.production_execution import ProductionExecution
from backend.studio.historical.models import HistoricalImageCandidate
from backend.studio.historical.providers.base import HistoricalImageProvider
from backend.studio.historical.search import default_providers
from backend.studio.stations.build_storyboard import save_json_atomic
from backend.studio.visuals.historical_visual_package import (
    BoundedSearchSettings,
    HistoricalCache,
    HistoricalVisualPackageBuilder,
)

VISUAL_RESEARCH_STATION = "visual_research"
VISUAL_RESEARCH_ARTIFACT = "shared.approved_visuals"
STORYBOARD_ARTIFACT = "shared.storyboard_and_scene_plan"
MAX_LIVE_IMAGE_BYTES = 25 * 1024 * 1024


class LiveImageTooLargeError(ValueError):
    """Raised when a live image exceeds the configured retrieval limit."""


def _recorded_storyboard_digest(path: Path) -> str | None:
    """Return the input digest embedded in a completed visual-research package."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    digest = payload.get("storyboard_sha256") if isinstance(payload, dict) else None
    return digest if isinstance(digest, str) else None


def retrieve_live_bytes(
    candidate: HistoricalImageCandidate, *, max_bytes: int = MAX_LIVE_IMAGE_BYTES
) -> bytes:
    """Lazy production retriever; all tests inject a local replacement."""
    import requests

    response = requests.get(candidate.original_url, timeout=(10, 120), headers={"User-Agent": "TopSpot40-Studio/1.0"})
    try:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length is not None and content_length.strip().isdigit() and int(content_length) > max_bytes:
            raise LiveImageTooLargeError(
                f"Historical image Content-Length exceeds {max_bytes} byte limit"
            )
        content = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            if len(content) + len(chunk) > max_bytes:
                raise LiveImageTooLargeError(
                    f"Historical image stream exceeds {max_bytes} byte limit"
                )
            content.extend(chunk)
        return bytes(content)
    finally:
        response.close()


def run_visual_research(
    production: Any,
    execution: ProductionExecution,
    *,
    providers: list[HistoricalImageProvider] | None = None,
    retriever: Callable[[HistoricalImageCandidate], bytes] = retrieve_live_bytes,
    settings: BoundedSearchSettings = BoundedSearchSettings(),
) -> bool:
    """Complete visual research without touching visual-quality artifacts."""
    execution.resume()
    execution.require_verified_completed(
        station="visual_planning", artifact_id=STORYBOARD_ARTIFACT
    )
    storyboard_verification = execution.record(STORYBOARD_ARTIFACT).get("verification")
    storyboard_digest = (
        storyboard_verification.get("sha256")
        if isinstance(storyboard_verification, dict)
        else None
    )
    if not isinstance(storyboard_digest, str):
        raise RuntimeError("Verified storyboard is missing its SHA-256 digest")
    if VISUAL_RESEARCH_ARTIFACT not in execution.pending_artifacts(station=VISUAL_RESEARCH_STATION):
        execution.require_verified_completed(station=VISUAL_RESEARCH_STATION, artifact_id=VISUAL_RESEARCH_ARTIFACT)
        research_path = execution.output_path(
            station=VISUAL_RESEARCH_STATION, artifact_id=VISUAL_RESEARCH_ARTIFACT
        )
        if _recorded_storyboard_digest(research_path) == storyboard_digest:
            return False
        execution.requeue_artifact(
            station=VISUAL_RESEARCH_STATION,
            artifact_id=VISUAL_RESEARCH_ARTIFACT,
            reason="Storyboard input digest changed or is missing",
        )
    session = production.session
    session.start_station(VISUAL_RESEARCH_STATION)
    claimed = False
    try:
        output = execution.start_artifact(station=VISUAL_RESEARCH_STATION, artifact_id=VISUAL_RESEARCH_ARTIFACT)
        claimed = True
        storyboard_path = execution.output_path(station="visual_planning", artifact_id=STORYBOARD_ARTIFACT)
        storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
        builder = HistoricalVisualPackageBuilder(
            providers=list(default_providers() if providers is None else providers),
            retriever=retriever,
            cache=HistoricalCache(Path(production.work_root) / "factory" / "cache" / "historical"),
            settings=settings,
        )
        payload = builder.build(storyboard)
        payload["storyboard_sha256"] = storyboard_digest
        output.parent.mkdir(parents=True, exist_ok=True)
        save_json_atomic(output, payload)
        execution.complete_artifact(station=VISUAL_RESEARCH_STATION, artifact_id=VISUAL_RESEARCH_ARTIFACT)
    except Exception:
        if claimed:
            try:
                execution.fail_artifact(station=VISUAL_RESEARCH_STATION, artifact_id=VISUAL_RESEARCH_ARTIFACT, error_summary="Historical visual research failed")
            except RuntimeError:
                pass
        session.finish_station(VISUAL_RESEARCH_STATION, success=False)
        raise
    for name, value in payload["summary"].items():
        session.metric(name, value, station=VISUAL_RESEARCH_STATION)
    session.artifact(VISUAL_RESEARCH_ARTIFACT, output, station=VISUAL_RESEARCH_STATION)
    session.finish_station(VISUAL_RESEARCH_STATION, success=True)
    execution.require_verified_completed(station=VISUAL_RESEARCH_STATION, artifact_id=VISUAL_RESEARCH_ARTIFACT)
    return True
