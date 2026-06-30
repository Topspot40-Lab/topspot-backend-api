from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

from backend.state.skip import skip_event
from backend.state.playback_state import update_phase
from backend.services.spotify.playback import (
    play_spotify_track,
    stop_spotify_playback,
    set_device_volume,
)
from backend.config import SPOTIFY_BED_TRACK_ID
from backend.services.playback_helpers import safe_play
from backend.state.playback_runtime import bind_task, current_runtime, current_user_id

logger = logging.getLogger(__name__)

# Single lock so intros/details/artist narrations never overlap
_narration_lock = asyncio.Lock()


async def _respect_user_controls() -> None:
    status = current_runtime().status
    while status.is_paused:
        await asyncio.sleep(0.25)


async def _run_voice_clip_with_skip(
    kind: str,
    bucket: str,
    key: str,
    *,
    voice_style: str,
) -> bool:
    user_id = current_user_id()
    play_task = asyncio.create_task(
        safe_play(kind, bucket, key, voice_style=voice_style)
    )
    bind_task(play_task, user_id)

    try:
        while not play_task.done():
            await _respect_user_controls()

            if skip_event.is_set():
                skip_event.clear()
                logger.info("⏭ Skip during %s narration; cancelling clip.", kind)
                play_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await play_task
                return True

            await asyncio.sleep(0.1)

        await play_task
        return False

    except asyncio.CancelledError:
        play_task.cancel()
        with contextlib.suppress(Exception):
            await play_task
        raise


async def play_narrations(
    *,
    play_intro: bool,
    play_detail: bool,
    play_artist: bool,
    intro_jobs,
    detail_bucket,
    detail_key,
    artist_bucket,
    artist_key,
    lang: str = "en",
    mode: str = "decade_genre",
    rank: Optional[int] = None,
    track_name: Optional[str] = None,
    artist_name: Optional[str] = None,
    voice_style: str = "before",  # "before" | "over"
) -> None:
    """
    voice_style = "before": bed track for intro, then dry detail/artist
    voice_style = "over": assume main track already playing, duck volume and narrate over it
    """
    async with _narration_lock:
        user_id = current_user_id()
        try:
            # Clear stale skip
            if skip_event.is_set():
                skip_event.clear()

            await _respect_user_controls()

            if skip_event.is_set():
                skip_event.clear()
                logger.info("⏭ Skip already set — skipping narration phase.")
                return

            # ───────────── VOICE OVER MODE ─────────────
            if voice_style == "over":
                ducked = False
                try:
                    any_voice = (
                        (play_intro and intro_jobs)
                        or (play_detail and detail_bucket and detail_key)
                        or (play_artist and artist_bucket and artist_key)
                    )
                    if any_voice:
                        with contextlib.suppress(Exception):
                            await set_device_volume(40, user_id)
                            ducked = True
                            logger.info("🔉 Ducking Spotify volume for narration.")

                    if play_intro and intro_jobs:
                        update_phase(user_id, "intro", current_rank=rank,
                                     track_name=track_name, artist_name=artist_name)
                        for bkt, key, *_ in intro_jobs:
                            skipped = await _run_voice_clip_with_skip(
                                "intro", bkt, key, voice_style=voice_style
                            )
                            if skipped:
                                return

                    if play_detail and detail_bucket and detail_key:
                        update_phase(user_id, "detail", current_rank=rank,
                                     track_name=track_name, artist_name=artist_name)
                        skipped = await _run_voice_clip_with_skip(
                            "detail", detail_bucket, detail_key, voice_style=voice_style
                        )
                        if skipped:
                            return

                    if play_artist and artist_bucket and artist_key:
                        update_phase(user_id, "artist", current_rank=rank,
                                     track_name=track_name, artist_name=artist_name)
                        skipped = await _run_voice_clip_with_skip(
                            "artist", artist_bucket, artist_key, voice_style=voice_style
                        )
                        if skipped:
                            return
                finally:
                    if ducked:
                        with contextlib.suppress(Exception):
                            await set_device_volume(100, user_id)
                return

            # ───────────── VOICE BEFORE MODE ─────────────
            if play_intro and intro_jobs:
                update_phase(user_id, "intro", current_rank=rank,
                             track_name=track_name, artist_name=artist_name)

                await play_spotify_track(SPOTIFY_BED_TRACK_ID, user_id)
                try:
                    for bkt, key, *_ in intro_jobs:
                        skipped = await _run_voice_clip_with_skip(
                            "intro", bkt, key, voice_style=voice_style
                        )
                        if skipped:
                            break
                finally:
                    with contextlib.suppress(Exception):
                        await stop_spotify_playback(user_id, fade_out_seconds=1.2)

            if play_detail and detail_bucket and detail_key:
                update_phase(user_id, "detail", current_rank=rank,
                             track_name=track_name, artist_name=artist_name)
                skipped = await _run_voice_clip_with_skip(
                    "detail", detail_bucket, detail_key, voice_style=voice_style
                )
                if skipped:
                    return

            if play_artist and artist_bucket and artist_key:
                update_phase(user_id, "artist", current_rank=rank,
                             track_name=track_name, artist_name=artist_name)
                skipped = await _run_voice_clip_with_skip(
                    "artist", artist_bucket, artist_key, voice_style=voice_style
                )
                if skipped:
                    return

        except asyncio.CancelledError:
            logger.info("⏹ Narration aborted.")
            with contextlib.suppress(Exception):
                await stop_spotify_playback(user_id, fade_out_seconds=1.0)
            raise
