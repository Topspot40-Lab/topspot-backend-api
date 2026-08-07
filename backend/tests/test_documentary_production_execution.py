from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from backend.studio.factory import (
    ProductionExecution,
    create_documentary_production_contract,
    documentary_artifact_assignments,
)


def _execution(tmp_path: Path, **kwargs: object) -> ProductionExecution:
    return ProductionExecution(
        contract=create_documentary_production_contract("ed_sullivan"),
        work_root=tmp_path / "work",
        **kwargs,
    )


def test_assignments_cover_shared_and_three_language_artifacts(tmp_path: Path) -> None:
    execution = _execution(tmp_path)
    assignments = documentary_artifact_assignments(execution.contract)

    assert len(assignments) == 33
    assert len({item.artifact_id for item in assignments}) == 33
    assert len({item.contract_path for item in assignments}) == 33
    assert len([item for item in assignments if item.artifact_id.startswith("shared.")]) == 6
    assert any(item.artifact_id == "shared.opening_video" and item.station == "visual_render" for item in assignments)
    for code in ("en", "es", "pt-BR"):
        assert len([item for item in assignments if f".{code}." in item.artifact_id]) == 9
        assert any(item.station == f"youtube_prepare_{code}" for item in assignments)


def test_station_cannot_write_another_stations_artifact(tmp_path: Path) -> None:
    execution = _execution(tmp_path)

    with pytest.raises(PermissionError, match="assigned to"):
        execution.output_path(station="narration_es", artifact_id="delivery.en.narration.intro")
    with pytest.raises(PermissionError, match="assigned to"):
        execution.start_artifact(station="visual_planning", artifact_id="shared.visual_master")


def test_completion_records_attempt_timestamps_and_verification(tmp_path: Path) -> None:
    execution = _execution(tmp_path)
    artifact_id = "delivery.en.narration.intro"
    output = execution.start_artifact(station="narration_en", artifact_id=artifact_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"narration")
    execution.complete_artifact(station="narration_en", artifact_id=artifact_id)

    record = execution.record(artifact_id)
    assert record["status"] == "completed"
    assert record["attempts"] == 1
    assert record["started_at"]
    assert record["finished_at"]
    assert record["verification"]["valid"] is True
    assert record["verification"]["size_bytes"] == len(b"narration")
    assert record["verification"]["sha256"]


def test_failure_skip_and_invalid_output_are_recorded(tmp_path: Path) -> None:
    execution = _execution(tmp_path)
    failed = "delivery.en.narration.story"
    execution.start_artifact(station="narration_en", artifact_id=failed)
    execution.fail_artifact(station="narration_en", artifact_id=failed, error_summary="temporary input unavailable")
    execution.skip_artifact(station="youtube_prepare_en", artifact_id="publishing.en.captions", reason="deliberately excluded from this run")
    invalid = "delivery.en.narration.outro"
    execution.start_artifact(station="narration_en", artifact_id=invalid)
    with pytest.raises(ValueError, match="Output verification failed"):
        execution.complete_artifact(station="narration_en", artifact_id=invalid)

    assert execution.record(failed)["error_summary"] == "temporary input unavailable"
    assert execution.record("publishing.en.captions")["status"] == "skipped"
    assert execution.record("publishing.en.captions")["skip_reason"]
    assert execution.record(invalid)["status"] == "failed"


def test_resume_retains_verified_completed_and_requeues_interrupted_or_invalid(tmp_path: Path) -> None:
    execution = _execution(tmp_path)
    complete = "shared.storyboard_and_scene_plan"
    output = execution.start_artifact(station="visual_planning", artifact_id=complete)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("{}", encoding="utf-8")
    execution.complete_artifact(station="visual_planning", artifact_id=complete)

    interrupted = "delivery.es.narration.intro"
    execution.start_artifact(station="narration_es", artifact_id=interrupted)
    invalid = "delivery.pt-BR.narration.intro"
    invalid_output = execution.start_artifact(station="narration_pt-BR", artifact_id=invalid)
    invalid_output.parent.mkdir(parents=True, exist_ok=True)
    invalid_output.write_bytes(b"valid once")
    execution.complete_artifact(station="narration_pt-BR", artifact_id=invalid)
    invalid_output.unlink()

    resumed = execution.resume()

    assert complete not in resumed
    assert execution.record(complete)["status"] == "completed"
    assert interrupted in resumed
    assert invalid in resumed
    assert execution.record(interrupted)["status"] == "pending"
    assert execution.record(invalid)["status"] == "pending"


def test_compatibility_mapping_is_opt_in_and_preserves_legacy_path(tmp_path: Path) -> None:
    artifact_id = "delivery.en.narration.intro"
    execution = _execution(tmp_path, compatibility_mappings={artifact_id: "audio/legacy_intro.mp3"})

    assert execution.output_path(station="narration_en", artifact_id=artifact_id) == (tmp_path / "work" / "audio" / "legacy_intro.mp3")
    with pytest.raises(ValueError, match="requires the supplied compatibility mapping"):
        _execution(tmp_path)


def test_youtube_artifacts_are_preparation_only(tmp_path: Path) -> None:
    execution = _execution(tmp_path)

    assert execution.contract.youtube_multilingual.publishing_enabled is False
    assert execution.pending_artifacts(station="youtube_prepare_en") == (
        "publishing.en.complete_audio_master",
        "publishing.en.captions",
        "publishing.en.thumbnail",
        "publishing.en.youtube_metadata",
        "publishing.en.youtube_chapters",
    )

@pytest.mark.parametrize(
    "target",
    ["factory/execution.json", "factory/session.json", "factory/execution.lock", "factory/workflow.lock"],
)
def test_compatibility_mapping_rejects_factory_control_files(
    tmp_path: Path,
    target: str,
) -> None:
    with pytest.raises(ValueError, match="reserved factory control path"):
        _execution(
            tmp_path,
            compatibility_mappings={
                "delivery.en.narration.intro": target,
            },
        )


def test_compatibility_mapping_rejects_mapped_to_mapped_collision(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Artifact output paths must be unique"):
        _execution(
            tmp_path,
            compatibility_mappings={
                "delivery.en.narration.intro": "legacy/shared.mp3",
                "delivery.en.narration.story": "legacy/shared.mp3",
            },
        )


def test_compatibility_mapping_rejects_mapped_to_unmapped_collision(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Artifact output paths must be unique"):
        _execution(
            tmp_path,
            compatibility_mappings={
                "delivery.en.narration.intro": (
                    "factory/delivery/en/narration/story.mp3"
                ),
            },
        )


def test_compatibility_mapping_rejects_case_and_separator_aliases(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Artifact output paths must be unique"):
        _execution(
            tmp_path,
            compatibility_mappings={
                "delivery.en.narration.intro": "legacy/audio.mp3",
                "delivery.en.narration.story": "LEGACY\\AUDIO.MP3",
            },
        )


def test_independent_execution_instances_merge_different_updates(
    tmp_path: Path,
) -> None:
    first = _execution(tmp_path)
    second = _execution(tmp_path)

    first.start_artifact(
        station="narration_en",
        artifact_id="delivery.en.narration.intro",
    )
    second.start_artifact(
        station="narration_es",
        artifact_id="delivery.es.narration.intro",
    )

    current = _execution(tmp_path)
    assert current.record("delivery.en.narration.intro")["status"] == "running"
    assert current.record("delivery.es.narration.intro")["status"] == "running"


def test_independent_execution_instances_reject_conflicting_transition(
    tmp_path: Path,
) -> None:
    first = _execution(tmp_path)
    second = _execution(tmp_path)
    artifact_id = "delivery.en.narration.intro"

    first.start_artifact(station="narration_en", artifact_id=artifact_id)
    with pytest.raises(RuntimeError, match="already running"):
        second.start_artifact(station="narration_en", artifact_id=artifact_id)

    assert _execution(tmp_path).record(artifact_id)["attempts"] == 1


def _custom_contract_with_shared_path(path: str):
    contract = create_documentary_production_contract("ed_sullivan")
    return replace(
        contract,
        shared_assets=replace(
            contract.shared_assets,
            storyboard_and_scene_plan=path,
        ),
    )


@pytest.mark.parametrize(
    "path",
    ["execution.json", "session.json", "execution.lock", "workflow.lock", "ExEcUtIoN.JsOn"],
)
def test_custom_contract_default_output_rejects_factory_control_paths(
    tmp_path: Path,
    path: str,
) -> None:
    with pytest.raises(ValueError, match="reserved factory control path"):
        ProductionExecution(
            contract=_custom_contract_with_shared_path(path),
            work_root=tmp_path / "work",
        )


def test_ordinary_canonical_contract_still_creates_execution_ledger(
    tmp_path: Path,
) -> None:
    execution = _execution(tmp_path)

    assert execution.execution_path.exists()
    assert execution.record("shared.storyboard_and_scene_plan")["status"] == "pending"
def test_execution_ledger_additively_adopts_opening_video(tmp_path: Path) -> None:
    execution = _execution(tmp_path)
    ledger = execution.execution_path
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    original = payload["artifacts"].pop("shared.opening_video")
    payload["artifacts"]["shared.visual_master"]["status"] = "failed"
    payload["artifacts"]["shared.visual_master"]["error_summary"] = "retained"
    ledger.write_text(json.dumps(payload), encoding="utf-8")

    adopted = _execution(tmp_path)
    assert adopted.record("shared.opening_video")["status"] == "pending"
    assert adopted.record("shared.visual_master")["error_summary"] == "retained"
    assert original["station"] == "visual_render"