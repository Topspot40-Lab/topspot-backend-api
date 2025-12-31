# backend/services/spotify/spotify_auth_user.py
from __future__ import annotations

import os
import logging
from pathlib import Path

from dotenv import load_dotenv
import spotipy
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import CacheFileHandler

logger = logging.getLogger(__name__)

# ── Load .env from repo root once (non-destructive) ──────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env", override=False)

# Stable, absolute cache path (prevents random working-dir issues)
CACHE_PATH = REPO_ROOT / ".cache-topspot"

# Minimal, valid scopes for server-side playback control
# (Add 'streaming' later only if you embed the Web Playback SDK in a browser.)
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"

_auth_manager: SpotifyOAuth | None = None
_client: Spotify | None = None


def _clean(s: str | None) -> str | None:
    """Trim whitespace and surrounding quotes from env values."""
    if s is None:
        return None
    s = s.strip()
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        s = s[1:-1].strip()
    return s


def _build_auth_manager(open_browser: bool = False) -> SpotifyOAuth:
    """
    Build a SpotifyOAuth with explicit, known-good params so Spotipy doesn't guess.
    """
    cid = _clean(os.getenv("SPOTIPY_CLIENT_ID") or os.getenv("SPOTIFY_CLIENT_ID"))
    secret = _clean(os.getenv("SPOTIPY_CLIENT_SECRET") or os.getenv("SPOTIFY_CLIENT_SECRET"))
    redirect = _clean(os.getenv("SPOTIPY_REDIRECT_URI"))

    if not cid or not secret or not redirect:
        raise EnvironmentError("Missing SPOTIPY_CLIENT_ID / SPOTIPY_CLIENT_SECRET / SPOTIPY_REDIRECT_URI")

    # DEBUG breadcrumb: last 6 chars of client id; exact redirect
    logger.info("SpotifyOAuth init | client=%s | redirect=%s | cache=%s",
                f"...{cid[-6:]}", redirect, CACHE_PATH)

    cache_handler = CacheFileHandler(cache_path=str(CACHE_PATH))

    return SpotifyOAuth(
        client_id=cid,
        client_secret=secret,
        redirect_uri=redirect,     # MUST match Spotify Dashboard exactly
        scope=SCOPES,              # known-good scopes (no quotes)
        cache_handler=cache_handler,
        open_browser=open_browser, # keep False for server routes
        show_dialog=False,
    )


def get_spotify_user_client(allow_prompt: bool = False) -> Spotify:
    """
    Return a Spotipy client using a cached USER token.
    - If no cached token and allow_prompt=False, raise a RuntimeError (so routes can instruct user to /spotify/authorize).
    - If allow_prompt=True (CLI only), the OAuth flow may open a browser.
    """
    global _client, _auth_manager
    if _client is not None:
        return _client

    _auth_manager = _build_auth_manager(open_browser=allow_prompt)

    token_info = _auth_manager.get_cached_token()
    if not token_info:
        raise RuntimeError(
            "No Spotify user token found in cache. "
            "Visit /spotify/authorize to sign in, or run an auth flow to populate "
            f"{CACHE_PATH}"
        )

    _client = spotipy.Spotify(auth_manager=_auth_manager)
    logger.debug("✅ Spotify user-auth client ready (cache=%s)", CACHE_PATH)
    return _client


# Optional: handy introspection for your /spotify/debug-config route
def current_oauth_config() -> dict[str, str | None]:
    return {
        "client_id_tail": (os.getenv("SPOTIPY_CLIENT_ID") or os.getenv("SPOTIFY_CLIENT_ID") or "")[-6:] or None,
        "redirect_uri": _clean(os.getenv("SPOTIPY_REDIRECT_URI")),
        "scopes": SCOPES,
        "cache_path": str(CACHE_PATH),
    }
