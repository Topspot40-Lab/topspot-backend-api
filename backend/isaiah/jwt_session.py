# backend/isaiah/jwt_session.py
# After authenticating the user's spotify premium account, it should allow front end
# know to keep them logged in
import jwt
from datetime import datetime, timedelta, timezone
import secrets
import os

JWT_SECRET = os.environ.get("JWT_SECRET")
JWT_ALGORITHM = "HS256"
JWT_EXP_DELTA_SECONDS = 3600 * 24 * 7 # 7 day token expiry
PLAYBACK_GUEST_JWT_EXP_SECONDS = 3600 * 6


def create_jwt_token(user_id: str):
    payload = {
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=JWT_EXP_DELTA_SECONDS),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def create_playback_guest_token(guest_id: str):
    payload = {
        "purpose": "playback_guest",
        "guest_id": guest_id,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=PLAYBACK_GUEST_JWT_EXP_SECONDS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _playback_guest_jwt_secret(), algorithm=JWT_ALGORITHM)

def decode_jwt_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def decode_playback_guest_token(token: str):
    try:
        payload = jwt.decode(token, _playback_guest_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
    if not payload or payload.get("purpose") != "playback_guest":
        return None
    guest_id = payload.get("guest_id")
    return payload if isinstance(guest_id, str) and guest_id else None


def _playback_guest_jwt_secret() -> str:
    """Use a separately configurable guest signer without weakening account JWTs."""
    secret = os.environ.get("PLAYBACK_GUEST_JWT_SECRET") or JWT_SECRET
    if not secret:
        raise RuntimeError("Missing PLAYBACK_GUEST_JWT_SECRET for guest playback")
    return secret
