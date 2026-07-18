from __future__ import annotations

from dataclasses import asdict
import time
import logging

from backend.state.playback_state import status

from fastapi import APIRouter, Body
from backend.services.spotify.spotify_auth_user import get_spotify_user_client

from backend.state.narration import narration_done_event

router = APIRouter(prefix="/playback", tags=["Playback Status"])
logger = logging.getLogger(__name__)

@router.post("/client-diagnostic")
async def client_diagnostic(diagnostic: dict = Body(...)):
    logger.info(
        "Client diagnostic event=%s phase=%s mode=%s programType=%s "
        "hasCurrentTrack=%s trackRank=%s decade=%s genre=%s",
        diagnostic.get("event"),
        diagnostic.get("phase"),
        diagnostic.get("mode"),
        diagnostic.get("programType"),
        diagnostic.get("hasCurrentTrack"),
        diagnostic.get("trackRank"),
        diagnostic.get("decade"),
        diagnostic.get("genre"),
    )
    return {"ok": True}


def update_track_clock():
    if status.is_playing and status.phase == "track":
        if status.track_start_ts is None:
            status.track_elapsed_seconds = 0
        else:
            status.track_elapsed_seconds = time.time() - status.track_start_ts


@router.get("/devices")
async def get_devices():
    """
    List available Spotify playback devices for the user.
    """
    sp = get_spotify_user_client()
    data = sp.devices()
    return {
        "devices": data.get("devices", [])
    }


@router.get("/status")
async def get_status():
    update_track_clock()

    snap = asdict(status)

    ctx = snap.get("context") or status.context or {}
    ctx["ranking_id"] = snap.get("current_ranking_id")

    # logger.info(f"📡 STATUS CONTEXT OUT: {ctx}")

    phase = snap.get("phase")
    voice_style = ctx.get("voice_style")

    # 🔥 Bed track control:
    # Backend only marks bed active.
    # Frontend actually plays bed_audio_url.
    if phase in ("set_intro", "liner", "intro", "detail", "artist") and voice_style == "before":
        if not getattr(status, "bed_playing", False):
            status.bed_playing = True
            logger.debug("🎧 Bed marked active; frontend will play bed_audio_url")

    # Otherwise do nothing here; bed is stopped explicitly by narration-finished

    # Pick which clock to expose
    if snap["phase"] == "track":
        elapsed_ms = int((snap.get("track_elapsed_seconds") or 0.0) * 1000)
        duration_ms = int((snap.get("track_duration_seconds") or 0.0) * 1000)
    else:
        elapsed_ms = int((snap.get("elapsed_seconds") or 0.0) * 1000)
        duration_ms = int((snap.get("duration_seconds") or 0.0) * 1000)

    progress = elapsed_ms / duration_ms if duration_ms > 0 else 0.0

    return {
        "isPlaying": snap.get("is_playing", False),
        "isPaused": snap.get("is_paused", False),
        "stopped": snap.get("stopped", False),
        "phase": phase,

        "track_name": snap.get("track_name"),
        "artist_name": snap.get("artist_name"),
        "current_rank": snap.get("current_rank"),

        # 🔥 ADD THIS — NARRATION FIELDS
        "intro": snap.get("intro"),
        "detail": snap.get("detail"),
        "artist_text": snap.get("artist_text"),

        # ✅ ADD THIS
        "totalTracks": snap.get("total_tracks"),

        # ⭐ ADD THESE (THIS IS THE FIX)
        "setNumber": ctx.get("set_number"),
        "blockPosition": ctx.get("block_position"),
        "blockSize": ctx.get("block_size"),

        "decadeSlug": ctx.get("decade_slug"),
        "genreSlug": ctx.get("genre_slug"),
        "decadeName": ctx.get("decade_name"),
        "genreName": ctx.get("genre_name"),

        "elapsedMs": elapsed_ms,
        "durationMs": duration_ms,
        "progress": progress,

        "context": ctx,
    }


@router.post("/transfer/{device_id}")
async def transfer_playback(device_id: str):
    """
    Force Spotify playback onto a specific device.
    """
    sp = get_spotify_user_client()
    sp.transfer_playback(device_id=device_id, force_play=True)
    return {"ok": True, "device_id": device_id}


@router.post("/narration-finished")
async def narration_finished():
    ctx = status.context or {}
    voice_style = ctx.get("voice_style")

    logger.info(
        "🔔 Narration finished signal received (phase=%s, voice_style=%s)",
        status.phase,
        voice_style
    )

    # 🛑 NEW: ignore if paused
    if status.is_paused:
        logger.info("⏸️ Ignoring narration-finished because system is paused")
        return {"ok": True}

    last_narration_phase = getattr(status, "last_narration_phase", None)

    should_stop_bed = (
            voice_style == "before"
            and getattr(status, "bed_playing", False)
            and (
                    not last_narration_phase
                    or status.phase == last_narration_phase
            )
    )

    if should_stop_bed:
        logger.debug("🔉 Marking bed as stopped (frontend will fade out)")
        status.bed_playing = False
    else:
        logger.debug(
            "🔁 Keeping narration bed running | phase=%s last=%s bed_playing=%s",
            status.phase,
            last_narration_phase,
            getattr(status, "bed_playing", False),
        )

    # ✅ ONLY fire event if NOT paused
    narration_done_event.set()

    return {"ok": True}


from backend.state.narration import track_done_event


@router.post("/track-finished")
async def track_finished(payload: dict = Body(default_factory=dict)):
    logger.info("🎵 Track finished signal received")
    logger.info(f"TRACK DONE EVENT ID (router): {id(track_done_event)}")

    current_phase = getattr(status, "phase", None)
    current_ranking_id = getattr(status, "current_ranking_id", None)
    current_spotify_id = getattr(status, "spotify_track_id", None)
    track_start_ts = getattr(status, "track_start_ts", None)

    track_age = None
    if track_start_ts is not None:
        track_age = time.time() - track_start_ts

    logger.info(
        "🎵 track-finished check: phase=%s ranking_id=%s spotify=%s track_age=%s",
        current_phase,
        current_ranking_id,
        current_spotify_id,
        round(track_age, 2) if track_age is not None else None,
    )

    if current_phase != "track":
        logger.info("🚫 Ignoring track-finished because phase=%s", current_phase)
        return {"ok": True, "ignored": True, "reason": "not_in_track_phase"}

    if track_start_ts is None:
        logger.info("🚫 Ignoring track-finished because track clock has not started")
        return {"ok": True, "ignored": True, "reason": "track_clock_not_started"}

    if track_age < 10:
        logger.info("🚫 Ignoring track-finished because track_age=%.2fs is too young", track_age)
        return {"ok": True, "ignored": True, "reason": "track_too_young"}

    payload_ranking_id = payload.get("ranking_id")
    payload_spotify_id = payload.get("spotify_track_id")

    if payload_ranking_id is not None and current_ranking_id is not None:
        if int(payload_ranking_id) != int(current_ranking_id):
            logger.info(
                "🚫 Ignoring stale track-finished because ranking_id payload=%s current=%s",
                payload_ranking_id,
                current_ranking_id,
            )
            return {"ok": True, "ignored": True, "reason": "stale_ranking_id"}

    if payload_spotify_id and current_spotify_id:
        if payload_spotify_id != current_spotify_id:
            logger.info(
                "🚫 Ignoring stale track-finished because spotify payload=%s current=%s",
                payload_spotify_id,
                current_spotify_id,
            )
            return {"ok": True, "ignored": True, "reason": "stale_spotify_id"}

    track_done_event.set()

    return {"ok": True}
