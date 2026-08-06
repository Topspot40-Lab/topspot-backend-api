from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.studio.factory import ProductionExecution, ProductionSession
from backend.studio.factory.documentary_factory import (
    STORYBOARD_ARTIFACT,
    VISUAL_PLANNING_STATION,
    VISUAL_RESEARCH_ARTIFACT,
    VISUAL_RESEARCH_STATION,
    create_documentary,
)
from backend.studio.stations.verify_historical_visuals import (
    PROVENANCE_ARTIFACT,
    QUALITY_ARTIFACT,
    VISUAL_QUALITY_STATION,
)
from backend.studio.stations.render_visual_master import (
    VISUAL_MASTER_ARTIFACT,
    VISUAL_RENDER_STATION,
    run_visual_render,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _fresh_import(module: str) -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )


def test_foundational_and_factory_modules_import_in_fresh_processes() -> None:
    modules = (
        "backend.studio.production",
        "backend.studio.stations.create_production",
        "backend.studio.stations.prepare_source_assets",
        "backend.studio.stations.build_storyboard",
        "backend.studio.stations.generate_visual_plan",
        "backend.studio.factory.documentary_factory",
    )
    for module in modules:
        _fresh_import(module)


class FakeDocumentary:
    title = "A Local Documentary"
    subtitle = "A test-only local story"
    source_type = "music_docuseries"
    source_id = 1

    def language(self, language_code: str) -> SimpleNamespace:
        assert language_code == "en"
        return SimpleNamespace(
            story_text="First sentence. Second sentence.",
            duration_seconds=16,
            locale_id=1,
        )


class FakeProduction:
    def __init__(self, tmp_path: Path, slug: str = "local_documentary") -> None:
        self.slug = slug
        self.work_root = tmp_path / "work"
        self.documentary = FakeDocumentary()
        self.session = ProductionSession(
            production_slug=slug,
            work_root=self.work_root,
        )


def _fake_image(_: str) -> bytes:
    return b"test image"

def _fake_narration(_: object, language: str, segment: str) -> bytes:
    return f"{language}:{segment}".encode()

def _fake_renderer(_: object, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"test visual master")

def _create(tmp_path: Path) -> tuple[FakeProduction, ProductionExecution]:
    production = FakeProduction(tmp_path)
    execution = create_documentary(
        production.slug,
        production_factory=lambda _: production,
        historical_providers=[],
        visual_image_generator=_fake_image,
        visual_renderer=_fake_renderer,
        narration_retriever=_fake_narration,
    )
    return production, execution


def test_create_documentary_builds_only_canonical_storyboard(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    output = production.work_root / "factory" / "shared" / "visual_plan.json"

    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["production_slug"] == production.slug
    assert execution.record(STORYBOARD_ARTIFACT)["status"] == "completed"
    assert execution.record(STORYBOARD_ARTIFACT)["station"] == VISUAL_PLANNING_STATION
    station = production.session.payload["stations"][VISUAL_PLANNING_STATION]
    assert station["status"] == "complete"
    assert production.session.payload["status"] == "complete"
    assert (production.work_root / "factory" / "shared" / "visual_research.json").exists()
    assert execution.record(VISUAL_RESEARCH_ARTIFACT)["status"] == "completed"
    assert execution.record(VISUAL_RESEARCH_ARTIFACT)["station"] == VISUAL_RESEARCH_STATION
    provenance = production.work_root / "factory" / "shared" / "historical_photo_provenance.json"
    quality = production.work_root / "factory" / "shared" / "visual_qc.json"
    assert provenance.exists()
    assert quality.exists()
    assert execution.record(PROVENANCE_ARTIFACT)["status"] == "completed"
    assert execution.record(QUALITY_ARTIFACT)["status"] == "completed"
    assert execution.record(PROVENANCE_ARTIFACT)["station"] == VISUAL_QUALITY_STATION
    assert json.loads(provenance.read_text(encoding="utf-8"))["entries"] == []
    assert json.loads(quality.read_text(encoding="utf-8"))["summary"]["passed"] is True
    master = production.work_root / "factory" / "shared" / "visual_master.mp4"
    assert master.exists()
    assert execution.record(VISUAL_MASTER_ARTIFACT)["status"] == "completed"
    assert execution.record(VISUAL_MASTER_ARTIFACT)["station"] == VISUAL_RENDER_STATION


def test_create_documentary_resume_skips_verified_storyboard(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    output = execution.output_path(
        station=VISUAL_PLANNING_STATION,
        artifact_id=STORYBOARD_ARTIFACT,
    )
    before = output.read_bytes()

    with patch(
        "backend.studio.factory.documentary_factory.build_storyboard_payload",
        side_effect=AssertionError("completed storyboard should be skipped"),
    ):
        resumed = create_documentary(
            production.slug,
            production_factory=lambda _: production,
            historical_providers=[],
            narration_retriever=_fake_narration,
        )

    assert output.read_bytes() == before
    assert resumed.record(STORYBOARD_ARTIFACT)["status"] == "completed"
    assert resumed.record(STORYBOARD_ARTIFACT)["attempts"] == 1


def test_interrupted_storyboard_is_requeued_and_rebuilt(tmp_path: Path) -> None:
    production = FakeProduction(tmp_path)
    contract = production.session.adopt_documentary_production_contract()
    first = ProductionExecution(contract=contract, work_root=production.work_root)
    first.start_artifact(
        station=VISUAL_PLANNING_STATION,
        artifact_id=STORYBOARD_ARTIFACT,
    )

    execution = create_documentary(
        production.slug,
        production_factory=lambda _: production,
        historical_providers=[],
        visual_image_generator=_fake_image,
        visual_renderer=_fake_renderer,
        narration_retriever=_fake_narration,
    )

    assert execution.record(STORYBOARD_ARTIFACT)["status"] == "completed"
    assert execution.record(STORYBOARD_ARTIFACT)["attempts"] == 2


def test_storyboard_failure_is_concisely_recorded(tmp_path: Path) -> None:
    production = FakeProduction(tmp_path)

    with patch(
        "backend.studio.factory.documentary_factory.build_storyboard_payload",
        side_effect=ValueError("bad\nlocal input"),
    ), pytest.raises(ValueError, match="bad"):
        create_documentary(
            production.slug,
            production_factory=lambda _: production,
            historical_providers=[],
            narration_retriever=_fake_narration,
        )

    execution = ProductionExecution(
        contract=production.session.adopt_documentary_production_contract(),
        work_root=production.work_root,
    )
    record = execution.record(STORYBOARD_ARTIFACT)
    assert record["status"] == "failed"
    assert record["error_summary"] == "ValueError: bad local input"
    station = production.session.payload["stations"][VISUAL_PLANNING_STATION]
    assert station["status"] == "failed"
    assert station["errors"][-1]["message"] == "ValueError: bad local input"
    assert production.session.payload["status"] == "failed"


def test_skipped_storyboard_cannot_complete_production(tmp_path: Path) -> None:
    production = FakeProduction(tmp_path)
    contract = production.session.adopt_documentary_production_contract()
    execution = ProductionExecution(contract=contract, work_root=production.work_root)
    execution.skip_artifact(
        station=VISUAL_PLANNING_STATION,
        artifact_id=STORYBOARD_ARTIFACT,
        reason="manually excluded",
    )

    with pytest.raises(RuntimeError, match="not verified and completed"):
        create_documentary(production.slug, production_factory=lambda _: production, historical_providers=[], visual_image_generator=_fake_image, visual_renderer=_fake_renderer, narration_retriever=_fake_narration)

    assert execution.record(STORYBOARD_ARTIFACT)["status"] == "skipped"
    assert not execution.output_path(
        station=VISUAL_PLANNING_STATION,
        artifact_id=STORYBOARD_ARTIFACT,
    ).exists()
    assert production.session.payload["status"] == "failed"


@pytest.mark.parametrize("tamper", ["removed", "changed"])
def test_tampered_completed_storyboard_is_rebuilt(tmp_path: Path, tamper: str) -> None:
    production, execution = _create(tmp_path)
    output = execution.output_path(
        station=VISUAL_PLANNING_STATION,
        artifact_id=STORYBOARD_ARTIFACT,
    )
    if tamper == "removed":
        output.unlink()
    else:
        output.write_text('{"tampered": true}', encoding="utf-8")

    resumed = create_documentary(production.slug, production_factory=lambda _: production, historical_providers=[], visual_image_generator=_fake_image, visual_renderer=_fake_renderer, narration_retriever=_fake_narration)

    assert resumed.record(STORYBOARD_ARTIFACT)["status"] == "completed"
    assert resumed.record(STORYBOARD_ARTIFACT)["attempts"] == 2
    assert json.loads(output.read_text(encoding="utf-8"))["production_slug"] == production.slug
    assert production.session.payload["status"] == "complete"


def test_rebuilt_storyboard_requeues_visual_research(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    storyboard_path = execution.output_path(
        station=VISUAL_PLANNING_STATION,
        artifact_id=STORYBOARD_ARTIFACT,
    )
    research_path = execution.output_path(
        station=VISUAL_RESEARCH_STATION,
        artifact_id=VISUAL_RESEARCH_ARTIFACT,
    )
    first_digest = json.loads(research_path.read_text(encoding="utf-8"))["storyboard_sha256"]
    storyboard_path.write_text('{"tampered": true}', encoding="utf-8")

    resumed = create_documentary(
        production.slug,
        production_factory=lambda _: production,
        historical_providers=[],
        visual_image_generator=_fake_image,
        visual_renderer=_fake_renderer,
        narration_retriever=_fake_narration,
    )

    package = json.loads(research_path.read_text(encoding="utf-8"))
    assert resumed.record(STORYBOARD_ARTIFACT)["attempts"] == 2
    assert resumed.record(VISUAL_RESEARCH_ARTIFACT)["attempts"] == 2
    assert package["storyboard_sha256"] != first_digest
    assert package["storyboard_sha256"] == resumed.record(STORYBOARD_ARTIFACT)["verification"]["sha256"]

def test_workflow_lock_prevents_overlapping_factory_invocation(tmp_path: Path) -> None:
    first = FakeProduction(tmp_path)
    second = FakeProduction(tmp_path)
    building = threading.Event()
    release_builder = threading.Event()
    first_result: list[ProductionExecution] = []
    first_error: list[BaseException] = []

    def blocked_builder(production: FakeProduction) -> dict[str, object]:
        building.set()
        assert release_builder.wait(timeout=5)
        from backend.studio.stations.build_storyboard import build_storyboard_payload as real_builder

        return real_builder(production)

    def run_first() -> None:
        try:
            first_result.append(
                create_documentary(first.slug, production_factory=lambda _: first, historical_providers=[], visual_image_generator=_fake_image, visual_renderer=_fake_renderer, narration_retriever=_fake_narration)
            )
        except BaseException as exc:  # surfaced below with the original traceback context
            first_error.append(exc)

    with patch(
        "backend.studio.factory.documentary_factory.build_storyboard_payload",
        side_effect=blocked_builder,
    ):
        worker = threading.Thread(target=run_first)
        worker.start()
        assert building.wait(timeout=5)

        locked_execution = ProductionExecution(
            contract=second.session.adopt_documentary_production_contract(),
            work_root=second.work_root,
        )
        running = locked_execution.record(STORYBOARD_ARTIFACT)
        assert running["status"] == "running"
        assert running["attempts"] == 1
        with pytest.raises(RuntimeError, match="production already running"):
            create_documentary(second.slug, production_factory=lambda _: second, visual_image_generator=_fake_image, visual_renderer=_fake_renderer, narration_retriever=_fake_narration)
        assert locked_execution.record(STORYBOARD_ARTIFACT)["status"] == "running"
        assert locked_execution.record(STORYBOARD_ARTIFACT)["attempts"] == 1

        release_builder.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert not first_error
    assert first_result[0].record(STORYBOARD_ARTIFACT)["status"] == "completed"

    with patch(
        "backend.studio.factory.documentary_factory.build_storyboard_payload",
        side_effect=AssertionError("verified storyboard should not rebuild"),
    ):
        resumed = create_documentary(
            first.slug,
            production_factory=lambda _: FakeProduction(tmp_path),
            narration_retriever=_fake_narration,
        )
    assert resumed.record(STORYBOARD_ARTIFACT)["attempts"] == 1


def test_tampered_visual_master_is_rebuilt(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    master = execution.output_path(
        station=VISUAL_RENDER_STATION,
        artifact_id=VISUAL_MASTER_ARTIFACT,
    )
    master.write_bytes(b"tampered")

    resumed = create_documentary(
        production.slug,
        production_factory=lambda _: production,
        historical_providers=[],
        visual_image_generator=_fake_image,
        visual_renderer=_fake_renderer,
        narration_retriever=_fake_narration,
    )

    assert resumed.record(VISUAL_MASTER_ARTIFACT)["attempts"] == 2
    assert master.read_bytes() == b"test visual master"


def test_visual_render_is_blocked_by_verified_failed_qc(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    execution.requeue_artifact(
        station=VISUAL_QUALITY_STATION,
        artifact_id=QUALITY_ARTIFACT,
        reason="test failing QC",
    )
    quality = execution.start_artifact(
        station=VISUAL_QUALITY_STATION,
        artifact_id=QUALITY_ARTIFACT,
    )
    quality.write_text('{"summary": {"passed": false}}', encoding="utf-8")
    execution.complete_artifact(
        station=VISUAL_QUALITY_STATION,
        artifact_id=QUALITY_ARTIFACT,
    )

    with pytest.raises(RuntimeError, match="visual QC passes"):
        run_visual_render(
            production,
            execution,
            image_generator=_fake_image,
            renderer=_fake_renderer,
        )

def test_tampered_narration_track_rebuilds_only_its_language_track(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    intro = execution.output_path(
        station="narration_en",
        artifact_id="delivery.en.narration.intro",
    )
    story = execution.output_path(
        station="narration_en",
        artifact_id="delivery.en.narration.story",
    )
    outro = execution.output_path(
        station="narration_en",
        artifact_id="delivery.en.narration.outro",
    )
    story_before = story.read_bytes()
    outro_before = outro.read_bytes()
    intro.write_bytes(b"tampered")

    resumed = create_documentary(
        production.slug,
        production_factory=lambda _: production,
        historical_providers=[],
        visual_image_generator=_fake_image,
        visual_renderer=_fake_renderer,
        narration_retriever=_fake_narration,
    )

    assert resumed.record("delivery.en.narration.intro")["attempts"] == 2
    assert resumed.record("delivery.en.narration.story")["attempts"] == 1
    assert resumed.record("delivery.en.narration.outro")["attempts"] == 1
    assert story.read_bytes() == story_before
    assert outro.read_bytes() == outro_before