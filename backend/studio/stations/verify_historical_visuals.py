"""Validate shared historical-visual research and record its provenance."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from backend.studio.factory.production_execution import ProductionExecution
from backend.studio.stations.build_storyboard import save_json_atomic


VISUAL_QUALITY_STATION = "visual_quality"
VISUAL_RESEARCH_ARTIFACT = "shared.approved_visuals"
PROVENANCE_ARTIFACT = "shared.provenance_report"
QUALITY_ARTIFACT = "shared.quality_report"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _completed_digest(execution: ProductionExecution, artifact_id: str) -> str:
    verification = execution.record(artifact_id).get("verification")
    digest = verification.get("sha256") if isinstance(verification, dict) else None
    if not isinstance(digest, str):
        raise RuntimeError(f"Verified {artifact_id} is missing its SHA-256 digest")
    return digest


def _records(package: dict[str, Any]) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    for shot in package.get("shots", []):
        if not isinstance(shot, dict):
            continue
        for record in shot.get("candidates", []):
            if isinstance(record, dict):
                yield shot, record


def build_provenance_report(package: dict[str, Any], *, research_sha256: str) -> dict[str, Any]:
    """Create an auditable, deterministic report for selected historical media."""
    entries: list[dict[str, Any]] = []
    for shot, record in _records(package):
        if record.get("disposition") != "approved":
            continue
        candidate = record.get("candidate")
        retrieval = record.get("retrieval")
        if not isinstance(candidate, dict) or not isinstance(retrieval, dict):
            raise ValueError("Approved historical candidate is missing provenance")
        required = (
            "provider",
            "page_url",
            "original_url",
            "license_name",
            "license_url",
            "creator",
            "credit",
        )
        if any(not isinstance(candidate.get(key), str) or not candidate[key].strip() for key in required):
            raise ValueError("Approved historical candidate has incomplete provenance")
        sha256 = retrieval.get("sha256")
        if not isinstance(sha256, str) or not sha256:
            raise ValueError("Approved historical candidate is missing content digest")
        entries.append({
            "scene_number": shot.get("scene_number"),
            "shot_number": shot.get("shot_number"),
            "candidate_id": record.get("candidate_id"),
            "provider": candidate["provider"],
            "page_url": candidate["page_url"],
            "original_url": candidate["original_url"],
            "creator": candidate["creator"],
            "credit": candidate["credit"],
            "license_name": candidate["license_name"],
            "license_url": candidate["license_url"],
            "content_sha256": sha256,
        })
    entries.sort(key=lambda entry: (entry["scene_number"], entry["shot_number"], str(entry["candidate_id"])))
    return {
        "version": 1,
        "production_slug": package.get("production_slug"),
        "visual_research_sha256": research_sha256,
        "entries": entries,
        "summary": {"approved_historical_assets": len(entries)},
    }


def build_quality_report(package: dict[str, Any], *, research_sha256: str, provenance_sha256: str) -> dict[str, Any]:
    """Summarize deterministic visual-research outcomes for operator review."""
    decisions: dict[str, int] = {}
    total_shots = 0
    for shot in package.get("shots", []):
        if not isinstance(shot, dict):
            continue
        total_shots += 1
        decision = shot.get("decision")
        state = decision.get("state") if isinstance(decision, dict) else "invalid"
        decisions[str(state)] = decisions.get(str(state), 0) + 1
    return {
        "version": 1,
        "production_slug": package.get("production_slug"),
        "visual_research_sha256": research_sha256,
        "provenance_sha256": provenance_sha256,
        "summary": {
            "total_shots": total_shots,
            "decision_counts": dict(sorted(decisions.items())),
            "passed": decisions.get("needs_review", 0) == 0,
        },
    }


def _report_matches(path: Path, *, research_sha256: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("visual_research_sha256") == research_sha256


def run_visual_quality(production: Any, execution: ProductionExecution) -> bool:
    """Produce contract-owned provenance and QC reports from verified research."""
    execution.resume()
    execution.require_verified_completed(
        station="visual_research", artifact_id=VISUAL_RESEARCH_ARTIFACT
    )
    research_sha256 = _completed_digest(execution, VISUAL_RESEARCH_ARTIFACT)
    artifact_ids = (PROVENANCE_ARTIFACT, QUALITY_ARTIFACT)
    pending = set(execution.pending_artifacts(station=VISUAL_QUALITY_STATION))
    if not pending:
        paths = [execution.output_path(station=VISUAL_QUALITY_STATION, artifact_id=artifact_id) for artifact_id in artifact_ids]
        if all(_report_matches(path, research_sha256=research_sha256) for path in paths):
            return False
        for artifact_id in artifact_ids:
            execution.requeue_artifact(station=VISUAL_QUALITY_STATION, artifact_id=artifact_id, reason="Visual research input digest changed or is missing")
        pending = set(artifact_ids)
    elif pending != set(artifact_ids):
        for artifact_id in artifact_ids:
            if artifact_id not in pending:
                execution.requeue_artifact(
                    station=VISUAL_QUALITY_STATION,
                    artifact_id=artifact_id,
                    reason="Visual-quality report set was incomplete",
                )
        pending = set(artifact_ids)

    session = production.session
    session.start_station(VISUAL_QUALITY_STATION)
    claimed: list[str] = []
    try:
        research_path = execution.output_path(station="visual_research", artifact_id=VISUAL_RESEARCH_ARTIFACT)
        package = json.loads(research_path.read_text(encoding="utf-8"))
        if not isinstance(package, dict):
            raise ValueError("Historical visual research must be a JSON object")
        provenance_path = execution.output_path(station=VISUAL_QUALITY_STATION, artifact_id=PROVENANCE_ARTIFACT)
        quality_path = execution.output_path(station=VISUAL_QUALITY_STATION, artifact_id=QUALITY_ARTIFACT)
        for artifact_id in artifact_ids:
            execution.start_artifact(station=VISUAL_QUALITY_STATION, artifact_id=artifact_id)
            claimed.append(artifact_id)
        provenance = build_provenance_report(package, research_sha256=research_sha256)
        save_json_atomic(provenance_path, provenance)
        provenance_sha256 = _sha256(provenance_path)
        quality = build_quality_report(package, research_sha256=research_sha256, provenance_sha256=provenance_sha256)
        save_json_atomic(quality_path, quality)
        for artifact_id in claimed:
            execution.complete_artifact(station=VISUAL_QUALITY_STATION, artifact_id=artifact_id)
    except Exception as exc:
        for artifact_id in claimed:
            try:
                execution.fail_artifact(station=VISUAL_QUALITY_STATION, artifact_id=artifact_id, error_summary=f"{type(exc).__name__}: {exc}")
            except RuntimeError:
                pass
        session.finish_station(VISUAL_QUALITY_STATION, success=False)
        raise
    session.metric("approved_historical_assets", provenance["summary"]["approved_historical_assets"], station=VISUAL_QUALITY_STATION)
    session.metric("visual_quality_passed", quality["summary"]["passed"], station=VISUAL_QUALITY_STATION)
    for artifact_id, path in ((PROVENANCE_ARTIFACT, provenance_path), (QUALITY_ARTIFACT, quality_path)):
        session.artifact(artifact_id, path, station=VISUAL_QUALITY_STATION)
        execution.require_verified_completed(station=VISUAL_QUALITY_STATION, artifact_id=artifact_id)
    session.finish_station(VISUAL_QUALITY_STATION, success=True)
    return True
