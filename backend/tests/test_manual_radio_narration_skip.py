import asyncio

import pytest

from backend.routers import playback_status
from backend.state.manual_radio_skip import (
    ManualRadioSkipTarget,
    wait_for_radio_event_or_manual_skip,
)
from backend.state.playback_state import get_status


@pytest.mark.parametrize("mode", ["all_radio", "collections_radio", "artist_radio"])
@pytest.mark.parametrize("phase", ["intro", "detail", "artist"])
def test_manual_radio_narration_skip_is_scoped_and_wakes_only_its_track(monkeypatch, mode, phase):
    user_id = f"manual-radio-{mode}-{phase}"
    status = get_status(user_id)
    status.playback_session_id = "session-1"
    status.phase = phase
    status.current_ranking_id = 17
    status.spotify_track_id = "spotify-17"
    status.context = {"mode": mode, "ranking_id": 17, "spotify_track_id": "spotify-17"}
    monkeypatch.setattr(playback_status, "current_user_id", lambda: user_id)

    async def scenario():
        waiting = asyncio.create_task(wait_for_radio_event_or_manual_skip(
            user_id, asyncio.Event(), ManualRadioSkipTarget("session-1", 17, "spotify-17")
        ))
        await asyncio.sleep(0)
        result = await playback_status.skip_radio_track(
            playback_status.ManualRadioSkipRequest(
                playbackSessionId="session-1", phase=phase,
                ranking_id=17, spotify_track_id="spotify-17",
            )
        )
        assert result == {"ok": True, "accepted": True, "ignored": False, "reason": None}
        assert await waiting is True

    asyncio.run(scenario())


def test_manual_radio_skip_rejects_stale_mismatched_duplicate_and_non_narration(monkeypatch):
    user_id = "manual-radio-validation"
    status = get_status(user_id)
    status.playback_session_id = "session-current"
    status.phase = "detail"
    status.current_ranking_id = 9
    status.spotify_track_id = "spotify-9"
    status.context = {"mode": "artist_radio", "ranking_id": 9, "spotify_track_id": "spotify-9"}
    monkeypatch.setattr(playback_status, "current_user_id", lambda: user_id)

    async def call(**overrides):
        return await playback_status.skip_radio_track(playback_status.ManualRadioSkipRequest(
            playbackSessionId=overrides.get("session", "session-current"),
            phase=overrides.get("phase", "detail"),
            ranking_id=overrides.get("ranking", 9),
            spotify_track_id=overrides.get("spotify", "spotify-9"),
        ))

    assert asyncio.run(call(session="stale"))["reason"] == "stale_session"
    assert asyncio.run(call(ranking=10))["reason"] == "track_mismatch"
    assert asyncio.run(call()) ["accepted"] is True
    assert asyncio.run(call())["reason"] == "duplicate"
    status.phase = "track"
    assert asyncio.run(call(phase="track"))["reason"] == "not_narration_phase"
