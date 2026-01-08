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
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)
from backend.services.supabase_playback import play_mp3
from backend.services.spotify.playback import play_spotify_track, stop_spotify_playback
from backend.services.play_policy import compute_play_seconds, sleep_with_skip
from backend.state.playback_state import status, update_phase
from backend.state.skip import skip_event
from backend.utils.tts_diagnostics import normalize_for_filename

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Playback User-Control Helpers
# ─────────────────────────────────────────────

async def _respect_user_controls() -> None:
    """Pause / stop cooperative checkpoint."""
    while status.is_paused:
        await asyncio.sleep(0.25)

    if status.stopped:
        logger.info("🛑 Playback stopped by user.")
        raise asyncio.CancelledError("Playback stopped")


def _update_state_for_play(kind: str, bucket: str, key: str) -> None:
    """Mark which audio asset is currently playing."""
    update_phase(
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
Kind = Literal["intro", "detail", "artist", "collections_intro"]

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

_play_lock = asyncio.Lock()


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
        prefix = "collections-intro"

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


def mp3_duration_seconds(b: bytes) -> float:
    """Return duration of MP3 bytes in seconds."""
    try:
        audio = MP3(BytesIO(b))
        return float(audio.info.length)
    except Exception:
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
        except Exception as e:
            logger.warning("ffplay volume-filter failed: %s", e)
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

async def safe_play(kind: str, bucket: str, key: str) -> bool:
    """
    Play a narration MP3 from Supabase while continuously updating playback_state.

    Returns:
      True  -> skip detected
      False -> finished normally (or not played)
    """
    if not (bucket and key):
        logger.warning("🚫 %s MP3 not attempted (empty bucket/key)", kind)
        return False

    phase = (kind or "").strip().lower()  # "intro" | "detail" | "artist" | ...

    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{key}"
    headers = {"Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"}

    # Optional HEAD probe (don’t fail hard if it errors)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            head = await client.head(url, headers=headers)
        if head.status_code != 200:
            logger.warning(
                "❌ %s MP3 missing: %s/%s (status=%s)",
                phase, bucket, key, head.status_code
            )
            return False
    except Exception:
        pass

    gain_db = _gain_for_kind(phase)
    last_err: object | None = None

    async with _play_lock:
        for attempt in range(1, _SUPA_FETCH_RETRIES + 1):
            try:
                await _respect_user_controls()
                _update_state_for_play(phase, bucket, key)

                # Download MP3 bytes
                async with httpx.AsyncClient(timeout=_SUPA_FETCH_TIMEOUT) as client:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    b = await resp.aread()

                if len(b) < 1024 or not _looks_like_mp3(b):
                    raise RuntimeError("Bad MP3 download")

                duration = float(mp3_duration_seconds(b) or 0.0)

                # ✅ Initialize state immediately so status endpoint never shows zeros
                update_phase(
                    phase,
                    is_playing=True,
                    is_paused=False,
                    stopped=False,
                    elapsed_seconds=0.0,
                    duration_seconds=duration,
                    percent_complete=0.0,
                    context={"bucket": bucket, "key": key},
                )

                await _respect_user_controls()

                # ✅ Single authority: narration timing lives here
                heartbeat_task = asyncio.create_task(_run_progress_heartbeat(phase, duration))

                try:
                    # Run actual playback in worker thread
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
                            logger.info("⏭️ Skip detected during %s narration.", phase)
                            play_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError, Exception):
                                await play_task
                            return True

                        await asyncio.sleep(0.1)

                    rc = await play_task
                    if int(rc) != 0:
                        last_err = f"play rc={rc}"
                        raise RuntimeError(str(last_err))

                    # ✅ Final state
                    update_phase(
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
                logger.info("🛑 %s playback cancelled by user", phase)
                return False
            except Exception as e:
                last_err = e
                logger.warning(
                    "⚠️ %s exception attempt %d/%d: %s",
                    phase, attempt, _SUPA_FETCH_RETRIES, e
                )

            if attempt < _SUPA_FETCH_RETRIES:
                await asyncio.sleep(_SUPA_BACKOFF ** attempt)

    logger.error(
        "❌ %s MP3 gave up after %d attempts: %s/%s :: %s",
        phase, _SUPA_FETCH_RETRIES, bucket, key, last_err
    )
    return False


# ─────────────────────────────────────────────
# 🎵 Spotify Track Playback
# ─────────────────────────────────────────────

async def play_track_with_skip(
    track,
    *,
    lang: str,
    mode: str,
    rank: int,
    track_name: str,
    artist_name: str,
) -> bool:
    spotify_id = getattr(track, "spotify_track_id", None)
    if not spotify_id:
        logger.warning("🚫 No spotify_track_id for %s — skipping.", track_name)
        return False

    try:
        await stop_spotify_playback(fade_out_seconds=0.8)
    except Exception:
        pass

    update_phase(
        "track",
        is_playing=True,
        language=lang,
        mode=mode,
        context={
            "spotify_track_id": spotify_id,
            "rank": rank,
            "track_name": track_name,
            "artist_name": artist_name,
        },
    )

    await _respect_user_controls()

    logger.info("🎵 Playing Spotify track: %s — rank %s", track_name, rank)

    ok = await play_spotify_track(spotify_id)
    if not ok:
        logger.warning("❌ Spotify refused playback.")
        return False

    play_secs = compute_play_seconds(track)
    skipped = await sleep_with_skip(skip_event, play_secs)

    try:
        await stop_spotify_playback(fade_out_seconds=1.0)
    except Exception:
        pass

    return skipped
