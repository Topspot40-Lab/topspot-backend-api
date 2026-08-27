import logging
import time
from types import SimpleNamespace

import pytest

from backend.routers import playback_control, playback_status
from backend.state import playback_state


class _UnsafeDict(dict):
    def items(self):
        raise AssertionError("diagnostic logging must not iterate a dict subclass")


class _IntSubclass(int):
    pass


@pytest.mark.asyncio
async def test_play_track_language_diagnostic_never_logs_client_values(monkeypatch, caplog):
    sentinel_url = "https://private.example/tts?token=language-secret"
    sentinel_token = "language-token-sentinel"
    payload = {
        "track": {
            "track_id": "track-id",
            "spotify_track_id": "spotify-id",
            "track_name": "Track",
            "artist_name": "Artist",
        },
        "selection": {
            "language": "en",
            "languages": [sentinel_url, sentinel_token],
            "voices": [],
            "voicePlayMode": "standard",
            "pauseMode": "none",
        },
        "context": {"type": "decade_genre", "decade": "all", "genre": "pop"},
    }
    phase_updates = []

    monkeypatch.setattr(playback_control, "current_user_id", lambda: "diagnostic-user")
    monkeypatch.setattr(playback_control, "current_runtime", lambda: SimpleNamespace(status=object()))
    monkeypatch.setattr(playback_control, "reset_for_single_track", lambda: None)
    monkeypatch.setattr(playback_control, "update_phase", lambda *args, **kwargs: phase_updates.append((args, kwargs)))

    with caplog.at_level(logging.INFO, logger=playback_control.__name__):
        response = await playback_control.play_track(payload)

    message = "\n".join(record.getMessage() for record in caplog.records)
    assert response == {"ok": True, "message": "ALL decade direct playback"}
    assert len(phase_updates) == 1
    assert "languages_is_builtin_list=True languages_item_count=2" in message
    assert sentinel_url not in message
    assert sentinel_token not in message


def test_diagnostic_state_summary_rejects_dict_subclasses_without_coercion():
    assert playback_status._sanitize_diagnostic_state(_UnsafeDict()) == "[unsupported]"
    assert playback_status._exact_int_or_zero(True) == 0
    assert playback_status._exact_int_or_zero(_IntSubclass(7)) == 0
    assert playback_status._sanitize_diagnostic_state({"duration": 1.5}) == {"duration": 1}


@pytest.mark.asyncio
async def test_client_diagnostic_logs_fixed_labels_and_sanitized_state(caplog):
    diagnostic = playback_status.ClientDiagnosticRequest(
        event="client supplied event",
        phase="client supplied phase",
        mode="client supplied mode",
        programType="client supplied program",
        hasCurrentTrack=True,
        trackRank=7,
        decade="client supplied decade",
        genre="client supplied genre",
        bedAudioState={
            "state": "client-state-sentinel",
            "message": "narration-sentinel",
            "connection": "https://private.example/audio",
            "session": "session-sentinel",
        },
        narrationAudioState={"errorCode": "NETWORK", "reason": "reason-sentinel"},
    )

    with caplog.at_level(logging.INFO, logger=playback_status.__name__):
        assert await playback_status.client_diagnostic(diagnostic) == {"ok": True}

    message = caplog.records[-1].getMessage()
    assert "event=other phase=other mode=other programType=other" in message
    assert "hasCurrentTrack=True trackRank=7 decade=provided genre=provided" in message
    assert "client supplied" not in message
    for sentinel in (
        "https://private.example/audio",
        "client-state-sentinel",
        "narration-sentinel",
        "session-sentinel",
        "NETWORK",
        "reason-sentinel",
    ):
        assert sentinel not in message
    assert "bedAudioState={'state': 'other', 'other_field_count': 3}" in message
    assert "narrationAudioState={'errorCode': 'other', 'other_field_count': 1}" in message


def test_stale_phase_log_uses_session_presence_not_session_values(caplog):
    user_id = "playback-diagnostic-log-test"
    incoming_session_id = "incoming-session-secret"
    current_session_id = "current-session-secret"
    status = playback_state.get_status(user_id)
    status.playback_session_id = current_session_id

    try:
        with caplog.at_level(logging.INFO, logger=playback_state.__name__):
            playback_state.update_phase(
                user_id,
                "track",
                playback_session_id=incoming_session_id,
            )
    finally:
        playback_state.statuses.pop(user_id, None)

    message = caplog.records[-1].getMessage()
    assert "operation=phase_update incoming_session_present=True current_session_present=True" in message
    for sentinel in (incoming_session_id, current_session_id, "incoming-session", "current-session"):
        assert sentinel not in message
    assert status.phase == "idle"


@pytest.mark.asyncio
async def test_track_finished_logs_only_identifier_presence_and_preserves_completion(monkeypatch, caplog):
    user_id = "playback-track-diagnostic-log-test"
    status = playback_state.get_status(user_id)
    status.phase = "track"
    status.current_ranking_id = 314159
    status.spotify_track_id = "spotify-track-sentinel"
    status.track_start_ts = time.time() - 11

    class Event:
        set_called = False

        def set(self):
            self.set_called = True

    event = Event()
    monkeypatch.setattr(playback_status, "current_user_id", lambda: user_id)
    monkeypatch.setattr(playback_status, "track_done_event", lambda _: event)

    try:
        with caplog.at_level(logging.INFO, logger=playback_status.__name__):
            assert await playback_status.track_finished() == {"ok": True}
    finally:
        playback_state.statuses.pop(user_id, None)

    message = "\n".join(record.getMessage() for record in caplog.records)
    assert event.set_called is True
    assert "has_ranking_id=True has_spotify_track=True" in message
    assert "spotify-track-sentinel" not in message
    assert "314159" not in message
