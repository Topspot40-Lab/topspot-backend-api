# backend/routers/playback_status.py
from __future__ import annotations

from dataclasses import asdict
import math
import time
import logging
from typing import Any, Optional


from backend.state.playback_state import get_status as get_playback_status

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.state.narration import narration_done_event, track_done_event
from backend.state.playback_runtime import bind_request_user, current_user_id

router = APIRouter(
    prefix="/playback",
    tags=["Playback Status"],
    dependencies=[Depends(bind_request_user)],
)
logger = logging.getLogger(__name__)


_PLAYBACK_PHASE_LABELS = frozenset({
    "idle", "loading", "prelude", "set_intro", "liner", "intro", "detail",
    "artist", "track", "ended", "music",
})
_PLAYBACK_MODE_LABELS = frozenset({"decade_genre", "collection"})
_PROGRAM_TYPE_LABELS = frozenset({"RADIO_ARTIST"})
_CLIENT_DIAGNOSTIC_EVENT_LABELS = frozenset()
_VOICE_STYLE_LABELS = frozenset({"before", "after"})
_DIAGNOSTIC_AUDIO_STATE_KEYS = frozenset({
    "state", "errorCode", "paused", "ended", "muted", "seeking",
    "currentTime", "duration", "readyState", "networkState",
})
_DIAGNOSTIC_AUDIO_STATE_LABELS = frozenset({"idle", "loading", "playing", "paused", "ended"})
_DIAGNOSTIC_AUDIO_ERROR_LABELS = frozenset({
    "MEDIA_ERR_ABORTED", "MEDIA_ERR_NETWORK", "MEDIA_ERR_DECODE", "MEDIA_ERR_SRC_NOT_SUPPORTED",
})


def _allowed_log_label(value: Any, allowed: frozenset[str]) -> str:
    """Return a fixed diagnostic label without coercing client-provided values."""
    if type(value) is not str:
        return "unknown"
    return value if value in allowed else "other"


def _string_presence_label(value: Any) -> str:
    if type(value) is not str:
        return "unknown"
    return "provided" if value else "missing"


def _exact_bool(value: Any) -> bool:
    return value if type(value) is bool else False


def _exact_int_or_zero(value: Any) -> int:
    return value if type(value) is int else 0


def _elapsed_seconds_for_log(value: Any) -> int:
    if type(value) is int:
        return value
    if type(value) is float and math.isfinite(value):
        return int(value)
    return 0


def _sanitize_diagnostic_state_field(key: str, value: Any) -> Any:
    if key == "state":
        return _allowed_log_label(value, _DIAGNOSTIC_AUDIO_STATE_LABELS)
    if key == "errorCode":
        return _allowed_log_label(value, _DIAGNOSTIC_AUDIO_ERROR_LABELS)
    if key in {"paused", "ended", "muted", "seeking"}:
        return _exact_bool(value)
    if key in {"currentTime", "duration"}:
        return _elapsed_seconds_for_log(value)
    if key in {"readyState", "networkState"}:
        return _exact_int_or_zero(value)
    return "[unsupported]"


class ClientDiagnosticRequest(BaseModel):
    event: Optional[str] = None
    phase: Optional[str] = None
    mode: Optional[str] = None
    programType: Optional[str] = None
    hasCurrentTrack: Optional[bool] = None
    trackRank: Optional[int] = None
    decade: Optional[str] = None
    genre: Optional[str] = None
    bedAudioState: Optional[dict[str, Any]] = None
    narrationAudioState: Optional[dict[str, Any]] = None


class NarrationFinishedRequest(BaseModel):
    playbackSessionId: Optional[str] = None
    phase: Optional[str] = None


def _sanitize_diagnostic_state(value: Any) -> Any:
    if type(value) is dict:
        sanitized = {}
        other_field_count = 0
        for key, item in value.items():
            if type(key) is not str or key not in _DIAGNOSTIC_AUDIO_STATE_KEYS:
                other_field_count += 1
                continue
            sanitized[key] = _sanitize_diagnostic_state_field(key, item)
        if other_field_count:
            sanitized["other_field_count"] = other_field_count
        return sanitized

    if type(value) is list:
        return [_sanitize_diagnostic_state(item) for item in value[:10]]

    if type(value) is str:
        return "[string]"

    if type(value) in (bool, int, float) or value is None:
        return value

    return "[unsupported]"


def update_track_clock(user_id: str):
    s = get_playback_status(user_id)
    if s.is_playing and s.phase == "track":
        if s.track_start_ts is None:
            s.track_elapsed_seconds = 0
        else:
            s.track_elapsed_seconds = time.time() - s.track_start_ts


@router.get("/status")
async def get_status():
    user_id = current_user_id()
    update_track_clock(user_id)

    s = get_playback_status(user_id)

    snap = asdict(s)

    ctx = snap.get("context") or s.context or {}
    ctx["ranking_id"] = snap.get("current_ranking_id")

    # logger.info(f"📡 STATUS CONTEXT OUT: {ctx}")

    phase = snap.get("phase")
    voice_style = ctx.get("voice_style")

    # 🔥 Bed track control:
    # Backend only marks bed active.
    # Frontend actually plays bed_audio_url.
    if phase in ("set_intro", "liner", "intro", "detail", "artist") and voice_style == "before":
        if not getattr(s, "bed_playing", False):
            s.bed_playing = True
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
        "playbackSessionId": snap.get("playback_session_id") or ctx.get("playback_session_id"),

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


@router.post("/client-diagnostic")
async def client_diagnostic(diagnostic: ClientDiagnosticRequest):
    logger.info(
        "Client diagnostic event=%s phase=%s mode=%s programType=%s "
        "hasCurrentTrack=%s trackRank=%s decade=%s genre=%s "
        "bedAudioState=%s narrationAudioState=%s",
        _allowed_log_label(diagnostic.event, _CLIENT_DIAGNOSTIC_EVENT_LABELS),
        _allowed_log_label(diagnostic.phase, _PLAYBACK_PHASE_LABELS),
        _allowed_log_label(diagnostic.mode, _PLAYBACK_MODE_LABELS),
        _allowed_log_label(diagnostic.programType, _PROGRAM_TYPE_LABELS),
        _exact_bool(diagnostic.hasCurrentTrack),
        _exact_int_or_zero(diagnostic.trackRank),
        _string_presence_label(diagnostic.decade),
        _string_presence_label(diagnostic.genre),
        _sanitize_diagnostic_state(diagnostic.bedAudioState),
        _sanitize_diagnostic_state(diagnostic.narrationAudioState),
    )
    return {"ok": True}


@router.post("/narration-finished")
async def narration_finished(payload: Optional[NarrationFinishedRequest] = None):
    user_id = current_user_id()
    s = get_playback_status(user_id)
    ctx = s.context or {}
    voice_style = ctx.get("voice_style")
    current_session_id = getattr(s, "playback_session_id", None) or ctx.get("playback_session_id")
    received_session_id = payload.playbackSessionId if payload else None
    received_phase = payload.phase if payload else None

    logger.info(
        "🔔 Narration finished signal received (phase=%s, voice_style=%s)",
        _allowed_log_label(s.phase, _PLAYBACK_PHASE_LABELS),
        _allowed_log_label(voice_style, _VOICE_STYLE_LABELS),
    )

    # 🛑 NEW: ignore if paused
    if s.is_paused:
        logger.info("⏸️ Ignoring narration-finished because system is paused")
        return {"ok": True, "ignored": True, "reason": "paused"}

    if not received_session_id:
        logger.info("Ignoring narration-finished because playbackSessionId is missing")
        return {"ok": True, "ignored": True, "reason": "missing_session"}

    if received_session_id != current_session_id:
        logger.info("Ignoring narration-finished because playbackSessionId is stale")
        return {"ok": True, "ignored": True, "reason": "stale_session"}

    narration_phases = {"set_intro", "liner", "intro", "detail", "artist"}
    if s.phase not in narration_phases:
        logger.info(
            "Ignoring narration-finished because phase=%s is not narration",
            _allowed_log_label(s.phase, _PLAYBACK_PHASE_LABELS),
        )
        return {"ok": True, "ignored": True, "reason": "not_narration_phase"}

    if received_phase != s.phase:
        logger.info(
            "Ignoring narration-finished because received phase=%s current phase=%s",
            _allowed_log_label(received_phase, _PLAYBACK_PHASE_LABELS),
            _allowed_log_label(s.phase, _PLAYBACK_PHASE_LABELS),
        )
        return {"ok": True, "ignored": True, "reason": "phase_mismatch"}

    last_narration_phase = getattr(s, "last_narration_phase", None)

    should_stop_bed = (
        voice_style == "before"
        and getattr(s, "bed_playing", False)
        and (
            not last_narration_phase
            or s.phase == last_narration_phase
        )
    )

    if should_stop_bed:
        logger.debug("🔉 Marking bed as stopped (frontend will fade out)")
        s.bed_playing = False
    else:
        logger.debug(
            "🔁 Keeping narration bed running | phase=%s last=%s bed_playing=%s",
            _allowed_log_label(s.phase, _PLAYBACK_PHASE_LABELS),
            _allowed_log_label(last_narration_phase, _PLAYBACK_PHASE_LABELS),
            _exact_bool(getattr(s, "bed_playing", False)),
        )

    # ✅ ONLY fire event if NOT paused
    narration_done_event(user_id).set()

    return {"ok": True}


#from backend.state.narration import track_done_event


@router.post("/track-finished")
async def track_finished():
    user_id = current_user_id()
    logger.info("🎵 Track finished signal received")
    event = track_done_event(user_id)

    s = get_playback_status(user_id)


    current_phase = getattr(s, "phase", None)
    current_ranking_id = getattr(s, "current_ranking_id", None)
    current_spotify_id = getattr(s, "spotify_track_id", None)
    track_start_ts = getattr(s, "track_start_ts", None)

    track_age = None
    if track_start_ts is not None:
        track_age = time.time() - track_start_ts

    logger.info(
        "🎵 track-finished check: phase=%s has_ranking_id=%s has_spotify_track=%s "
        "track_age_seconds=%s",
        _allowed_log_label(current_phase, _PLAYBACK_PHASE_LABELS),
        current_ranking_id is not None,
        current_spotify_id is not None,
        _elapsed_seconds_for_log(track_age),
    )

    if current_phase != "track":
        logger.info(
            "🚫 Ignoring track-finished because phase=%s",
            _allowed_log_label(current_phase, _PLAYBACK_PHASE_LABELS),
        )
        return {"ok": True, "ignored": True, "reason": "not_in_track_phase"}

    if track_start_ts is None:
        logger.info("🚫 Ignoring track-finished because track clock has not started")
        return {"ok": True, "ignored": True, "reason": "track_clock_not_started"}

    if track_age < 10:
        logger.info(
            "🚫 Ignoring track-finished because track_age_seconds=%s is too young",
            _elapsed_seconds_for_log(track_age),
        )
        return {"ok": True, "ignored": True, "reason": "track_too_young"}

    # Signal backend sequence loop that Spotify track is done
    event.set()

    return {"ok": True}
