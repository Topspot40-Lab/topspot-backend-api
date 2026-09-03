# backend/services/playback_helpers.py
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
from io import BytesIO
from typing import Literal, Optional

import httpx
from mutagen.mp3 import MP3

from backend.config import (
    AUDIO_PREFIXES,
    BUCKETS,
)
from backend.services.supabase_playback import play_mp3
from backend.state.playback_state import update_phase
from backend.state.playback_runtime import bind_task, current_runtime, current_user_id
from backend.state.skip import skip_event
from backend.utils.tts_diagnostics import normalize_for_filename
from backend.services.audio_urls import resolve_audio_ref

logger = logging.getLogger(__name__)

# Temporary: frontend owns narration playback
FRONTEND_OWNS_INTRO = True
FRONTEND_OWNS_DETAIL = False
FRONTEND_OWNS_ARTIST = False


# ─────────────────────────────────────────────
# Playback User-Control Helpers
# ─────────────────────────────────────────────

async def _respect_user_controls() -> None:
    """Pause / stop cooperative checkpoint."""
    status = current_runtime().status
    while status.is_paused:
        await asyncio.sleep(0.25)

    if status.stopped:
        logger.info("🛑 Playback stopped by user.")
        raise asyncio.CancelledError("Playback stopped")


def _update_state_for_play(kind: str, bucket: str, key: str) -> None:
    """Mark which audio asset is currently playing."""
    user_id = current_user_id()
    update_phase(
        user_id,
        kind.lower(),
        is_playing=True,
        is_paused=False,
        stopped=False,
        context={"bucket": bucket, "key": key},
    )


# ─────────────────────────────────────────────
# Speech + Language Helpers
# ─────────────────────────────────────────────

Lang = Literal["en", "es", "pt-BR"]
Kind = Literal[
    "set_intro",
    "liner",
    "intro",
    "detail",
    "short_detail",
    "artist",
    "collections_intro",
]

_LANG_MAP: dict[str, str] = {
    "en": "en",
    "es": "es",
    "ptbr": "pt-BR",
    "pt-br": "pt-BR",
    "pt_br": "pt-BR",
    "pt": "pt-BR",
}

def canon_lang(code: str | None) -> str:
    c = (code or "en").strip().lower()
    return _LANG_MAP.get(c, "en")


# ─────────────────────────────────────────────
# Tunables & Gain
# ─────────────────────────────────────────────

_SUPA_FETCH_TIMEOUT = float(os.getenv("SUPA_MP3_TIMEOUT", "60"))
_SUPA_FETCH_RETRIES = int(os.getenv("SUPA_MP3_RETRIES", "3"))
_SUPA_BACKOFF = float(os.getenv("SUPA_MP3_BACKOFF", "1.8"))

try:
    from backend.config import INTRO_GAIN_DB, DETAIL_GAIN_DB, ARTIST_GAIN_DB
except Exception:
    INTRO_GAIN_DB = float(os.getenv("INTRO_GAIN_DB", "-4.0"))
    DETAIL_GAIN_DB = float(os.getenv("DETAIL_GAIN_DB", "0.0"))
    ARTIST_GAIN_DB = float(os.getenv("ARTIST_GAIN_DB", "0.0"))

# ─────────────────────────────────────────────
# Bucket / Key Builders
# ─────────────────────────────────────────────

def bucket_for(language: str, kind: Kind) -> str:
    lang = canon_lang(language)
    lang_map = BUCKETS.get(lang, BUCKETS["en"])

    if kind in lang_map:
        return lang_map[kind]

    if kind == "collections_intro":
        return lang_map.get("intro")

    return lang_map.get("intro")


def key_for(kind: Kind, filename: str | None) -> Optional[str]:
    if not filename:
        return None

    prefix = AUDIO_PREFIXES.get(kind)
    if prefix is None and kind == "collections_intro":
        prefix = "collections-intros"

    if prefix is None:
        return None

    return f"{prefix}/{filename}"


def build_intro_filename(decade: str, genre: str, rank: int) -> str:
    return f"{normalize_for_filename(decade)}_{normalize_for_filename(genre)}_{rank:02d}.mp3"


def build_collection_intro_filename(slug: str, rank: int) -> str:
    return f"{normalize_for_filename(slug)}_{rank:02d}.mp3"


def build_detail_filename(spotify_track_id: str | None) -> Optional[str]:
    return f"{spotify_track_id}.mp3" if spotify_track_id else None


def build_artist_filename(spotify_artist_id: str | None) -> Optional[str]:
    return f"{spotify_artist_id}.mp3" if spotify_artist_id else None


# ─────────────────────────────────────────────
# Gain Mapping
# ─────────────────────────────────────────────

def _gain_for_kind(kind_label: str) -> float:
    k = (kind_label or "").strip().lower()
    if k in ("intro", "collections_intro"):
        return INTRO_GAIN_DB
    if k == "detail":
        return DETAIL_GAIN_DB
    if k == "artist":
        return ARTIST_GAIN_DB
    return 0.0


# ─────────────────────────────────────────────
# MP3 helpers
# ─────────────────────────────────────────────

def _looks_like_mp3(b: bytes) -> bool:
    return b.startswith(b"ID3") or (
        len(b) > 2 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0
    )


from typing import Union
import httpx
from io import BytesIO
from mutagen.mp3 import MP3
import logging

logger = logging.getLogger(__name__)

def _audio_source_label(src: object) -> str:
    if type(src) is bytes:
        return "bytes"
    if type(src) is str:
        return "remote" if src.startswith("http") else "local"
    return "unsupported"


def _audio_error_diagnostic(exc: BaseException) -> tuple[str, int]:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            status_code = exc.response.status_code
        except Exception:
            status_code = 0
        return "http_status", status_code if type(status_code) is int else 0
    if isinstance(exc, httpx.RequestError):
        return "http_request", 0
    if isinstance(exc, OSError):
        return "os_error", 0
    if isinstance(exc, RuntimeError):
        return "runtime_error", 0
    return "unexpected", 0


def _narration_phase_label(kind: object) -> str:
    if type(kind) is str and kind in {"set_intro", "liner", "intro", "detail", "artist", "collections_intro"}:
        return kind
    return "other"


def mp3_duration_seconds(src: Union[str, bytes]) -> float:
    """
    Return duration of an MP3 in seconds.
    Accepts:
      - raw bytes
      - local file path
      - remote URL (http/https)
    """
    try:
        # Case 1: Already bytes
        if isinstance(src, bytes):
            audio = MP3(BytesIO(src))
            secs = float(audio.info.length)
            logger.info("mp3_duration source=bytes")
            return secs

        # Case 2: Remote URL
        if isinstance(src, str) and src.startswith("http"):
            r = httpx.get(src, timeout=20.0)
            r.raise_for_status()
            audio = MP3(BytesIO(r.content))
            secs = float(audio.info.length)
            logger.info("mp3_duration source=remote")
            return secs

        # Case 3: Local file path
        if isinstance(src, str):
            audio = MP3(src)
            secs = float(audio.info.length)
            logger.info("mp3_duration source=local")
            return secs

        logger.error("mp3_duration_failed source=unsupported error_class=unsupported http_status=0")
        return 0.0

    except Exception as exc:
        error_class, http_status = _audio_error_diagnostic(exc)
        logger.error(
            "mp3_duration_failed source=%s error_class=%s http_status=%d",
            _audio_source_label(src),
            error_class,
            http_status,
        )
        return 0.0


def _play_bytes_with_gain_sync(b: bytes, gain_db: float) -> int:
    """BLOCKING ffplay execution (safe to run in a worker thread)."""
    import tempfile
    import subprocess
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "clip.mp3"
        src.write_bytes(b)

        cmd = [
            "ffplay",
            "-nodisp",
            "-autoexit",
            "-hide_banner",
            "-loglevel",
            "error",
            "-af",
            f"volume={gain_db}dB",
            str(src),
        ]
        try:
            return int(subprocess.call(cmd))
        except Exception as exc:
            error_class, _ = _audio_error_diagnostic(exc)
            logger.warning("ffplay_volume_filter_failed error_class=%s", error_class)
            return 1


def _play_bytes_plain_sync(b: bytes) -> int:
    """BLOCKING plain MP3 playback."""
    res = play_mp3(b, block=True, diagnostics=False)
    if inspect.iscoroutine(res):
        return int(asyncio.run(res))
    return int(res)


async def _run_progress_heartbeat(phase: str, duration: float) -> None:
    """
    Update playback_state while narration audio is playing.
    percent_complete stays normalized 0.0 -> 1.0 (same as track).
    """
    user_id = current_user_id()
    start = asyncio.get_running_loop().time()

    while True:
        await _respect_user_controls()

        now = asyncio.get_running_loop().time()
        elapsed = now - start

        if duration > 0:
            percent = min(elapsed / duration, 1.0)
        else:
            percent = 0.0

        update_phase(
            user_id,
            phase,
            elapsed_seconds=min(elapsed, duration) if duration > 0 else elapsed,
            duration_seconds=duration,
            percent_complete=percent,
        )

        if duration > 0 and elapsed >= duration:
            break

        await asyncio.sleep(0.1)


# ─────────────────────────────────────────────
# safe_play — MP3 playback + real-time progress updates
# ─────────────────────────────────────────────

async def safe_play(kind: str, bucket: str, key: str, voice_style: str | None = None) -> bool:
    user_id = current_user_id()
    log_phase = _narration_phase_label(kind)
    owns = (
            ((kind == "intro" or kind == "set_intro") and FRONTEND_OWNS_INTRO)
            or (kind == "detail" and FRONTEND_OWNS_DETAIL)
            or (kind == "artist" and FRONTEND_OWNS_ARTIST)
    )

    if owns:
        status = current_runtime().status
        ref = resolve_audio_ref(bucket, key)
        logger.info(
            "narration_frontend_owned phase=%s source=resolved has_audio_ref=%s",
            log_phase,
            bool(ref) if type(ref) is str else False,
        )

        update_phase(
            user_id,
            kind,
            is_playing=True,
            is_paused=False,
            stopped=False,
            context={
                "bucket": bucket,
                "key": key,
                "audio_url": ref,
            },
        )

        # Wait until frontend says narration finished
        while True:
            await asyncio.sleep(0.1)
            if status.stopped:
                return False
            if getattr(status, "narration_finished", False):
                logger.info("narration_frontend_finished phase=%s", log_phase)
                status.narration_finished = False
                return False

    # Resolve first, always
    ref = resolve_audio_ref(bucket, key)
    if not ref:
        logger.warning("narration_not_attempted phase=%s source=resolved has_audio_ref=false", log_phase)
        return False

    phase = (kind or "").strip().lower()  # "intro" | "detail" | "artist"
    gain_db = _gain_for_kind(phase)
    last_err: object | None = None

    async with current_runtime().play_lock:
        for attempt in range(1, _SUPA_FETCH_RETRIES + 1):
            try:
                await _respect_user_controls()
                _update_state_for_play(phase, bucket, key)

                # ─────────────────────────────────────────────
                # Download MP3 bytes (remote or local unified)
                # ─────────────────────────────────────────────
                if ref.startswith("http"):
                    async with httpx.AsyncClient(timeout=_SUPA_FETCH_TIMEOUT) as client:
                        resp = await client.get(ref)
                        resp.raise_for_status()
                        b = await resp.aread()
                else:
                    with open(ref, "rb") as f:
                        b = f.read()

                if len(b) < 1024 or not _looks_like_mp3(b):
                    raise RuntimeError("Bad MP3 download")

                # ─────────────────────────────────────────────
                # Duration is always computed from the real source
                # ─────────────────────────────────────────────
                duration = float(mp3_duration_seconds(ref) or 0.0)

                logger.info("narration_duration phase=%s source=%s", log_phase, _audio_source_label(ref))

                # Initialize state so status endpoint never shows zero timing
                update_phase(
                    user_id,
                    phase,
                    is_playing=True,
                    is_paused=False,
                    stopped=False,
                    elapsed_seconds=0.0,
                    duration_seconds=duration,
                    percent_complete=0.0,
                    context={
                        "bucket": bucket,
                        "key": key,
                        "audio_url": ref,
                        "voice_style": voice_style or "before",
                    },
                )

                await _respect_user_controls()

                # Single authority: narration timing lives here
                heartbeat_task = asyncio.create_task(_run_progress_heartbeat(phase, duration))
                bind_task(heartbeat_task, user_id)

                try:
                    # Playback in worker thread
                    if abs(gain_db) > 0.05:
                        play_task = asyncio.create_task(
                            asyncio.to_thread(_play_bytes_with_gain_sync, b, gain_db)
                        )
                    else:
                        play_task = asyncio.create_task(
                            asyncio.to_thread(_play_bytes_plain_sync, b)
                        )

                    # Cooperative loop for pause/stop + skip
                    while not play_task.done():
                        await _respect_user_controls()

                        if skip_event.is_set():
                            skip_event.clear()
                            logger.info("narration_skip_detected phase=%s", log_phase)
                            play_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError, Exception):
                                await play_task
                            return True

                        await asyncio.sleep(0.1)

                    rc = await play_task
                    if int(rc) != 0:
                        last_err = f"play rc={rc}"
                        raise RuntimeError(str(last_err))

                    # Final state
                    update_phase(
                        user_id,
                        phase,
                        elapsed_seconds=duration,
                        duration_seconds=duration,
                        percent_complete=1.0 if duration > 0 else 0.0,
                    )

                    return False

                finally:
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await heartbeat_task

            except asyncio.CancelledError:
                logger.info("narration_cancelled phase=%s", log_phase)
                return False

            except Exception as exc:
                last_err = exc
                error_class, http_status = _audio_error_diagnostic(exc)
                logger.warning(
                    "narration_attempt_failed phase=%s source=%s attempt=%d retry_limit=%d error_class=%s http_status=%d",
                    log_phase,
                    _audio_source_label(ref),
                    attempt,
                    _SUPA_FETCH_RETRIES,
                    error_class,
                    http_status,
                )

            if attempt < _SUPA_FETCH_RETRIES:
                await asyncio.sleep(_SUPA_BACKOFF ** attempt)

    error_class, http_status = _audio_error_diagnostic(last_err) if isinstance(last_err, BaseException) else ("unexpected", 0)
    logger.error(
        "narration_failed phase=%s source=%s retry_limit=%d error_class=%s http_status=%d",
        log_phase,
        _audio_source_label(ref),
        _SUPA_FETCH_RETRIES,
        error_class,
        http_status,
    )
    return False
