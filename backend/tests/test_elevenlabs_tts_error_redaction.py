import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.tts import elevenlabs_tts


def test_generate_tts_mp3_success_writes_response_bytes_and_returns_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "requested.mp3"
    response_bytes = b"mp3-bytes"
    request_calls: list[dict[str, object]] = []
    monkeypatch.setattr(elevenlabs_tts, "ELEVENLABS_API_KEY", "test-api-key")
    monkeypatch.setattr(
        elevenlabs_tts.requests,
        "post",
        lambda *args, **kwargs: (
            request_calls.append({"args": args, "kwargs": kwargs})
            or SimpleNamespace(status_code=200, content=response_bytes)
        ),
    )

    result = elevenlabs_tts.generate_tts_mp3(
        text="narration",
        out_path=destination,
        voice_id="voice-id",
    )

    assert result == str(destination)
    assert destination.read_bytes() == response_bytes
    assert len(request_calls) == 1
    request = request_calls[0]
    assert request["args"] == ("https://api.elevenlabs.io/v1/text-to-speech/voice-id",)
    assert request["kwargs"] == {
        "headers": {
            "xi-api-key": "test-api-key",
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        "data": json.dumps(
            {
                "text": "narration",
                "model_id": elevenlabs_tts.ELEVENLABS_MODEL,
                "voice_settings": {
                    "stability": elevenlabs_tts.VOICE_STABILITY,
                    "similarity_boost": elevenlabs_tts.VOICE_SIMILARITY,
                },
            }
        ),
        "timeout": (10.0, 120.0),
    }


def test_generate_tts_mp3_failure_redacts_sensitive_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    narration = "private narration text"
    voice_id = "private-voice-id"
    api_key = "private-api-key"
    destination = tmp_path / "private-output.mp3"
    response_text = "private provider response"
    monkeypatch.setattr(elevenlabs_tts, "ELEVENLABS_API_KEY", api_key)
    monkeypatch.setattr(
        elevenlabs_tts.requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(status_code=429, text=response_text),
    )

    with pytest.raises(RuntimeError) as exc_info:
        elevenlabs_tts.generate_tts_mp3(
            text=narration,
            out_path=destination,
            voice_id=voice_id,
        )

    assert str(exc_info.value) == "ElevenLabs TTS request failed (HTTP 429)"
    captured = capsys.readouterr()
    exposed_output = caplog.text + captured.out + captured.err + str(exc_info.value)
    for sensitive_value in (response_text, narration, voice_id, api_key, str(destination)):
        assert sensitive_value not in exposed_output


def test_generate_tts_mp3_sanitizes_request_exception(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sensitive_error = "provider exception with private-api-key"
    monkeypatch.setattr(elevenlabs_tts, "ELEVENLABS_API_KEY", "private-api-key")
    monkeypatch.setattr(
        elevenlabs_tts.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(elevenlabs_tts.requests.ConnectionError(sensitive_error)),
    )

    with pytest.raises(RuntimeError, match="^ElevenLabs TTS request failed$") as exc_info:
        elevenlabs_tts.generate_tts_mp3(
            text="private narration",
            out_path=tmp_path / "private-output.mp3",
            voice_id="private-voice-id",
        )

    assert sensitive_error not in str(exc_info.value)
