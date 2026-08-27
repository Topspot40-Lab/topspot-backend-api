from __future__ import annotations

from types import SimpleNamespace

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
