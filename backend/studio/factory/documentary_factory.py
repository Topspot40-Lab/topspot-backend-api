"""The first canonical, local-only documentary factory slice.

This entry point deliberately adopts the Stage 3 contract only when the
caller explicitly requests canonical factory execution. Legacy station
commands continue to use their existing outputs and manifests unchanged.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from backend.studio.factory.production_execution import (
    ProductionExecution,
    ProductionWorkflowLock,
)
from backend.studio.production import Production
from backend.studio.stations.build_storyboard import (
    build_storyboard_payload,
    save_json_atomic,
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


VISUAL_PLANNING_STATION = "visual_planning"
STORYBOARD_ARTIFACT = "shared.storyboard_and_scene_plan"
_MAX_ERROR_SUMMARY_LENGTH = 400


def concise_error_summary(error: Exception) -> str:
    """Return a bounded one-line error suitable for persistent local state."""
    message = " ".join(str(error).split()) or "No error detail provided"
    return f"{type(error).__name__}: {message}"[:_MAX_ERROR_SUMMARY_LENGTH]


def run_visual_planning(
    production: Production,
    execution: ProductionExecution,
) -> bool:
    """Build the shared canonical storyboard if its verified output is absent.

    The existing storyboard payload builder remains the source of the actual
    construction logic. This adapter only binds it to canonical ownership,
    output paths, persistence, and session reporting.
    """
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
        payload = build_storyboard_payload(production)
        output_path.parent.mkdir(parents=True, exist_ok=True)
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
                # Completion verification may already have recorded failure.
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
) -> ProductionExecution:
    """Run the normal one-action canonical factory workflow for a production."""
    production = production_factory(slug)
    with ProductionWorkflowLock(production.work_root):
        production.session.start_production()
        try:
            contract = production.session.adopt_documentary_production_contract()
            execution = ProductionExecution(contract=contract, work_root=production.work_root)
            run_visual_planning(production, execution)
            execution.require_verified_completed(
                station=VISUAL_PLANNING_STATION,
                artifact_id=STORYBOARD_ARTIFACT,
            )
            research_kwargs: dict[str, Any] = {"providers": historical_providers}
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
