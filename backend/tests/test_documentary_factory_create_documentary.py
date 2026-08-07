from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch
from backend.studio.factory.production_contract import SUPPORTED_LANGUAGE_CODES
from backend.studio.stations.prepare_localized_narration import (
    SEGMENTS,
    narration_artifact,
    narration_station,
)

import pytest

from backend.studio.factory import ProductionExecution, ProductionSession
from backend.studio.factory.documentary_factory import (
    STORYBOARD_ARTIFACT,
    VISUAL_PLANNING_STATION,
    VISUAL_RESEARCH_ARTIFACT,
    VISUAL_RESEARCH_STATION,
    create_documentary,
    run_visual_planning,
)
from backend.studio.stations.render_opening_video import (
    OPENING_VIDEO_ARTIFACT,
    run_opening_render,
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
from backend.studio.stations.build_localized_delivery import (
    run_localized_deliveries,
    validate_delivery_media,
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

    languages = tuple(
        SimpleNamespace(
            language_code=language_code,
            story_text="First sentence. Second sentence.",
            duration_seconds=16,
            tts_bucket=f"audio-{language_code}",
            tts_key=f"stories/{language_code}.mp3",
            locale_id=index,
        )
        for index, language_code in enumerate(SUPPORTED_LANGUAGE_CODES, start=1)
    )

    def language(self, language_code: str) -> SimpleNamespace:
        return next(
            language
            for language in self.languages
            if language.language_code == language_code
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


def _fake_visual_planner(
    *,
    documentary_title: str,
    scene: dict[str, object],
) -> list[dict[str, object]]:
    return [
        {
            "shot_number": shot["shot_number"],
            "visual_intent": f"{documentary_title} scene {scene['scene_number']} visual",
            "historical_search": f"{documentary_title} scene {scene['scene_number']}",
            "historical_plan": {
                "subject": documentary_title,
                "subject_type": "group",
                "era": "documentary era",
                "required_terms": [documentary_title],
                "avoid_terms": [],
                "search_queries": [f"{documentary_title} archive", f"{documentary_title} scene"],
            },
            "image_prompt": f"16:9 documentary image for {documentary_title} scene {scene['scene_number']}",
        }
        for shot in scene["visual_shots"]
    ]


@pytest.fixture(autouse=True)
def _use_fake_visual_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.studio.factory.documentary_factory.request_visual_plan",
        _fake_visual_planner,
    )
    monkeypatch.setattr(
        "backend.studio.stations.render_opening_video.render_opening",
        _fake_opening,
    )

def _multi_scene_production(tmp_path: Path) -> FakeProduction:
    production = FakeProduction(tmp_path)
    production.documentary.languages = tuple(
        SimpleNamespace(
            **{
                **vars(language),
                "story_text": "One. Two. Three. Four.",
                "duration_seconds": 32,
            }
        )
        if language.language_code == "en"
        else language
        for language in production.documentary.languages
    )
    return production

def _fake_image(_: str) -> bytes:
    return b"test image"

def _fake_narration(_: object, language: str, segment: str) -> bytes:
    return f"{language}:{segment}".encode()

def _unexpected_narration(
    _: object,
    language: str,
    segment: str,
) -> bytes:
    raise AssertionError(
        f"Completed local narration should be reused: {language}:{segment}"
    )


def _fake_delivery(_: Path, __: Path, ___: Path, ____: object, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"test delivery")

def _fake_media(_: Path, __: object) -> dict[str, float]:
    return {"duration_seconds": 3.0, "fps": 30.0}

def _fake_opening(_: object, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"test opening")

def _fake_renderer(_: object, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"test visual master")

def _create(tmp_path: Path) -> tuple[FakeProduction, ProductionExecution]:
    production = FakeProduction(tmp_path)
    execution = create_documentary(
        production.slug,
        production_factory=lambda _: production,
        visual_planner=_fake_visual_planner,
        visual_image_generator=_fake_image,
        visual_renderer=_fake_renderer,
        opening_renderer=_fake_opening,
        narration_retriever=_fake_narration,
        delivery_builder=_fake_delivery, delivery_media_validator=_fake_media,
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
    research = (
        production.work_root
        / "factory"
        / "shared"
        / "visual_research.json"
    )
    assert research.exists()
    research_payload = json.loads(research.read_text(encoding="utf-8"))
    assert research_payload["summary"]["provider_searches"] == 0
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
        delivery_builder=_fake_delivery, delivery_media_validator=_fake_media,
        )

    assert output.read_bytes() == before
    assert resumed.record(STORYBOARD_ARTIFACT)["status"] == "completed"
    assert resumed.record(STORYBOARD_ARTIFACT)["attempts"] == 1

def test_create_documentary_resume_uses_completed_local_narration(
    tmp_path: Path,
) -> None:
    production, _ = _create(tmp_path)

    resumed = create_documentary(
        production.slug,
        production_factory=lambda _: production,
        historical_providers=[],
        narration_retriever=_unexpected_narration,
        delivery_builder=_fake_delivery,
        delivery_media_validator=_fake_media,
    )

    for language in SUPPORTED_LANGUAGE_CODES:
        station = narration_station(language)

        for segment in SEGMENTS:
            artifact = narration_artifact(language, segment)
            record = resumed.record(artifact)

            assert record["status"] == "completed"
            assert record["attempts"] == 1
            assert resumed.output_path(
                station=station,
                artifact_id=artifact,
            ).is_file()


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
        opening_renderer=_fake_opening,
        narration_retriever=_fake_narration,
        delivery_builder=_fake_delivery, delivery_media_validator=_fake_media,
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
        delivery_builder=_fake_delivery, delivery_media_validator=_fake_media,
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
        create_documentary(production.slug, production_factory=lambda _: production, historical_providers=[], visual_image_generator=_fake_image, visual_renderer=_fake_renderer, narration_retriever=_fake_narration, delivery_builder=_fake_delivery, delivery_media_validator=_fake_media)

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

    resumed = create_documentary(production.slug, production_factory=lambda _: production, historical_providers=[], visual_image_generator=_fake_image, visual_renderer=_fake_renderer, narration_retriever=_fake_narration, delivery_builder=_fake_delivery, delivery_media_validator=_fake_media)

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
        opening_renderer=_fake_opening,
        narration_retriever=_fake_narration,
        delivery_builder=_fake_delivery, delivery_media_validator=_fake_media,
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
                create_documentary(first.slug, production_factory=lambda _: first, historical_providers=[], visual_image_generator=_fake_image, visual_renderer=_fake_renderer, narration_retriever=_fake_narration, delivery_builder=_fake_delivery, delivery_media_validator=_fake_media)
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
            create_documentary(second.slug, production_factory=lambda _: second, visual_image_generator=_fake_image, visual_renderer=_fake_renderer, narration_retriever=_fake_narration, delivery_builder=_fake_delivery, delivery_media_validator=_fake_media)
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
        delivery_builder=_fake_delivery, delivery_media_validator=_fake_media,
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
        opening_renderer=_fake_opening,
        narration_retriever=_fake_narration,
        delivery_builder=_fake_delivery, delivery_media_validator=_fake_media,
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
        opening_renderer=_fake_opening,
        narration_retriever=_fake_narration,
        delivery_builder=_fake_delivery, delivery_media_validator=_fake_media,
    )

    assert resumed.record("delivery.en.narration.intro")["attempts"] == 2
    assert resumed.record("delivery.en.narration.story")["attempts"] == 1
    assert resumed.record("delivery.en.narration.outro")["attempts"] == 1
    assert story.read_bytes() == story_before
    assert outro.read_bytes() == outro_before

def test_all_contract_delivery_artifacts_are_completed(tmp_path: Path) -> None:
    _, execution = _create(tmp_path)
    for language in ("en", "es", "pt-BR"):
        record = execution.record(f"delivery.{language}.video")
        assert record["station"] == f"localized_delivery_{language}"
        assert record["status"] == "completed"
        assert execution.output_path(
            station=f"localized_delivery_{language}",
            artifact_id=f"delivery.{language}.video",
        ).read_bytes() == b"test delivery"

def test_delivery_failure_isolated_and_later_languages_complete(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    for language in ("en", "es", "pt-BR"):
        execution.requeue_artifact(
            station=f"localized_delivery_{language}",
            artifact_id=f"delivery.{language}.video",
            reason="exercise isolated delivery failure",
        )

    attempted: list[str] = []

    def failing_en_builder(_: Path, __: Path, ___: Path, tracks: tuple[Path, Path, Path], output: Path) -> None:
        language = tracks[0].read_text(encoding="utf-8").split(":", maxsplit=1)[0]
        attempted.append(language)
        if language == "en":
            raise RuntimeError("en delivery failure")
        _fake_delivery(_, _, _, tracks, output)

    with pytest.raises(RuntimeError, match="en: RuntimeError: en delivery failure"):
        run_localized_deliveries(production, execution, builder=failing_en_builder, media_validator=_fake_media)

    assert attempted == ["en", "es", "pt-BR"]
    assert execution.record("delivery.en.video")["status"] == "failed"
    assert execution.record("delivery.es.video")["status"] == "completed"
    assert execution.record("delivery.pt-BR.video")["status"] == "completed"

def _media_metadata(*, duration: float = 3.0, video: bool = True, audio: bool = True, width: int = 1920, height: int = 1080, fps: str = "30/1", audio_duration: float | None = None) -> dict[str, object]:
    streams: list[dict[str, object]] = []
    if video:
        streams.append({"codec_type": "video", "width": width, "height": height, "avg_frame_rate": fps, "duration": str(duration)})
    if audio:
        streams.append({"codec_type": "audio", "duration": str(duration if audio_duration is None else audio_duration)})
    return {"streams": streams, "format": {"duration": str(duration)}}


def test_localized_delivery_media_acceptance_and_rejections(tmp_path: Path) -> None:
    output = tmp_path / "documentary.mp4"
    output.write_bytes(b"not empty")
    tracks = tuple(tmp_path / f"{part}.mp3" for part in ("intro", "story", "outro"))
    for track in tracks:
        track.write_bytes(b"audio")

    def valid_probe(path: Path) -> dict[str, object]:
        return _media_metadata(duration=3.0) if path == output else _media_metadata(duration=1.0, video=False)

    assert validate_delivery_media(output, tracks, probe=valid_probe) == {"duration_seconds": 3.0, "fps": 30.0}

    def padded_video_probe(path: Path) -> dict[str, object]:
        return (
            _media_metadata(duration=5.0, audio_duration=3.0)
            if path == output
            else _media_metadata(duration=1.0, video=False)
        )

    assert validate_delivery_media(
        output,
        tracks,
        probe=padded_video_probe,
    ) == {"duration_seconds": 5.0, "fps": 30.0}

    cases = (
        ("no video", _media_metadata(duration=3.0, video=False)),
        ("no audio", _media_metadata(duration=3.0, audio=False)),
        ("bad resolution", _media_metadata(duration=3.0, width=1280)),
        ("bad fps", _media_metadata(duration=3.0, fps="24/1")),
        ("bad duration", _media_metadata(duration=0.0)),
        ("unsynchronized", _media_metadata(duration=4.0)),
    )
    for _, delivery in cases:
        def rejecting_probe(path: Path, metadata: dict[str, object] = delivery) -> dict[str, object]:
            return metadata if path == output else _media_metadata(duration=1.0, video=False)
        with pytest.raises(RuntimeError):
            validate_delivery_media(output, tracks, probe=rejecting_probe)


def test_delivery_resume_skips_valid_per_language_outputs(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    assert run_localized_deliveries(production, execution, builder=_fake_delivery, media_validator=_fake_media) is False
    for language in ("en", "es", "pt-BR"):
        assert execution.record(f"delivery.{language}.video")["attempts"] == 1


@pytest.mark.parametrize("tamper", ("missing", "changed"))
def test_delivery_tamper_or_missing_rebuilds_only_affected_language(tmp_path: Path, tamper: str) -> None:
    production, execution = _create(tmp_path)
    output = execution.output_path(station="localized_delivery_en", artifact_id="delivery.en.video")
    if tamper == "missing":
        output.unlink()
    else:
        output.write_bytes(b"tampered")
    create_documentary(production.slug, production_factory=lambda _: production, historical_providers=[], visual_image_generator=_fake_image, visual_renderer=_fake_renderer, narration_retriever=_fake_narration, delivery_builder=_fake_delivery, delivery_media_validator=_fake_media)
    assert execution.record("delivery.en.video")["attempts"] == 2
    assert execution.record("delivery.es.video")["attempts"] == 1
    assert execution.record("delivery.pt-BR.video")["attempts"] == 1


def test_delivery_requires_verified_stage_8_tracks(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    execution.requeue_artifact(station="narration_en", artifact_id="delivery.en.narration.intro", reason="test Stage 8 gate")
    with pytest.raises(RuntimeError, match="Localized delivery failures"):
        run_localized_deliveries(production, execution, builder=_fake_delivery, media_validator=_fake_media)
    assert execution.record("delivery.en.video")["status"] == "completed"

def test_verified_visual_master_change_rebuilds_all_deliveries(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    master = execution.output_path(station=VISUAL_RENDER_STATION, artifact_id=VISUAL_MASTER_ARTIFACT)
    execution.requeue_artifact(station=VISUAL_RENDER_STATION, artifact_id=VISUAL_MASTER_ARTIFACT, reason="test visual input change")
    rebuilt = execution.start_artifact(station=VISUAL_RENDER_STATION, artifact_id=VISUAL_MASTER_ARTIFACT)
    rebuilt.write_bytes(b"changed visual master")
    execution.complete_artifact(station=VISUAL_RENDER_STATION, artifact_id=VISUAL_MASTER_ARTIFACT)
    assert rebuilt == master

    assert run_localized_deliveries(production, execution, builder=_fake_delivery, media_validator=_fake_media) is True
    for language in ("en", "es", "pt-BR"):
        assert execution.record(f"delivery.{language}.video")["attempts"] == 2

def test_verified_narration_change_rebuilds_only_its_language_delivery(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    artifact = "delivery.en.narration.intro"
    execution.requeue_artifact(station="narration_en", artifact_id=artifact, reason="test narration source change")
    changed = execution.start_artifact(station="narration_en", artifact_id=artifact)
    changed.write_bytes(b"en:intro:changed")
    execution.complete_artifact(station="narration_en", artifact_id=artifact)

    assert run_localized_deliveries(production, execution, builder=_fake_delivery, media_validator=_fake_media) is True
    assert execution.record("delivery.en.video")["attempts"] == 2
    assert execution.record("delivery.es.video")["attempts"] == 1
    assert execution.record("delivery.pt-BR.video")["attempts"] == 1

def test_create_documentary_cannot_finish_after_final_delivery_verification_failure(
    tmp_path: Path,
) -> None:
    production, execution = _create(tmp_path)
    output = execution.output_path(
        station="localized_delivery_en",
        artifact_id="delivery.en.video",
    )
    output.write_bytes(b"tampered")

    with patch(
        "backend.studio.factory.documentary_factory.run_localized_deliveries",
    ), pytest.raises(RuntimeError, match=r"en.*delivery\.en\.video"):
        create_documentary(
            production.slug,
            production_factory=lambda _: production,
            historical_providers=[],
            visual_image_generator=_fake_image,
            visual_renderer=_fake_renderer,
            narration_retriever=_fake_narration,
            delivery_builder=_fake_delivery,
            delivery_media_validator=_fake_media,
        )

    assert production.session.payload["status"] == "failed"
def test_factory_visual_planning_populates_every_shot(tmp_path: Path) -> None:
    production, _ = _create(tmp_path)
    payload = json.loads(
        (production.work_root / "factory" / "shared" / "visual_plan.json").read_text(
            encoding="utf-8"
        )
    )

    for scene in payload["scenes"]:
        for shot in scene["visual_shots"]:
            assert shot["status"] == "prompt_ready"
            assert shot["visual_intent"].strip()
            assert "historical_search" in shot
            assert isinstance(shot["historical_plan"], dict)
            assert shot["prompt"].strip()


def test_visual_planner_is_called_once_per_incomplete_scene(tmp_path: Path) -> None:
    production = _multi_scene_production(tmp_path)
    execution = ProductionExecution(
        contract=production.session.adopt_documentary_production_contract(),
        work_root=production.work_root,
    )
    planned: list[int] = []

    def planner(**kwargs: object) -> list[dict[str, object]]:
        scene = kwargs["scene"]
        assert isinstance(scene, dict)
        planned.append(int(scene["scene_number"]))
        return _fake_visual_planner(**kwargs)  # type: ignore[arg-type]

    run_visual_planning(production, execution, visual_planner=planner)
    assert planned == [1, 2]


def test_partial_visual_plan_resumes_without_replanning_completed_scenes(tmp_path: Path) -> None:
    production = _multi_scene_production(tmp_path)
    execution = ProductionExecution(
        contract=production.session.adopt_documentary_production_contract(),
        work_root=production.work_root,
    )
    first_calls: list[int] = []

    def interrupted_planner(**kwargs: object) -> list[dict[str, object]]:
        scene = kwargs["scene"]
        assert isinstance(scene, dict)
        scene_number = int(scene["scene_number"])
        first_calls.append(scene_number)
        if scene_number == 2:
            raise RuntimeError("planner interrupted")
        return _fake_visual_planner(**kwargs)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="planner interrupted"):
        run_visual_planning(production, execution, visual_planner=interrupted_planner)

    output = execution.output_path(
        station=VISUAL_PLANNING_STATION,
        artifact_id=STORYBOARD_ARTIFACT,
    )
    partial = json.loads(output.read_text(encoding="utf-8"))
    assert first_calls == [1, 2]
    assert all(
        shot["status"] == "prompt_ready"
        for shot in partial["scenes"][0]["visual_shots"]
    )

    resumed_calls: list[int] = []

    def resumed_planner(**kwargs: object) -> list[dict[str, object]]:
        scene = kwargs["scene"]
        assert isinstance(scene, dict)
        resumed_calls.append(int(scene["scene_number"]))
        return _fake_visual_planner(**kwargs)  # type: ignore[arg-type]

    run_visual_planning(production, execution, visual_planner=resumed_planner)
    assert resumed_calls == [2]
    assert execution.record(STORYBOARD_ARTIFACT)["status"] == "completed"


def test_invalid_visual_planner_output_fails_canonical_artifact_concisely(tmp_path: Path) -> None:
    production = FakeProduction(tmp_path)
    execution = ProductionExecution(
        contract=production.session.adopt_documentary_production_contract(),
        work_root=production.work_root,
    )

    with pytest.raises(RuntimeError, match="expected shot numbers"):
        run_visual_planning(
            production,
            execution,
            visual_planner=lambda **_: [],
        )

    record = execution.record(STORYBOARD_ARTIFACT)
    assert record["status"] == "failed"
    assert record["error_summary"] == "RuntimeError: Scene 1: expected shot numbers [1, 2], received []."

def test_opening_video_is_verified_and_resume_skips_generation(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    opening = execution.output_path(station=VISUAL_RENDER_STATION, artifact_id=OPENING_VIDEO_ARTIFACT)
    assert execution.record(OPENING_VIDEO_ARTIFACT)["status"] == "completed"
    assert opening.read_bytes() == b"test opening"
    assert run_opening_render(production, execution, renderer=lambda *_: (_ for _ in ()).throw(AssertionError("must resume"))) is False


def test_localized_delivery_receives_full_legacy_visual_sequence_inputs(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    for language in SUPPORTED_LANGUAGE_CODES:
        execution.requeue_artifact(station=f"localized_delivery_{language}", artifact_id=f"delivery.{language}.video", reason="inspect inputs")
    calls: list[tuple[Path, Path, Path, tuple[Path, Path, Path]]] = []

    def builder(opening: Path, master: Path, brand: Path, tracks: tuple[Path, Path, Path], output: Path) -> None:
        calls.append((opening, master, brand, tracks))
        _fake_delivery(opening, master, brand, tracks, output)

    run_localized_deliveries(production, execution, builder=builder, media_validator=_fake_media)
    assert len(calls) == 3
    for opening, master, brand, tracks in calls:
        assert opening.name == "opening.mp4"
        assert master.name == "visual_master.mp4"
        assert brand.name == "old_dog_new_tracks.png"
        assert len(tracks) == 3


def test_opening_digest_change_rebuilds_all_localized_deliveries(tmp_path: Path) -> None:
    production, execution = _create(tmp_path)
    execution.requeue_artifact(station=VISUAL_RENDER_STATION, artifact_id=OPENING_VIDEO_ARTIFACT, reason="opening changed")
    run_opening_render(production, execution, renderer=lambda _, output: output.write_bytes(b"changed opening"))
    run_localized_deliveries(production, execution, builder=_fake_delivery, media_validator=_fake_media)
    for language in SUPPORTED_LANGUAGE_CODES:
        assert execution.record(f"delivery.{language}.video")["attempts"] == 2
def test_brand_digest_change_rebuilds_all_localized_deliveries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    production, execution = _create(tmp_path)
    from backend.studio.stations import build_localized_delivery

    original_digest = build_localized_delivery.digest

    def changed_brand_digest(path: Path) -> str:
        value = original_digest(path)
        return "changed-" + value if path.name == "old_dog_new_tracks.png" else value

    monkeypatch.setattr(build_localized_delivery, "digest", changed_brand_digest)
    run_localized_deliveries(production, execution, builder=_fake_delivery, media_validator=_fake_media)
    for language in SUPPORTED_LANGUAGE_CODES:
        assert execution.record(f"delivery.{language}.video")["attempts"] == 2