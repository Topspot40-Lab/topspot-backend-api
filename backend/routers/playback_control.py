# backend/routers/playback_control.py
from __future__ import annotations

from backend.state.playback_state import (
    clear_public_playback_status,
    mark_paused,
    mark_playing,
    start_playback_session,
    update_phase,
)
from pydantic import BaseModel
from backend.services.spotify.playback import play_spotify_track
from backend.services.spotify.playback import stop_spotify_playback
from backend.state.narration import track_done_event, narration_done_event
from sqlmodel import Session, select
from backend.database import engine
from backend.models.dbmodels import Artist
from backend.database import get_db
from backend.models.dbmodels import TrackRanking, DecadeGenre, Decade, Genre
from backend.services.bed_tracks import BED_BUCKET, get_genre_bed_key

import asyncio
import logging
from typing import Literal, Optional
import contextlib

from fastapi import APIRouter, Depends
from fastapi import HTTPException

from backend.services.spotify.playback import set_device_volume
from backend.services.spotify.spotify_auth_user import get_spotify_user_client

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
from backend.state.playback_runtime import (
    bind_request_user,
    bind_task,
    current_runtime,
    current_user_id,
    snapshot_dataclass,
)

logger = logging.getLogger(__name__)


def _normalize_tts_locale(language: str | None) -> str:
    value = (language or "").strip()
    if not value:
        return "en"

    normalized = value.lower().replace("_", "-")
    if normalized.startswith("en"):
        return "en"
    if normalized.startswith("es"):
        return "es"
    if normalized in ("pt", "ptbr", "pt-br"):
        return "pt-BR"
    return "en"

# 🔒 Global playback sequence lock — prevents overlapping launches
# Try loading skip_event if available
try:
    from backend.state.skip import skip_event

except Exception:
    skip_event = None

router = APIRouter(
    prefix="/playback",
    tags=["Playback"],
    dependencies=[Depends(bind_request_user)],
)


class PlaySpotifyRequest(BaseModel):
    spotify_track_id: str
    device_id: Optional[str] = None


@router.post("/play-spotify", summary="Start Spotify playback for a spotify_track_id")
async def play_spotify(req: PlaySpotifyRequest):
    user_id = current_user_id()
    status = current_runtime().status
    logger.debug("🎵 /playback/play-spotify HIT: %s", req.spotify_track_id)

    # Start Spotify playback
    ok = await play_spotify_track(req.spotify_track_id, user_id, req.device_id)

    if not ok:
        logger.error("❌ Spotify playback failed for %s", req.spotify_track_id)
        return {
            "ok": False,
            "error": "Spotify playback failed",
            "spotify_track_id": req.spotify_track_id,
        }

    # Optional: reinforce phase for UI sync
    existing_context = getattr(status, "context", {}) or {}

    merged_context = {
        **existing_context,
        "spotify_track_id": req.spotify_track_id,
        "started_by": "frontend",
    }

    update_phase(
        user_id,
        "track",
        track_name=getattr(status, "track_name", None),
        artist_name=getattr(status, "artist_name", None),
        current_rank=getattr(status, "current_rank", None),
        context=merged_context,
    )

    return {
        "ok": True,
        "spotify_track_id": req.spotify_track_id,
    }


# ─────────────────────────────────────────────
# GLOBAL ASYNC TASK REFERENCE
# ─────────────────────────────────────────────
async def _run_sequence_guarded(coro):
    logger.info("🔥 Sequence START")
    try:
        await coro
        logger.info("✅ Sequence END")
    except asyncio.CancelledError:
        logger.info("🛑 Sequence CANCELLED")
        raise
    except Exception:
        logger.exception("🔥 Playback sequence crashed")


def cancel_for_skip() -> None:
    """Cancel current playback immediately for Next/Prev without poisoning global flags."""
    runtime = current_runtime()
    logger.warning("🛑 cancel_for_skip CALLED by Next/Prev")

    if runtime.current_task:
        logger.warning("⏭ Cancelling current playback for skip/next/prev")
        with contextlib.suppress(Exception):
            runtime.current_task.cancel()
        runtime.current_task = None

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
    runtime = current_runtime()
    user_id = current_user_id()

    if runtime.current_task:
        logger.info("🔄 Replacing existing playback sequence")
        flags.cancel_requested = True
        try:
            runtime.current_task.cancel()
        except Exception:
            pass
        runtime.current_task = None

    flags.is_playing = False
    flags.stopped = True
    flags.is_paused = False

    # 🔥 STOP SPOTIFY IMMEDIATELY WHEN CANCELING
    try:
        await stop_spotify_playback(user_id, fade_out_seconds=0.2)
        logger.debug("🛑 Spotify stopped during sequence cancel")
    except Exception as exc:
        logger.warning("⚠️ Failed to stop Spotify during cancel: %s", exc)

    await asyncio.sleep(0.15)

    # ─────────────────────────────────────────────
    # Restore Spotify volume after cancellation
    # ─────────────────────────────────────────────
    try:
        from backend.services.spotify.playback import set_device_volume
        await set_device_volume(100, user_id)
        logger.debug("🔊 Restored Spotify volume to 100% after cancel")
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
    runtime = current_runtime()
    user_id = current_user_id()
    async with runtime.sequence_lock:
        await cancel_current_sequence()
        session_id = start_playback_session(user_id)
        if callable(coro):
            coro = coro(session_id)

        flags.stopped = False
        flags.is_playing = True
        flags.cancel_requested = False

        logger.debug("🎬 Launching new playback background task…")
        runtime.current_task = asyncio.create_task(
            _run_sequence_guarded(coro)
        )
        bind_task(runtime.current_task, user_id)

        return runtime.current_task


# ─────────────────────────────────────────────
# PUBLIC API ROUTES
# ─────────────────────────────────────────────
@router.post("/play-track", summary="Play exactly one track via sequence engine")
async def play_track(payload: dict):
    user_id = current_user_id()
    status = current_runtime().status

    track = TrackRef(
        track_id=payload["track"]["track_id"],
        spotify_track_id=payload["track"]["spotify_track_id"],
        rank=payload["track"].get("rank", 1),
        track_name=payload["track"]["track_name"],
        artist_name=payload["track"]["artist_name"],
    )

    tts_languages = (
            payload["selection"].get("languages")
            or [payload["selection"]["language"]]
    )

    selection = PlaybackSelection(
        language=payload["selection"]["language"],
        voices=payload["selection"]["voices"],
        voicePlayMode=payload["selection"]["voicePlayMode"],
        pauseMode=payload["selection"]["pauseMode"],
        languages=tts_languages,
    )

    logger.info("🌎 Playback languages requested: %s", tts_languages)

    context = payload.get("context")
    if not context:
        return {"ok": False, "error": "Missing playback context"}

    logger.info(
        "▶️ /playback/play-track (single-step via sequence): program=DG|%s|%s rank=%s mode=%s context=%s",
        context.get("decade"),
        context.get("genre"),
        track.rank,
        selection.voicePlayMode,
        context.get("type"),
    )

    # await cancel_current_sequence()
    reset_for_single_track()

    if context and context.get("type") == "favorites":

        ranking_id = payload.get("track", {}).get("ranking_id")
        if not ranking_id:
            return {"ok": False, "error": "Missing track.ranking_id for favorites playback"}

        db = next(get_db())

        q = (
            select(TrackRanking, Decade, Genre)
            .join(DecadeGenre, DecadeGenre.id == TrackRanking.decade_genre_id)
            .join(Decade, Decade.id == DecadeGenre.decade_id)
            .join(Genre, Genre.id == DecadeGenre.genre_id)
            .where(TrackRanking.id == ranking_id)
        )

        row = db.exec(q).first()
        if not row:
            return {"ok": False, "error": f"TrackRanking not found for ranking_id={ranking_id}"}

        tr_rank, decade_row, genre_row = row

        # ✅ Reuse DG sequence engine with REAL decade/genre
        from backend.services.decade_genre_sequence import run_decade_genre_sequence

        coro = run_decade_genre_sequence(
            decade=decade_row.slug,
            genre=genre_row.slug,
            start_rank=tr_rank.ranking,
            end_rank=tr_rank.ranking,
            mode="count_up",
            tts_language=selection.language,
            play_intro=True,
            play_detail="detail" in selection.voices,
            play_artist_description="artist" in selection.voices,
            play_track=True,
            voice_style=selection.voicePlayMode,
        )

        await start_new_sequence(coro)

        return {
            "ok": True,
            "message": "Favorites single-track played via DG engine (resolved by ranking_id)",
            "resolved": {
                "decade": decade_row.slug,
                "genre": genre_row.slug,
                "rank": tr_rank.ranking,
                "ranking_id": ranking_id,
            },
        }

    if context.get("type") == "favorites":
        # Option 1: separate pipeline for favorites (no genre required)
        spotify_id = track.spotify_track_id
        if not spotify_id:
            raise HTTPException(status_code=400, detail="Missing spotify_track_id for favorites playback")

        async def _play_favorites_one():
            # Minimal v1: just start the Spotify track (keeps pipeline separate)
            await play_spotify_track(spotify_id, user_id)

            existing_context = getattr(status, "context", {}) or {}
            merged_context = {
                **existing_context,
                "type": "favorites",
                "program": context.get("program"),
                "decade": context.get("decade"),
                "collection_slug": context.get("collection_slug"),
                "ranking_id": payload["track"].get("ranking_id"),
                "spotify_track_id": spotify_id,
                "started_by": "frontend",
            }

            update_phase(
                user_id,
                "track",
                track_name=track.track_name,
                artist_name=track.artist_name,
                current_rank=track.rank,
                context=merged_context,
            )

        reset_for_single_track()
        await start_new_sequence(_play_favorites_one())
        return {"ok": True, "message": "Favorites single-track playback started"}

    elif context.get("type") == "artist_spotlight":
        if not track.spotify_track_id:
            return {"ok": False, "error": "Missing spotify_track_id for Artist Spotlight playback"}

        spotify_artist_id = context.get("spotify_artist_id")

        genre_slug = context.get("genre")

        bed_key = get_genre_bed_key(genre_slug)

        bed_audio_url = (
            f"https://iizlnzmmhkzedqkolgir.supabase.co/storage/v1/object/public/"
            f"{BED_BUCKET}/{bed_key}"
        )

        if not spotify_artist_id and context.get("artist_id"):
            with Session(engine) as session:
                artist = session.exec(
                    select(Artist).where(Artist.id == int(context["artist_id"]))
                ).first()

                if artist:
                    spotify_artist_id = artist.spotify_artist_id
                    context["spotify_artist_id"] = spotify_artist_id

        logger.info(
            "🎙️ Artist Spotlight library branch | artist_id=%s artist_name=%s spotify_artist_id=%s",
            context.get("artist_id"),
            context.get("artist_name"),
            spotify_artist_id,
        )

        async def _play_narration_phase(phase: str, audio_url: str | None):
            if not audio_url:
                return

            narration_done_event(user_id).clear()

            logger.info(
                "🎙️ Artist Spotlight phase publish | phase=%s url=%s",
                phase,
                audio_url,
            )

            update_phase(
                user_id,
                phase,
                is_playing=True,
                voice_style=selection.voicePlayMode,
                track_name=track.track_name,
                artist_name=track.artist_name,
                current_rank=track.rank,
                context={
                    **context,
                    "spotify_track_id": track.spotify_track_id,
                    "audio_url": audio_url,
                    "bed_audio_url": bed_audio_url,
                    "started_by": "frontend",
                },
            )

            await narration_done_event(user_id).wait()
            logger.info("✅ Artist Spotlight phase finished | phase=%s", phase)

        tts_language = _normalize_tts_locale(context.get("language") or selection.language or "en")
        audio_bucket = "audio-ptbr" if tts_language == "pt-BR" else f"audio-{tts_language}"
        base_url = f"https://iizlnzmmhkzedqkolgir.supabase.co/storage/v1/object/public/{audio_bucket}"

        artist_audio_url = (
            f"{base_url}/artist/{spotify_artist_id}.mp3"
            if spotify_artist_id
            else None
        )

        track_detail = payload["track"].get("detail")

        if context.get("play_artist_bio", True):
            await _play_narration_phase("artist", artist_audio_url)

        # Artist Spotlight skips intro MP3s because they are ranking-list specific.
        # The artist bio plays once, then each track gets its detail narration.
        await _play_narration_phase(
            "detail",
            f"{base_url}/detail/{track.spotify_track_id}.mp3",
        )

        logger.info("🎵 Artist Spotlight about to start Spotify | track=%s", track.spotify_track_id)

        await play_spotify_track(track.spotify_track_id, user_id)
        update_phase(
            user_id,
            "track",
            track_name=track.track_name,
            artist_name=track.artist_name,
            current_rank=track.rank,
            context={
                **context,
                "spotify_track_id": track.spotify_track_id,
                "started_by": "frontend",
            },
        )

        return {"ok": True, "message": "Artist Spotlight playback started"}

    elif context.get("type") == "decade_genre":

        if context.get("decade", "").lower() == "all":
            if not track.spotify_track_id:
                return {"ok": False, "error": "Missing spotify_track_id for ALL decade playback"}

            await play_spotify_track(track.spotify_track_id, user_id)

            update_phase(
                user_id,
                "track",
                track_name=track.track_name,
                artist_name=track.artist_name,
                current_rank=track.rank,
                context={
                    **context,
                    "spotify_track_id": track.spotify_track_id,
                    "started_by": "frontend",
                },
            )

            return {"ok": True, "message": "ALL decade direct playback"}

        from backend.services.decade_genre_sequence import (
            run_decade_genre_sequence,
            run_decade_genre_continuous_sequence
        )
        is_continuous = payload["selection"].get("continuous", False)

        if is_continuous:
            logger.debug("📻 RADIO MODE ENABLED (continuous)")

            coro = lambda session_id: run_decade_genre_continuous_sequence(
                decade=context["decade"],
                genre=context["genre"],
                start_rank=track.rank,
                end_rank=track.rank,
                mode=payload["selection"].get("playbackOrder", "count_up"),
                tts_language=selection.language,
                tts_languages=tts_languages,
                play_intro=True,
                play_detail="detail" in selection.voices,
                play_artist_description="artist" in selection.voices,
                play_track=True,
                voice_style=selection.voicePlayMode,
                playback_session_id=session_id,
            )
        else:
            logger.info("🎯 SINGLE MODE ENABLED")

            coro = lambda session_id: run_decade_genre_sequence(
                decade=context["decade"],
                genre=context["genre"],
                start_rank=track.rank,
                end_rank=track.rank,
                mode="count_up",
                tts_language=selection.language,
                tts_languages=tts_languages,
                play_intro=True,
                play_detail="detail" in selection.voices,
                play_artist_description="artist" in selection.voices,
                play_track=True,
                voice_style=selection.voicePlayMode,
                playback_session_id=session_id,
            )

    elif context.get("type") == "collection_radio":
        from backend.services.collections_radio_sequence import run_collections_radio_sequence

        collection_group_slug = (
                context.get("collection_group_slug")
                or context.get("collectionGroupSlug")
                or context.get("collection_group")
                or "ALL"
        )

        logger.info(
            "📻 COLLECTIONS RADIO START REQUEST | group=%s",
            collection_group_slug,
        )

        coro = run_collections_radio_sequence(
            tts_language=selection.language,
            tts_languages=tts_languages,
            collection_group_slug=collection_group_slug,
            voices=selection.voices,
            voice_style=selection.voicePlayMode,
        )


    elif context.get("type") == "collection":
        from backend.services.collection_sequence import run_collection_sequence

        coro = run_collection_sequence(
            collection_slug=context["collection_slug"],
            start_rank=track.rank,
            end_rank=track.rank,
            mode="count_up",
            tts_language=selection.language,
            tts_languages=selection.languages,
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


# LEGACY/DEBUG ROUTE
# Not used by the current frontend flow.
# Candidate for removal after smoke testing and API cleanup.
@router.get("/flags-status", summary="Legacy flags snapshot (debug)")
async def flags_status():
    return snapshot_dataclass(flags)


@router.post("/start", summary="Mark playback as started")
async def start(
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
    return {"ok": True, "status": snapshot_dataclass(flags)}


@router.post("/pause", summary="Pause playback")
async def pause():
    user_id = current_user_id()
    status = current_runtime().status
    logger.info("⏸️ Pause requested")

    mark_paused(user_id)

    # 🔊 Capture current volume BEFORE fade
    try:
        sp = await get_spotify_user_client(user_id)
        pb = sp.current_playback()
        if pb and pb.get("device"):
            status.volume = pb["device"]["volume_percent"]
            status.context["device_id"] = pb["device"]["id"]
            logger.info(f"💾 Saved volume: {status.volume}")
    except Exception as exc:
        logger.warning("⚠️ Failed to capture volume: %s", exc)

    # 1️⃣ Stop narration
    if skip_event is not None:
        try:
            skip_event.set()
        except Exception:
            pass

    # 2️⃣ Fade out Spotify
    try:
        from backend.services.spotify.playback import stop_spotify_playback
        await stop_spotify_playback(user_id, fade_out_seconds=0.3)
    except Exception as exc:
        logger.warning("⚠️ Pause Spotify stop failed: %s", exc)

    touch()
    return {"ok": True, "status": snapshot_dataclass(flags)}


@router.post("/resume", summary="Resume playback")
async def resume():
    user_id = current_user_id()
    status = current_runtime().status
    phase = status.phase
    logger.info(f"▶️ Resume requested from phase: {phase}")

    mark_playing(
        user_id=user_id,
        mode=status.mode,
        language=status.language,
        context=status.context
    )

    try:
        # 🎯 CASE 1 — TRACK (existing logic)
        if phase == "track":
            sp = await get_spotify_user_client(user_id)

            sp.start_playback()

            import time

            for _ in range(10):
                time.sleep(0.1)
                try:
                    pb = sp.current_playback()
                    if pb and pb.get("is_playing"):
                        break
                except Exception:
                    pass

            time.sleep(0.2)

            device_id = status.context.get("device_id") if status.context else None

            if device_id and hasattr(status, "volume") and status.volume is not None:
                logger.info(f"🔊 Restoring volume to {status.volume}")
                sp.volume(status.volume, device_id=device_id)

            return {"ok": True, "status": snapshot_dataclass(flags)}

        # 🎯 CASE 2 — NARRATION PHASES
        elif phase in ["set_intro", "liner", "intro", "detail", "artist"]:
            logger.info(f"🔁 Restarting narration phase: {phase}")

            return {
                "ok": True,
                "restart_track": True,
                "status": snapshot_dataclass(flags)
            }

    except Exception as exc:
        logger.warning("⚠️ Resume failed: %s", exc)

    touch()
    return {"ok": True, "status": snapshot_dataclass(flags)}


@router.post("/stop", summary="Stop playback")
async def stop():
    user_id = current_user_id()
    await cancel_current_sequence()

    try:
        await stop_spotify_playback(user_id, fade_out_seconds=0.3)
    except Exception as exc:
        logger.warning("⚠️ Spotify stop failed: %s", exc)

    clear_public_playback_status(user_id)
    touch()
    return {"ok": True, "status": snapshot_dataclass(flags)}


@router.post("/skip", summary="Skip to next track")
async def skip():
    if skip_event is not None:
        try:
            skip_event.set()
        except Exception:
            pass

    touch()
    return {
        "ok": True,
        "message": "Skip signaled",
        "status": snapshot_dataclass(flags),
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

    user_id = current_user_id()

    try:
        # 1️⃣ Ensure Spotify client (OAuth)
        sp = await get_spotify_user_client(user_id)
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
            await set_device_volume(100, user_id, device_id=device_id)
            logger.debug("🔊 Spotify volume set to 100%%")
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
    from backend.state.playback_flags import flags
    user_id = current_user_id()
    status = current_runtime().status

    # Kill any running sequence first
    await cancel_current_sequence()

    # Reset public playback state
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

    # Reset engine flags
    flags.is_playing = False
    flags.stopped = True
    flags.cancel_requested = False

    clear_public_playback_status(user_id)

    return {"ok": True}
