from __future__ import annotations

from pathlib import Path

import pytest

from backend.studio.factory import (
    ProductionExecution,
    create_documentary_production_contract,
)
from backend.studio.factory.delivery_package_verification import (
    verify_final_delivery_packages,
)
from backend.studio.factory.production_contract import SUPPORTED_LANGUAGE_CODES


def _execution(tmp_path: Path) -> ProductionExecution:
    return ProductionExecution(
        contract=create_documentary_production_contract("delivery_verification"),
        work_root=tmp_path / "work",
    )


def _complete(
    execution: ProductionExecution,
    *,
    station: str,
    artifact_id: str,
) -> Path:
    output = execution.start_artifact(station=station, artifact_id=artifact_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(artifact_id.encode("utf-8"))
    execution.complete_artifact(station=station, artifact_id=artifact_id)
    return output


def _complete_delivery_packages(tmp_path: Path) -> ProductionExecution:
    execution = _execution(tmp_path)
    for language_code in SUPPORTED_LANGUAGE_CODES:
        _complete(execution, station=f"localized_delivery_{language_code}", artifact_id=f"delivery.{language_code}.video")
        for segment in ("intro", "story", "outro"):
            _complete(execution, station=f"narration_{language_code}", artifact_id=f"delivery.{language_code}.narration.{segment}")
    return execution


def test_final_delivery_verification_accepts_all_three_packages(tmp_path: Path) -> None:
    execution = _complete_delivery_packages(tmp_path)

    packages = verify_final_delivery_packages(execution)

    assert tuple(package.language_code for package in packages) == SUPPORTED_LANGUAGE_CODES


def test_final_delivery_verification_returns_exactly_four_paths_per_language(tmp_path: Path) -> None:
    execution = _complete_delivery_packages(tmp_path)

    packages = verify_final_delivery_packages(execution)

    for package in packages:
        assert len(package.paths) == 4
        assert package.paths == (
            execution.output_path(station=f"localized_delivery_{package.language_code}", artifact_id=f"delivery.{package.language_code}.video"),
            execution.output_path(station=f"narration_{package.language_code}", artifact_id=f"delivery.{package.language_code}.narration.intro"),
            execution.output_path(station=f"narration_{package.language_code}", artifact_id=f"delivery.{package.language_code}.narration.story"),
            execution.output_path(station=f"narration_{package.language_code}", artifact_id=f"delivery.{package.language_code}.narration.outro"),
        )


@pytest.mark.parametrize("tamper", ("missing", "changed"))
def test_final_delivery_verification_rejects_missing_or_tampered_mp4(tmp_path: Path, tamper: str) -> None:
    execution = _complete_delivery_packages(tmp_path)
    output = execution.output_path(station="localized_delivery_en", artifact_id="delivery.en.video")
    if tamper == "missing":
        output.unlink()
    else:
        output.write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match=r"en.*delivery\.en\.video"):
        verify_final_delivery_packages(execution)


@pytest.mark.parametrize("segment", ("intro", "story", "outro"))
@pytest.mark.parametrize("tamper", ("missing", "changed"))
def test_final_delivery_verification_rejects_missing_or_tampered_narration(tmp_path: Path, segment: str, tamper: str) -> None:
    execution = _complete_delivery_packages(tmp_path)
    artifact_id = f"delivery.en.narration.{segment}"
    output = execution.output_path(station="narration_en", artifact_id=artifact_id)
    if tamper == "missing":
        output.unlink()
    else:
        output.write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match=rf"en.*{artifact_id}"):
        verify_final_delivery_packages(execution)
