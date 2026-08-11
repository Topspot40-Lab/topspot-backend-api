from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.scripts.upload_youtube_release import (
    _is_quota_error,
    _positive_int,
    _select_batch,
)
from backend.studio.youtube.auth import SCOPES


def _spec(slug: str, language: str) -> SimpleNamespace:
    return SimpleNamespace(slug=slug, language_code=language)


def test_batch_limit_skips_completed_uploads() -> None:
    specs = [_spec("one", "en"), _spec("one", "es"), _spec("one", "pt-BR")]
    uploads = {"one|en": {"status": "uploaded"}}
    selected = _select_batch(specs, uploads, 1)
    assert [(item.slug, item.language_code) for item in selected] == [("one", "es")]


def test_batch_limit_defaults_are_positive() -> None:
    assert _positive_int("15") == 15
    with pytest.raises(Exception):
        _positive_int("0")


def test_quota_error_detection() -> None:
    error = RuntimeError("quotaExceeded")
    error.resp = SimpleNamespace(status=403)  # type: ignore[attr-defined]
    assert _is_quota_error(error) is True


def test_non_quota_error_is_not_misclassified() -> None:
    error = RuntimeError("forbidden")
    error.resp = SimpleNamespace(status=403)  # type: ignore[attr-defined]
    assert _is_quota_error(error) is False


def test_caption_scope_is_requested() -> None:
    assert "https://www.googleapis.com/auth/youtube.force-ssl" in SCOPES
