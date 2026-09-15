import asyncio
import time
from http.cookies import SimpleCookie

import pytest

from backend.isaiah import jwt_session
from backend.routers import playback_guest
from backend.state import playback_runtime
from backend.state.narration import track_done_event
from backend.state.playback_state import get_status, statuses


def _cookie_value(response):
    cookies = SimpleCookie()
    cookies.load(response.headers["set-cookie"])
    return cookies["playback_guest"].value


def test_guest_browsers_receive_distinct_signed_identities_and_isolated_runtime(monkeypatch):
    monkeypatch.setattr(jwt_session, "JWT_SECRET", "guest-playback-test-secret")
    monkeypatch.setattr(
        playback_guest,
        "cookie_config",
        {"COOKIE_DOMAIN": None, "SECURE_COOKIE": False, "SAMESITE": "lax"},
    )
    playback_runtime.runtime_by_user.clear()
    statuses.clear()

    first_bootstrap = asyncio.run(playback_guest.establish_guest_playback_session(None, None))
    second_bootstrap = asyncio.run(playback_guest.establish_guest_playback_session(None, None))

    assert first_bootstrap.status_code == 200
    assert second_bootstrap.status_code == 200
    assert b"guest_id" not in first_bootstrap.body
    assert "HttpOnly" in first_bootstrap.headers["set-cookie"]

    identity_a = playback_runtime.guest_identity_from_token(_cookie_value(first_bootstrap))
    identity_b = playback_runtime.guest_identity_from_token(_cookie_value(second_bootstrap))
    assert identity_a and identity_b and identity_a != identity_b
    assert identity_a.startswith("guest:")
    assert identity_b.startswith("guest:")

    # Simulate browser A's protected start/status state. Browser B resolves to
    # a different signed principal and therefore cannot read or signal it.
    state_a = get_status(identity_a)
    state_a.phase = "track"
    state_a.track_start_ts = time.time() - 11
    state_a.track_name = "Only this browser's track"
    state_b = get_status(identity_b)
    assert state_b.track_name == ""
    assert state_b.phase == "idle"
    track_done_event(identity_b).set()
    assert track_done_event(identity_a).is_set() is False

    with pytest.raises(Exception) as no_cookie:
        playback_runtime.resolve_playback_identity(None, None)
    assert getattr(no_cookie.value, "status_code", None) == 401


def test_valid_account_identity_wins_over_a_guest_cookie(monkeypatch):
    monkeypatch.setattr(
        playback_runtime,
        "decode_jwt_token",
        lambda token: {"user_id": "account-123"} if token == "account-token" else None,
    )
    monkeypatch.setattr(
        playback_runtime,
        "decode_playback_guest_token",
        lambda token: {"purpose": "playback_guest", "guest_id": "guest-123"},
    )

    assert playback_runtime.resolve_playback_identity("account-token", "guest-token") == "user:account-123"
    assert playback_runtime.resolve_playback_identity(None, "guest-token") == "guest:guest-123"


def test_expired_guest_runtime_cleanup_never_removes_account_runtime(monkeypatch):
    playback_runtime.runtime_by_user.clear()
    statuses.clear()
    account = playback_runtime.get_runtime_for_user("user:account-123")
    guest = playback_runtime.get_runtime_for_user("guest:expired-guest")
    statuses["user:account-123"] = account.status
    statuses["guest:expired-guest"] = guest.status
    account.status.last_action_ts = 1
    guest.status.last_action_ts = 1

    playback_runtime.cleanup_inactive_guest_runtimes(
        now=1 + playback_runtime.GUEST_RUNTIME_IDLE_SECONDS + 1
    )

    assert "guest:expired-guest" not in playback_runtime.runtime_by_user
    assert "user:account-123" in playback_runtime.runtime_by_user
