"""Canonical Stage 7 renderer for the shared documentary visual program."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.studio.factory.production_execution import ProductionExecution
from backend.studio.render.build_image_sequence import (
    ImageEntry,
    concatenate_videos,
    render_image,
)
from backend.studio.render.motion_controller import MotionKind
from backend.studio.stations.build_storyboard import save_json_atomic
from backend.studio.visuals.generate_images import generate_image


VISUAL_RENDER_STATION = "visual_render"
VISUAL_MASTER_ARTIFACT = "shared.visual_master"
STORYBOARD_ARTIFACT = "shared.storyboard_and_scene_plan"
RESEARCH_ARTIFACT = "shared.approved_visuals"
PROVENANCE_ARTIFACT = "shared.provenance_report"
QUALITY_ARTIFACT = "shared.quality_report"

ImageGenerator = Callable[[str], bytes]
MasterRenderer = Callable[[list[ImageEntry], Path], None]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verified_digest(execution: ProductionExecution, artifact_id: str, station: str) -> str:
    execution.require_verified_completed(station=station, artifact_id=artifact_id)
    verification = execution.record(artifact_id).get("verification")
    digest = verification.get("sha256") if isinstance(verification, dict) else None
    if not isinstance(digest, str):
        raise RuntimeError(f"Verified {artifact_id} is missing its SHA-256 digest")
    return digest


def _input_digests(execution: ProductionExecution) -> dict[str, str]:
    return {
        STORYBOARD_ARTIFACT: _verified_digest(execution, STORYBOARD_ARTIFACT, "visual_planning"),
        RESEARCH_ARTIFACT: _verified_digest(execution, RESEARCH_ARTIFACT, "visual_research"),
        PROVENANCE_ARTIFACT: _verified_digest(execution, PROVENANCE_ARTIFACT, "visual_quality"),
        QUALITY_ARTIFACT: _verified_digest(execution, QUALITY_ARTIFACT, "visual_quality"),
    }


def _input_sidecar(execution: ProductionExecution) -> Path:
    return execution.factory_root / "shared" / "visual_master.inputs.json"


def _sidecar_matches(path: Path, digests: dict[str, str]) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("input_sha256") == digests


def _require_quality_passes(execution: ProductionExecution) -> None:
    path = execution.output_path(station="visual_quality", artifact_id=QUALITY_ARTIFACT)
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict) or summary.get("passed") is not True:
        raise RuntimeError("Visual rendering is blocked until visual QC passes")


def _approved_candidates(research: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    approved: dict[tuple[int, int], dict[str, Any]] = {}
    for shot in research.get("shots", []):
        if not isinstance(shot, dict):
            continue
        decision = shot.get("decision")
        if not isinstance(decision, dict):
            continue
        state = decision.get("state")
        if state == "needs_review":
            raise RuntimeError("Visual rendering is blocked by unresolved historical review")
        if state != "approved_historical":
            continue
        selected = decision.get("selected_candidate_id")
        record = next((item for item in shot.get("candidates", []) if isinstance(item, dict) and item.get("candidate_id") == selected and item.get("disposition") == "approved"), None)
        if record is None:
            raise ValueError("Approved historical selection has no approved candidate record")
        approved[(int(shot["scene_number"]), int(shot["shot_number"]))] = record
    return approved


def _asset_for_shot(*, work_root: Path, scene: dict[str, Any], shot: dict[str, Any], approved: dict[tuple[int, int], dict[str, Any]], generator: ImageGenerator) -> tuple[Path, str]:
    key = (int(scene["scene_number"]), int(shot["shot_number"]))
    assets = work_root / "factory" / "render_assets"
    if key in approved:
        record = approved[key]
        retrieval = record.get("retrieval")
        candidate = record.get("candidate")
        if not isinstance(retrieval, dict) or not isinstance(candidate, dict):
            raise ValueError("Approved historical record lacks cached retrieval metadata")
        sha256 = str(retrieval.get("sha256") or "")
        source = work_root / "factory" / "cache" / "historical" / "objects" / f"{sha256}.bin"
        if not source.is_file() or _digest(source) != sha256:
            raise FileNotFoundError("Approved historical image is unavailable from the verified cache")
        suffix = ".jpg" if candidate.get("mime_type") == "image/jpeg" else ".png"
        destination = assets / "historical" / f"{key[1]:03d}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source, destination)
        return destination, "historical"
    destination = assets / "generated" / f"{key[1]:03d}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.stat().st_size == 0:
        prompt = str(shot.get("prompt") or shot.get("visual_intent") or "").strip()
        if not prompt:
            raise ValueError(f"Shot {key[1]} has no generated fallback prompt")
        content = generator(prompt)
        if not content:
            raise RuntimeError("Generated fallback visual was empty")
        destination.write_bytes(content)
    return destination, "AI"


def render_master(entries: list[ImageEntry], output: Path) -> None:
    """Adapt the established Ken-Burns renderer without legacy path access."""
    if not entries:
        raise ValueError("Visual master requires at least one storyboard shot")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        parts: list[Path] = []
        previous: MotionKind | None = None
        for index, entry in enumerate(entries, start=1):
            part = Path(temporary) / f"{index:03d}.mp4"
            _, previous = render_image(source=entry.image, destination=part, duration=entry.duration, shot_number=entry.shot_number, source_kind=entry.source_kind, scene_text=entry.scene_text, previous_kind=previous)
            parts.append(part)
        concatenate_videos(parts, output)


def run_visual_render(production: Any, execution: ProductionExecution, *, image_generator: ImageGenerator = generate_image, renderer: MasterRenderer = render_master) -> bool:
    """Create one verified 1920x1080/30fps visual master for all editions."""
    execution.resume()
    digests = _input_digests(execution)
    _require_quality_passes(execution)
    if VISUAL_MASTER_ARTIFACT not in execution.pending_artifacts(station=VISUAL_RENDER_STATION):
        execution.require_verified_completed(station=VISUAL_RENDER_STATION, artifact_id=VISUAL_MASTER_ARTIFACT)
        if _sidecar_matches(_input_sidecar(execution), digests):
            return False
        execution.requeue_artifact(station=VISUAL_RENDER_STATION, artifact_id=VISUAL_MASTER_ARTIFACT, reason="Visual-render input digest changed or is missing")
    session = production.session
    session.start_station(VISUAL_RENDER_STATION)
    claimed = False
    try:
        output = execution.start_artifact(station=VISUAL_RENDER_STATION, artifact_id=VISUAL_MASTER_ARTIFACT)
        claimed = True
        storyboard_path = execution.output_path(station="visual_planning", artifact_id=STORYBOARD_ARTIFACT)
        research_path = execution.output_path(station="visual_research", artifact_id=RESEARCH_ARTIFACT)
        storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
        approved = _approved_candidates(json.loads(research_path.read_text(encoding="utf-8")))
        entries: list[ImageEntry] = []
        for scene in storyboard.get("scenes", []):
            for shot in scene.get("visual_shots", []):
                image, source_kind = _asset_for_shot(work_root=Path(production.work_root), scene=scene, shot=shot, approved=approved, generator=image_generator)
                entries.append(ImageEntry(shot_number=int(shot["shot_number"]), image=image, duration=float(shot["estimated_seconds"]), source_kind=source_kind, scene_text=str(shot.get("visual_intent") or scene.get("visual_intent") or "")))
        renderer(entries, output)
        execution.complete_artifact(station=VISUAL_RENDER_STATION, artifact_id=VISUAL_MASTER_ARTIFACT)
        save_json_atomic(_input_sidecar(execution), {"version": 1, "input_sha256": digests})
    except Exception as exc:
        if claimed:
            try:
                execution.fail_artifact(station=VISUAL_RENDER_STATION, artifact_id=VISUAL_MASTER_ARTIFACT, error_summary=f"{type(exc).__name__}: {exc}")
            except RuntimeError:
                pass
        session.finish_station(VISUAL_RENDER_STATION, success=False)
        raise
    session.metric("visual_shots", len(entries), station=VISUAL_RENDER_STATION)
    session.metric("resolution", "1920x1080", station=VISUAL_RENDER_STATION)
    session.metric("fps", 30, station=VISUAL_RENDER_STATION)
    session.artifact(VISUAL_MASTER_ARTIFACT, output, station=VISUAL_RENDER_STATION)
    session.finish_station(VISUAL_RENDER_STATION, success=True)
    execution.require_verified_completed(station=VISUAL_RENDER_STATION, artifact_id=VISUAL_MASTER_ARTIFACT)
    return True
