"""Signed, browser-bound anonymous identity for protected playback routes."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Cookie
from fastapi.responses import JSONResponse

from backend.isaiah.isaiah_helper import get_env_config
from backend.isaiah.jwt_session import PLAYBACK_GUEST_JWT_EXP_SECONDS, create_playback_guest_token
from backend.state.playback_runtime import (
    account_identity_from_token,
    cleanup_inactive_guest_runtimes,
    guest_identity_from_token,
)


router = APIRouter(prefix="/playback", tags=["Playback Guest Session"])
cookie_config = get_env_config()


@router.post("/guest-session")
async def establish_guest_playback_session(
        access_token: str | None = Cookie(None),
        playback_guest: str | None = Cookie(None),
):
    """Create a signed guest cookie; the opaque identity never enters JSON."""
    cleanup_inactive_guest_runtimes()

    if account_identity_from_token(access_token):
        return {"ok": True, "authenticated": True}
    if guest_identity_from_token(playback_guest):
        return {"ok": True, "authenticated": False}

    token = create_playback_guest_token(secrets.token_urlsafe(32))
    response = JSONResponse({"ok": True, "authenticated": False})
    response.set_cookie(
        key="playback_guest",
        value=token,
        httponly=True,
        secure=cookie_config["SECURE_COOKIE"],
        samesite=cookie_config["SAMESITE"],
        max_age=PLAYBACK_GUEST_JWT_EXP_SECONDS,
        path="/",
        domain=cookie_config["COOKIE_DOMAIN"],
    )
    return response
