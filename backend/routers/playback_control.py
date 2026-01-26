# backend/routers/playback_control.py
from __future__ import annotations

from pydantic import BaseModel
from backend.services.spotify.playback import play_spotify_track
from backend.state.playback_state import update_phase


import asyncio
import logging
from dataclasses import asdict
from typing import Literal, Optional
import contextlib

from fastapi import APIRouter
from fastapi import HTTPException

from backend.services.spotify.spotify_auth_user import get_spotify_user_client
from backend.services.spotify.playback import set_device_volume

# ✅ KEEP data models, but not the pipeline
from backend.services.playback_engine import (
    TrackRef,
    PlaybackSelection,
)

# ✅ shared playback state (NO circular import)
from backend.state.playback_flags import (
    flags,
    touch,
    reset_for_single_track,
)

logger = logging.getLogger(__name__)

# 🔒 Global playback sequence lock — prevents overlapping launches
sequence_lock = asyncio.Lock()

# Try loading skip_event if available
try:
    from backend.state.skip import skip_event

except Exception:
    skip_event = None

router = APIRouter(
    prefix="/playback",
    tags=["Playback"],
)

class PlaySpotifyRequest(BaseModel):
    spotify_track_id: str


@router.post("/play-spotify", summary="Start Spotify playback for a spotify_track_id")
async def play_spotify(req: PlaySpotifyRequest):
    logger.info("🎵 /playback/play-spotify HIT: %s", req.spotify_track_id)

    # Start Spotify playback
    await play_spotify_track(req.spotify_track_id)

    # Optional: reinforce phase for UI sync
    update_phase(
        "track",
        context={
            "spotify_track_id": req.spotify_track_id,
            "started_by": "frontend",
        }
    )

    return {
        "ok": True,
        "spotify_track_id": req.spotify_track_id,
    }


# ─────────────────────────────────────────────
# GLOBAL ASYNC TASK REFERENCE
# ─────────────────────────────────────────────
current_task: asyncio.Task | None = None


async def _run_sequence_guarded(coro):
    logger.warning("🔥 Sequence START")
    try:
        await coro
        logger.warning("✅ Sequence END")
    except asyncio.CancelledError:
        logger.warning("🛑 Sequence CANCELLED")
        raise
    except Exception:
        logger.exception("🔥 Playback sequence crashed")


def cancel_for_skip() -> None:
    """Cancel current playback immediately for Next/Prev without poisoning global flags."""
    global current_task
    logger.warning("🛑 cancel_for_skip CALLED by Next/Prev")

    if current_task:
        logger.warning("⏭ Cancelling current playback for skip/next/prev")
        with contextlib.suppress(Exception):
            current_task.cancel()
        current_task = None

    if skip_event is not None:
        with contextlib.suppress(Exception):
            skip_event.set()


# ─────────────────────────────────────────────
# CANCEL ANY EXISTING TASK
# ─────────────────────────────────────────────
async def cancel_current_sequence():
    """
    Cancels an in-flight playback coroutine (intros, details, track, bed, etc.).
    Ensures proper async cleanup before a new sequence can begin.
    """
    global current_task

    if current_task:
        logger.warning("🛑 Cancelling existing playback sequence…")
        flags.cancel_requested = True
        try:
            current_task.cancel()
        except Exception:
            pass
        current_task = None

    flags.is_playing = False
    flags.stopped = True
    flags.is_paused = False

    # 🔥 brief delay gives radio_runtime time to unwind Spotify + narration
    await asyncio.sleep(0.15)

    # ─────────────────────────────────────────────
    # Restore Spotify volume after cancellation
    # ─────────────────────────────────────────────
    try:
        from backend.services.spotify.playback import set_device_volume
        await set_device_volume(100)
        logger.info("🔊 Restored Spotify volume to 100% after cancel")
    except Exception as exc:
        logger.warning(f"⚠️ Failed to restore volume after cancel: {exc}")

    flags.cancel_requested = False


# ─────────────────────────────────────────────
# START NEW BACKGROUND TASK SAFELY
# ─────────────────────────────────────────────
async def start_new_sequence(coro):
    """
    Ensures exclusive playback launch by protecting the entire
    cancel → start sequence with a global asyncio.Lock.
    """
    async with sequence_lock:
        await cancel_current_sequence()

        global current_task
        flags.stopped = False
        flags.is_playing = True
        flags.cancel_requested = False

        logger.info("🎬 Launching new playback background task…")
        current_task = asyncio.create_task(
            _run_sequence_guarded(coro)
        )

        return current_task


# ─────────────────────────────────────────────
# PUBLIC API ROUTES
# ─────────────────────────────────────────────
@router.post("/play-track", summary="Play exactly one track via sequence engine")
async def play_track(payload: dict):
    logger.info("🎯 /playback/play-track HIT")
    print("🔥🔥🔥 PLAY_TRACK ENDPOINT ENTERED 🔥🔥🔥")

    track = TrackRef(
        track_id=payload["track"]["track_id"],
        spotify_track_id=payload["track"]["spotify_track_id"],
        rank=payload["track"]["rank"],
        track_name=payload["track"]["track_name"],
        artist_name=payload["track"]["artist_name"],
    )

    selection = PlaybackSelection(
        language=payload["selection"]["language"],
        voices=payload["selection"]["voices"],
        voicePlayMode=payload["selection"]["voicePlayMode"],
        pauseMode=payload["selection"]["pauseMode"],
    )

    context = payload.get("context")
    if not context:
        return {"ok": False, "error": "Missing playback context"}

    logger.info(
        "▶️ /playback/play-track (single-step via sequence): rank=%s mode=%s context=%s",
        track.rank,
        selection.voicePlayMode,
        context.get("type"),
    )

    # await cancel_current_sequence()
    reset_for_single_track()

    # ─────────────────────────────────────────────
    # SINGLE STEP = SEQUENCE OF LENGTH 1
    # ─────────────────────────────────────────────

    if context["type"] == "decade_genre":
        from backend.services.decade_genre_sequence import run_decade_genre_sequence

        print("🔥 About to build decade_genre sequence")
        print("FUNC:", run_decade_genre_sequence)
        print("FILE:", run_decade_genre_sequence.__code__.co_filename)

        coro = run_decade_genre_sequence(
            decade=context["decade"],
            genre=context["genre"],
            start_rank=track.rank,
            end_rank=track.rank,
            mode="count_up",
            tts_language=selection.language,
            play_intro=True,
            play_detail="detail" in selection.voices,
            play_artist_description="artist" in selection.voices,
            play_track=True,
            voice_style=selection.voicePlayMode,
        )


    elif context["type"] == "collection":
        from backend.routers.collections_player import _run_play_sequence_collection

        coro = _run_play_sequence_collection(
            collection_slug=context["collection_slug"],
            start_rank=track.rank,
            end_rank=track.rank,
            mode="count_up",
            tts_language=selection.language,
            play_intro=True,
            play_detail="detail" in selection.voices,
            play_artist_description="artist" in selection.voices,
            play_track=True,
            text_intro=True,
            text_detail=False,
            text_artist_description=False,
            voice_style=selection.voicePlayMode,
        )

    else:
        return {"ok": False, "error": "Unknown playback context type"}
    # Cancel anything already running (keeps behavior sane)

    # ✅ Run single-step inline so Spotify actually starts
    await start_new_sequence(coro)

    return {
        "ok": True,
        "rank": track.rank,
        "message": "Single-step playback ran inline (sync) via sequence engine",
    }


@router.get("/flags-status", summary="Legacy flags snapshot (debug)")
def flags_status():
    return asdict(flags)


@router.post("/start", summary="Mark playback as started")
def start(
        language: Literal["en", "es", "ptbr", "pt-BR"] = "en",
        mode: Optional[str] = None,
        current_rank: Optional[int] = None,
):
    flags.is_playing = True
    flags.is_paused = False
    flags.stopped = False
    flags.language = language
    flags.mode = mode
    flags.current_rank = current_rank
    touch()
    return {"ok": True, "status": asdict(flags)}


@router.post("/pause", summary="Pause playback")
async def pause():
    logger.info("⏸️ Pause requested")

    # Mark paused state
    flags.is_paused = True
    flags.is_playing = False
    flags.cancel_requested = True

    # 1️⃣ Stop narration immediately
    if skip_event is not None:
        try:
            skip_event.set()
        except Exception:
            pass

    # 2️⃣ Stop Spotify immediately
    try:
        await set_device_volume(100)
        from backend.services.spotify.playback import stop_spotify_playback
        await stop_spotify_playback(fade_out_seconds=0.3)
    except Exception as exc:
        logger.warning("⚠️ Pause Spotify stop failed: %s", exc)

    touch()
    return {"ok": True, "status": asdict(flags)}


@router.post("/resume", summary="Resume playback")
def resume():
    flags.is_paused = False
    flags.is_playing = True
    touch()
    return {"ok": True, "status": asdict(flags)}


@router.post("/stop", summary="Stop playback")
async def stop():
    await cancel_current_sequence()
    touch()
    return {"ok": True, "status": asdict(flags)}


@router.post("/skip", summary="Skip to next track")
def skip():
    if skip_event is not None:
        try:
            skip_event.set()
        except Exception:
            pass

    touch()
    return {
        "ok": True,
        "message": "Skip signaled",
        "status": asdict(flags),
    }


@router.post("/warmup", summary="Prepare Spotify playback environment")
async def warmup_playback():
    """
    Prepare Spotify for playback:
    - Ensure OAuth is valid
    - Ensure at least one active device exists
    - Set baseline volume

    This endpoint NEVER starts playback.
    It is safe and idempotent.
    """

    logger.info("🎛️ /playback/warmup requested")

    try:
        # 1️⃣ Ensure Spotify client (OAuth)
        sp = get_spotify_user_client()
        logger.info("🎧 Spotify client ready")

        # 2️⃣ Discover devices
        devices = sp.devices().get("devices", [])
        logger.info("📱 Spotify devices found: %d", len(devices))

        if not devices:
            logger.warning("❌ No Spotify devices found")
            return {
                "ready": False,
                "reason": "no_devices",
                "message": "No Spotify devices found. Open Spotify on a device."
            }

        # 3️⃣ Require an active device
        active_device = next((d for d in devices if d.get("is_active")), None)

        if not active_device:
            logger.warning("⚠️ No active Spotify device")
            return {
                "ready": False,
                "reason": "no_active_device",
                "message": "Open Spotify on a device to continue."
            }

        device_id = active_device["id"]
        device_name = active_device.get("name", "Unknown device")

        logger.info("▶️ Active device: %s (%s)", device_name, device_id)

        # 4️⃣ Set baseline volume
        # NOTE: set_device_volume may be async in some versions; yours supports await
        try:
            await set_device_volume(100, device_id=device_id)
            logger.info("🔊 Spotify volume set to 100%%")
        except Exception as exc:
            logger.warning("⚠️ Failed to set volume during warmup: %s", exc)

        return {
            "ready": True,
            "device_id": device_id,
            "device_name": device_name,
            "volume": 100
        }

    except Exception as exc:
        logger.exception("🔥 Playback warmup failed")
        raise HTTPException(status_code=500, detail=str(exc))

# backend/routers/playback_control.py (or playback_status.py)

@router.post("/reset")
async def reset_playback_state():
    from backend.state.playback_state import status
    from backend.state.playback_flags import flags

    status.is_playing = False
    status.is_paused = False
    status.stopped = True
    status.phase = None
    status.track_name = None
    status.artist_name = None
    status.current_rank = None
    status.context = {}
    status.bed_playing = False
    status.started_by = None
    status.track_start_ts = None
    status.track_elapsed_seconds = 0
    status.track_duration_seconds = 0

    flags.is_playing = False
    flags.stopped = True
    flags.cancel_requested = False

    return {"ok": True}
