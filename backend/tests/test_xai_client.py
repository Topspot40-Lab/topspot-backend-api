from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from backend.services import xai_client


def test_ask_xai_uses_extended_read_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return SimpleNamespace(
            ok=True,
            json=lambda: {
                "choices": [
                    {"message": {"content": " planned response "}}
                ]
            },
        )

    monkeypatch.setattr(xai_client, "XAI_API_KEY", "test-key")
    monkeypatch.setattr(xai_client.requests, "post", fake_post)

    result = xai_client.ask_xai("system", "user")

    assert result == "planned response"
    assert captured["timeout"] == (10, 180)


def test_ask_xai_redacts_non_ok_response_details(monkeypatch, capsys) -> None:
    sensitive_body = "provider body: prompt=system secret-token request-id=abc123"
    sensitive_url = "https://api.x.ai/v1/chat/completions?key=secret"
    response = SimpleNamespace(ok=False, status_code=503)

    def raise_for_status() -> None:
        raise requests.HTTPError(
            f"503 Server Error: {sensitive_body} for url: {sensitive_url}",
            response=response,
        )

    response.raise_for_status = raise_for_status
    monkeypatch.setattr(xai_client, "XAI_API_KEY", "test-key")
    monkeypatch.setattr(xai_client.requests, "post", lambda *args, **kwargs: response)

    with pytest.raises(requests.HTTPError) as exc_info:
        xai_client.ask_xai("system prompt secret", "user prompt secret")

    captured = capsys.readouterr()
    assert exc_info.value.response is response
    assert exc_info.value.response.status_code == 503
    assert str(exc_info.value) == "xAI request failed (HTTP 503)"
    assert captured.out == "xAI request failed (HTTP 503)\n"
    assert sensitive_body not in captured.out
    assert sensitive_url not in captured.out
    assert sensitive_body not in str(exc_info.value)
    assert sensitive_url not in str(exc_info.value)
