"""Canonical Stage 8 localized narration preparation."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.studio.audio.build_language_masters import safe_language
from backend.studio.factory.production_contract import SUPPORTED_LANGUAGE_CODES
from backend.studio.factory.production_execution import ProductionExecution
from backend.studio.stations.build_storyboard import save_json_atomic

VISUAL_MASTER_ARTIFACT = "shared.visual_master"
VISUAL_RENDER_STATION = "visual_render"
SEGMENTS = ("intro", "story", "outro")
Retriever = Callable[[Any, str, str], bytes]


def narration_station(language: str) -> str:
    return f"narration_{language}"


def narration_artifact(language: str, segment: str) -> str:
    return f"delivery.{language}.narration.{segment}"


def default_retriever(production: Any, language: str, segment: str) -> bytes:
    """Retrieve existing TTS assets without rewriting legacy source files."""
    locale = production.documentary.language(language)
    bucket = str(getattr(locale, "tts_bucket", "") or "")
    key = str(getattr(locale, "tts_key", "") or "") if segment == "story" else f"youtube/{segment}.mp3"
    if not bucket or not key:
        raise RuntimeError(f"Missing {segment} narration source for {language}")
    from backend.services.supabase_client import supabase
    data = supabase.storage.from_(bucket).download(key)
    if not data:
        raise RuntimeError(f"Empty {segment} narration source for {language}")
    return bytes(data)


def _sidecar(execution: ProductionExecution, language: str) -> Path:
    return execution.factory_root / "delivery" / safe_language(language) / "narration.inputs.json"


def _hashes(sources: dict[str, bytes]) -> dict[str, str]:
    return {segment: hashlib.sha256(value).hexdigest() for segment, value in sources.items()}


def _stored_hashes(path: Path) -> dict[str, str] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("source_sha256")
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and set(value) == set(SEGMENTS) else None


def run_localized_narration(production: Any, execution: ProductionExecution, *, retriever: Retriever = default_retriever) -> bool:
    """Prepare all contract-owned narration tracks with language-local resume."""
    execution.resume()
    execution.require_verified_completed(station=VISUAL_RENDER_STATION, artifact_id=VISUAL_MASTER_ARTIFACT)
    changed = False
    for language in SUPPORTED_LANGUAGE_CODES:
        station = narration_station(language)
        pending_artifacts = set(
            execution.pending_artifacts(station=station)
        )

        if not pending_artifacts:
            for segment in SEGMENTS:
                execution.require_verified_completed(
                    station=station,
                    artifact_id=narration_artifact(language, segment),
                )
            continue

        sources = {
            segment: retriever(production, language, segment)
            for segment in SEGMENTS
        }
        if any(not value for value in sources.values()):
            raise RuntimeError(f"Empty narration source for {language}")

        hashes = _hashes(sources)
        recorded_hashes = _stored_hashes(_sidecar(execution, language))
        if recorded_hashes != hashes:
            for segment in SEGMENTS:
                artifact = narration_artifact(language, segment)
                if artifact not in pending_artifacts:
                    execution.requeue_artifact(
                        station=station,
                        artifact_id=artifact,
                        reason="Narration source digest changed or is missing",
                    )
            pending_segments = set(SEGMENTS)
        else:
            pending_segments = {
                artifact.rsplit(".", maxsplit=1)[-1]
                for artifact in pending_artifacts
            }
        session = production.session
        session.start_station(station)
        claimed: list[str] = []
        try:
            for segment in SEGMENTS:
                if segment not in pending_segments:
                    continue
                artifact = narration_artifact(language, segment)
                path = execution.start_artifact(station=station, artifact_id=artifact)
                claimed.append(artifact)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(sources[segment])
                execution.complete_artifact(station=station, artifact_id=artifact)
            save_json_atomic(_sidecar(execution, language), {"version": 1, "source_sha256": hashes})
        except Exception as exc:
            for artifact in claimed:
                try:
                    execution.fail_artifact(station=station, artifact_id=artifact, error_summary=f"{type(exc).__name__}: {exc}")
                except RuntimeError:
                    pass
            session.finish_station(station, success=False)
            raise
        for segment in SEGMENTS:
            artifact = narration_artifact(language, segment)
            path = execution.output_path(station=station, artifact_id=artifact)
            session.artifact(artifact, path, station=station)
            execution.require_verified_completed(station=station, artifact_id=artifact)
        session.metric("narration_tracks", len(SEGMENTS), station=station)
        session.finish_station(station, success=True)
        changed = True
    return changed
