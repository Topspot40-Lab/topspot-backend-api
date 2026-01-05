# backend/routers/spotify_auth.py
from __future__ import annotations

import os
import logging
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse

from backend.services.spotify.spotify_auth_user import _build_auth_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/spotify", tags=["Spotify Auth"])


@router.get("/debug-config")
def debug_config():
    """Show the exact values Spotipy will use (helps fix INVALID_CLIENT)."""
    return JSONResponse({
        "client_id": os.getenv("SPOTIPY_CLIENT_ID") or os.getenv("SPOTIFY_CLIENT_ID"),
        "redirect_uri": os.getenv("SPOTIPY_REDIRECT_URI"),
        "scopes": os.getenv("SPOTIFY_SCOPES"),
    })


@router.get("/authorize")
def authorize(debug: int = Query(0, description="1 = return URL JSON instead of redirect")):
    """
    Start OAuth. With ?debug=1 returns {"authorize_url": "..."} so you can inspect/copy it.
    Otherwise, redirects the browser to Spotify.
    """
    am = _build_auth_manager(open_browser=False)  # never auto-open; we control the flow here
    url = am.get_authorize_url()
    if debug:
        return JSONResponse({"authorize_url": url})
    return RedirectResponse(url)


@router.get("/callback")
def callback(request: Request):
    """
    Spotify redirects here with ?code=... (or ?error=...).
    Exchanges the code for an access/refresh token, which is cached to .cache-topspot.
    """
    q = dict(request.query_params)
    if (err := q.get("error")):
        raise HTTPException(400, f"OAuth error from Spotify: {err}")

    code = q.get("code")
    if not code:
        raise HTTPException(400, "Missing 'code'")

    am = _build_auth_manager(open_browser=False)

    # Try once; if cache decode fails mid-flow, wipe and retry once.
    try:
        token_info = am.get_access_token(code)  # writes .cache-topspot
    except Exception as e:
        logger.warning("First token exchange failed (%s). Retrying after cache wipe...", e)
        try:
            # If using CacheFileHandler with 'cache_path', nuke it to fix JSON decode/corruption.
            ch = getattr(am, "cache_handler", None)
            cache_path = getattr(ch, "cache_path", None) if ch else None
            if cache_path:
                Path(cache_path).unlink(missing_ok=True)
        except Exception:
            pass
        token_info = am.get_access_token(code)

    if not token_info or "access_token" not in token_info:
        raise HTTPException(400, "Token exchange failed")

    return HTMLResponse(
        "<p>Spotify authentication complete. You can close this window.</p>"
    )


@router.get("/whoami")
def whoami():
    """
    Quick sanity check that the cached token works.
    Returns your Spotify user id/display name or 401 if not authorized.
    """
    import spotipy
    am = _build_auth_manager(open_browser=False)
    sp = spotipy.Spotify(auth_manager=am)
    me = sp.current_user()  # raises on 401/invalid token
    return {"id": me.get("id"), "name": me.get("display_name")}
