"""The first canonical, local-only documentary factory slice.

This entry point deliberately adopts the Stage 3 contract only when the
caller explicitly requests canonical factory execution. Legacy station
commands continue to use their existing outputs and manifests unchanged.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from backend.studio.factory.production_execution import (
    ProductionExecution,
    ProductionWorkflowLock,
)
from backend.studio.factory.delivery_package_verification import (
    verify_final_delivery_packages,
)
from backend.studio.factory.input_preflight import validate_factory_inputs
from backend.studio.production import Production
from backend.studio.stations.build_storyboard import (
    build_storyboard_payload,
    save_json_atomic,
)
from backend.studio.stations.generate_visual_plan import (
    apply_scene_plan,
    request_visual_plan,
    validate_scene_plan,
)
from backend.studio.stations.select_historical_visuals import (
    VISUAL_RESEARCH_ARTIFACT,
    VISUAL_RESEARCH_STATION,
    run_visual_research,
)
from backend.studio.stations.verify_historical_visuals import (
    PROVENANCE_ARTIFACT,
    QUALITY_ARTIFACT,
    VISUAL_QUALITY_STATION,
    run_visual_quality,
)
from backend.studio.stations.render_visual_master import (
    VISUAL_MASTER_ARTIFACT,
    VISUAL_RENDER_STATION,
    run_visual_render,
)
from backend.studio.stations.render_opening_video import (
    OPENING_VIDEO_ARTIFACT,
    run_opening_render,
)
from backend.studio.stations.prepare_localized_narration import run_localized_narration
from backend.studio.stations.build_localized_delivery import run_localized_deliveries


VISUAL_PLANNING_STATION = "visual_planning"
STORYBOARD_ARTIFACT = "shared.storyboard_and_scene_plan"
_MAX_ERROR_SUMMARY_LENGTH = 400


def concise_error_summary(error: Exception) -> str:
    """Return a bounded one-line error suitable for persistent local state."""
    message = " ".join(str(error).split()) or "No error detail provided"
    return f"{type(error).__name__}: {message}"[:_MAX_ERROR_SUMMARY_LENGTH]


def _scene_is_prompt_ready(scene: dict[str, Any]) -> bool:
    shots = scene.get("visual_shots", [])
    return bool(shots) and all(
        shot.get("status") == "prompt_ready"
        and bool(str(shot.get("prompt") or "").strip())
        and bool(str(shot.get("visual_intent") or "").strip())
        and "historical_search" in shot
        and isinstance(shot.get("historical_plan"), dict)
        for shot in shots
    )


def _resume_or_build_storyboard(
    production: Production,
    output_path: Any,
) -> dict[str, Any]:
    if output_path.is_file():
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
        if (
            isinstance(payload, dict)
            and payload.get("production_slug") == production.slug
            and isinstance(payload.get("scenes"), list)
        ):
            return payload
    return build_storyboard_payload(production)


def run_visual_planning(
    production: Production,
    execution: ProductionExecution,
    *,
    visual_planner: Callable[..., list[dict[str, Any]]] | None = None,
) -> bool:
    """Build and persist the canonical storyboard with prompt-ready shots."""
    execution.resume()
    if STORYBOARD_ARTIFACT not in execution.pending_artifacts(
        station=VISUAL_PLANNING_STATION,
    ):
        execution.require_verified_completed(
            station=VISUAL_PLANNING_STATION,
            artifact_id=STORYBOARD_ARTIFACT,
        )
        return False

    session = production.session
    session.start_station(VISUAL_PLANNING_STATION)
    claimed = False
    try:
        output_path = execution.start_artifact(
            station=VISUAL_PLANNING_STATION,
            artifact_id=STORYBOARD_ARTIFACT,
        )
        claimed = True
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = _resume_or_build_storyboard(production, output_path)
        planner = visual_planner or request_visual_plan
        for scene in payload["scenes"]:
            if _scene_is_prompt_ready(scene):
                continue
            plan = planner(
                documentary_title=production.documentary.title,
                scene=scene,
            )
            validate_scene_plan(scene=scene, plan=plan)
            apply_scene_plan(scene=scene, plan=plan)
            save_json_atomic(output_path, payload)
        save_json_atomic(output_path, payload)
        execution.complete_artifact(
            station=VISUAL_PLANNING_STATION,
            artifact_id=STORYBOARD_ARTIFACT,
        )
    except Exception as exc:
        summary = concise_error_summary(exc)
        if claimed:
            try:
                execution.fail_artifact(
                    station=VISUAL_PLANNING_STATION,
                    artifact_id=STORYBOARD_ARTIFACT,
                    error_summary=summary,
                )
            except RuntimeError:
                pass
        session.error(summary, station=VISUAL_PLANNING_STATION)
        session.finish_station(VISUAL_PLANNING_STATION, success=False)
        raise

    session.metric("scene_count", payload["scene_count"], station=VISUAL_PLANNING_STATION)
    session.metric("visual_shot_count", payload["visual_shot_count"], station=VISUAL_PLANNING_STATION)
    session.artifact(STORYBOARD_ARTIFACT, output_path, station=VISUAL_PLANNING_STATION)
    session.finish_station(VISUAL_PLANNING_STATION, success=True)
    execution.require_verified_completed(
        station=VISUAL_PLANNING_STATION,
        artifact_id=STORYBOARD_ARTIFACT,
    )
    return True
def create_documentary(
    slug: str,
    *,
    production_factory: Callable[[str], Production] = Production,
    historical_providers: list[Any] | None = None,
    historical_retriever: Callable[[Any], bytes] | None = None,
    visual_planner: Callable[..., list[dict[str, Any]]] | None = None,
    visual_image_generator: Callable[[str], bytes] | None = None,
    visual_renderer: Callable[[Any, Any], None] | None = None,
    opening_renderer: Callable[[Any, Any], None] | None = None,
    narration_retriever: Callable[[Any, str, str], bytes] | None = None,
    delivery_builder: Callable[[Any, Any, Any], None] | None = None,
    delivery_media_validator: Callable[[Any, Any], dict[str, float]] | None = None,
    delivery_bed_ensurer: Callable[..., None] | None = None,
) -> ProductionExecution:
    """Run the normal one-action canonical factory workflow for a production."""
    production = production_factory(slug)
    validate_factory_inputs(production.documentary)
    with ProductionWorkflowLock(production.work_root):
        production.session.start_production()
        try:
            contract = production.session.adopt_documentary_production_contract()
            execution = ProductionExecution(contract=contract, work_root=production.work_root)
            run_visual_planning(production, execution, visual_planner=visual_planner)
            execution.require_verified_completed(
                station=VISUAL_PLANNING_STATION,
                artifact_id=STORYBOARD_ARTIFACT,
            )
            research_kwargs: dict[str, Any] = {
                "providers": (
                    historical_providers
                    if historical_providers is not None
                    else []
                )
            }
            if historical_retriever is not None:
                research_kwargs["retriever"] = historical_retriever
            run_visual_research(production, execution, **research_kwargs)
            execution.require_verified_completed(
                station=VISUAL_RESEARCH_STATION,
                artifact_id=VISUAL_RESEARCH_ARTIFACT,
            )
            run_visual_quality(production, execution)
            for artifact_id in (PROVENANCE_ARTIFACT, QUALITY_ARTIFACT):
                execution.require_verified_completed(
                    station=VISUAL_QUALITY_STATION,
                    artifact_id=artifact_id,
                )
            render_kwargs: dict[str, Any] = {}
            if visual_image_generator is not None:
                render_kwargs["image_generator"] = visual_image_generator
            if visual_renderer is not None:
                render_kwargs["renderer"] = visual_renderer
            run_visual_render(production, execution, **render_kwargs)
            execution.require_verified_completed(
                station=VISUAL_RENDER_STATION,
                artifact_id=VISUAL_MASTER_ARTIFACT,
            )
            opening_kwargs: dict[str, Any] = {}
            if opening_renderer is not None:
                opening_kwargs["renderer"] = opening_renderer
            run_opening_render(production, execution, **opening_kwargs)
            execution.require_verified_completed(
                station=VISUAL_RENDER_STATION,
                artifact_id=OPENING_VIDEO_ARTIFACT,
            )
            narration_kwargs: dict[str, Any] = {}
            if narration_retriever is not None:
                narration_kwargs["retriever"] = narration_retriever
            run_localized_narration(production, execution, **narration_kwargs)
            delivery_kwargs: dict[str, Any] = {}
            if delivery_builder is not None:
                delivery_kwargs["builder"] = delivery_builder
            if delivery_media_validator is not None:
                delivery_kwargs["media_validator"] = delivery_media_validator
            if delivery_bed_ensurer is not None:
                delivery_kwargs["bed_ensurer"] = delivery_bed_ensurer
            run_localized_deliveries(production, execution, **delivery_kwargs)
            verify_final_delivery_packages(execution)
        except Exception as exc:
            production.session.error(concise_error_summary(exc))
            production.session.finish_production(success=False)
            raise

        production.session.finish_production(success=True)
        return execution


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a canonical TopSpot documentary visual plan.",
    )
    parser.add_argument("--slug", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        create_documentary(args.slug)
    except (FileNotFoundError, KeyError, LookupError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Create Documentary failed: {concise_error_summary(exc)}") from exc


if __name__ == "__main__":
    main()
