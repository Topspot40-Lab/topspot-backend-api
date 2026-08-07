"""One verified, language-neutral hook image per documentary."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from backend.studio.factory.production_execution import ProductionExecution
from backend.studio.stations.build_storyboard import save_json_atomic
from backend.studio.visuals.generate_images import generate_image

HOOK_VISUAL_ARTIFACT = "shared.hook_visual"
VISUAL_RENDER_STATION = "visual_render"


def run_hook_visual(production: Any, execution: ProductionExecution, *, image_generator: Callable[[str], bytes] = generate_image) -> bool:
    execution.resume()
    locale = production.documentary.language("en")
    prompt = "Language-neutral cinematic documentary hook image, one strong visual mystery inspired only by this story; no captions, logos, signs, headlines, album lettering, watermarks, or readable text. " + (getattr(locale, "hook_text", None) or locale.story_text[:500])
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    sidecar = execution.factory_root / "shared" / "hook_visual.inputs.json"
    if HOOK_VISUAL_ARTIFACT not in execution.pending_artifacts(station=VISUAL_RENDER_STATION):
        execution.require_verified_completed(station=VISUAL_RENDER_STATION, artifact_id=HOOK_VISUAL_ARTIFACT)
        try:
            if json.loads(sidecar.read_text(encoding="utf-8")).get("prompt_sha256") == digest:
                return False
        except (OSError, json.JSONDecodeError):
            pass
        execution.requeue_artifact(station=VISUAL_RENDER_STATION, artifact_id=HOOK_VISUAL_ARTIFACT, reason="Hook visual input digest changed or is missing")
    session = production.session
    session.start_station(VISUAL_RENDER_STATION)
    claimed = False
    try:
        output = execution.start_artifact(station=VISUAL_RENDER_STATION, artifact_id=HOOK_VISUAL_ARTIFACT)
        claimed = True
        data = image_generator(prompt)
        if not data:
            raise RuntimeError("Hook visual generator returned empty image")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        execution.complete_artifact(station=VISUAL_RENDER_STATION, artifact_id=HOOK_VISUAL_ARTIFACT)
        save_json_atomic(sidecar, {"version": 1, "prompt_sha256": digest})
    except Exception as exc:
        if claimed:
            execution.fail_artifact(station=VISUAL_RENDER_STATION, artifact_id=HOOK_VISUAL_ARTIFACT, error_summary=f"{type(exc).__name__}: {exc}")
        session.finish_station(VISUAL_RENDER_STATION, success=False)
        raise
    session.artifact(HOOK_VISUAL_ARTIFACT, output, station=VISUAL_RENDER_STATION)
    session.finish_station(VISUAL_RENDER_STATION, success=True)
    return True
