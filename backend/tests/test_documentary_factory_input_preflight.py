from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.studio.factory.documentary_factory import create_documentary
from backend.studio.factory.input_preflight import (
    FactoryInputPreflightError,
    validate_factory_inputs,
)
from backend.studio.factory.production_contract import SUPPORTED_LANGUAGE_CODES
from backend.studio.factory.production_session import ProductionSession


def _language(language_code: str, **changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "language_code": language_code,
        "story_text": f"{language_code} story.",
        "duration_seconds": 30,
        "tts_bucket": f"audio-{language_code}",
        "tts_key": f"stories/{language_code}.mp3",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _documentary(*languages: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(languages=languages)


def _valid_documentary() -> SimpleNamespace:
    return _documentary(*(_language(code) for code in SUPPORTED_LANGUAGE_CODES))


@pytest.mark.parametrize(
    ("language_code", "changes", "expected_failure"),
    [
        ("en", {"story_text": "  "}, "en: story_text is missing or blank"),
        (
            "es",
            {"duration_seconds": 0},
            "es: duration_seconds must be greater than zero",
        ),
        ("pt-BR", {"tts_bucket": None}, "pt-BR: tts_bucket is missing or blank"),
        ("en", {"tts_key": ""}, "en: tts_key is missing or blank"),
    ],
)
def test_validate_factory_inputs_rejects_invalid_required_field(
    language_code: str,
    changes: dict[str, object],
    expected_failure: str,
) -> None:
    languages = [
        _language(code, **changes) if code == language_code else _language(code)
        for code in SUPPORTED_LANGUAGE_CODES
    ]

    with pytest.raises(FactoryInputPreflightError, match=expected_failure):
        validate_factory_inputs(_documentary(*languages))


def test_validate_factory_inputs_accepts_all_required_languages() -> None:
    validate_factory_inputs(_valid_documentary())


def test_validate_factory_inputs_reports_missing_language() -> None:
    documentary = _documentary(_language("en"), _language("pt-BR"))

    with pytest.raises(
        FactoryInputPreflightError,
        match="es: language is missing",
    ):
        validate_factory_inputs(documentary)


def test_validate_factory_inputs_aggregates_failures_deterministically() -> None:
    documentary = _documentary(
        _language("en", story_text=""),
        _language("es", duration_seconds=-1, tts_bucket=""),
    )

    with pytest.raises(FactoryInputPreflightError) as raised:
        validate_factory_inputs(documentary)

    assert str(raised.value) == (
        "Factory input preflight failed: "
        "en: story_text is missing or blank; "
        "es: duration_seconds must be greater than zero; "
        "es: tts_bucket is missing or blank; "
        "pt-BR: language is missing"
    )


class _PreflightProduction:
    slug = "preflight_failure"

    def __init__(self, tmp_path: Path) -> None:
        self.work_root = tmp_path / "work"
        self.documentary = _documentary(_language("en"))
        self.session = ProductionSession(
            production_slug=self.slug,
            work_root=self.work_root,
        )


def test_create_documentary_does_not_start_visual_planning_after_preflight_failure(
    tmp_path: Path,
) -> None:
    production = _PreflightProduction(tmp_path)

    with patch(
        "backend.studio.factory.documentary_factory.run_visual_planning",
        side_effect=AssertionError("visual planning must not run"),
    ) as visual_planning:
        with pytest.raises(FactoryInputPreflightError):
            create_documentary(
                production.slug,
                production_factory=lambda _: production,
            )

    visual_planning.assert_not_called()
    assert not (production.work_root / "factory" / "shared").exists()
    assert production.session.payload["status"] == "idle"
