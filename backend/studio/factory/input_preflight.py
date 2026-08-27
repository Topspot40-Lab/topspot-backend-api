"""Pure validation of source inputs required by the documentary factory."""

from __future__ import annotations

from backend.studio.documentary import Documentary
from backend.studio.factory.production_contract import SUPPORTED_LANGUAGE_CODES


class FactoryInputPreflightError(ValueError):
    """Raised when a factory run lacks required localized source inputs."""


def _is_nonblank(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_positive_duration(value: int | None) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_factory_inputs(documentary: Documentary) -> None:
    """Validate every required localized input before factory work begins.

    The checks only inspect the already-loaded documentary model, so a failure
    cannot start visual work or contact a source service.
    """
    languages_by_code = {
        language.language_code: language
        for language in documentary.languages
    }
    failures: list[str] = []

    for language_code in SUPPORTED_LANGUAGE_CODES:
        language = languages_by_code.get(language_code)
        if language is None:
            failures.append(f"{language_code}: language is missing")
            continue

        if not _is_nonblank(language.story_text):
            failures.append(f"{language_code}: story_text is missing or blank")
        if not _has_positive_duration(language.duration_seconds):
            failures.append(
                f"{language_code}: duration_seconds must be greater than zero"
            )
        if not _is_nonblank(language.tts_bucket):
            failures.append(f"{language_code}: tts_bucket is missing or blank")
        if not _is_nonblank(language.tts_key):
            failures.append(f"{language_code}: tts_key is missing or blank")

    if failures:
        raise FactoryInputPreflightError(
            "Factory input preflight failed: " + "; ".join(failures)
        )
