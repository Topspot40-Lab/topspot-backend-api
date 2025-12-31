from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Query
from sqlmodel import select

from backend.database import get_db_session
from backend.models.dbmodels import Track, Artist
from backend.routers.playback_control import (
    start_new_sequence,
    cancel_current_sequence,
)

from backend.services.radio_runtime import (
    log_header_and_texts,
    build_intro_jobs,
    narration_keys_for,
    play_narrations,
    play_track_with_skip,
)

from backend.services.spotify.playback import play_spotify_track
from backend.config.volume import PLAY_FULL_TRACK

router = APIRouter(prefix="/supabase", tags=["Supabase: Single Track"])
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# INTERNAL: run a single track with narration
# ─────────────────────────────────────────────
async def _run_single_track(
    *,
    track_id: int,
    tts_language: str,
    play_intro: bool,
    play_detail: bool,
    play_artist_description: bool,
    play_track: bool,
    voice_style: Literal["before", "over"] = "before",
):
    logger.info("🎧 SINGLE-PLAY: track_id=%s voice_style=%s", track_id, voice_style)

    # ─────────── DB LOOKUP ───────────
    with get_db_session() as db:
        q = (
            select(Track, Artist)
            .join(Artist, Artist.id == Track.artist_id)
            .where(Track.id == track_id)
        )
        row = db.exec(q).first()

    if not row:
        logger.error("❌ Track id %s not found.", track_id)
        await cancel_current_sequence()
        return

    track, artist = row

    log_header_and_texts(
        lang=tts_language,
        track=track,
        artist=artist,
        tr_rows=[],
    )

    # ─────────── NARRATION METADATA ───────────
    intro_jobs = build_intro_jobs(
        lang=tts_language,
        tr_rows=[(None, None, None)],
    )

    detail_bucket, detail_key, artist_bucket, artist_key = narration_keys_for(
        lang=tts_language,
        track=track,
        artist=artist,
    )

    # ─────────────────────────────────────────────
    # OVER MODE — track starts first
    # ─────────────────────────────────────────────
    if voice_style == "over" and play_track and track.spotify_track_id:
        logger.info("🎧 SINGLE: over-track mode")

        play_spotify_track(track.spotify_track_id)
        await asyncio.sleep(0.4)

        await play_narrations(
            play_intro=play_intro,
            play_detail=play_detail,
            play_artist=play_artist_description,
            intro_jobs=intro_jobs,
            detail_bucket=detail_bucket,
            detail_key=detail_key,
            artist_bucket=artist_bucket,
            artist_key=artist_key,
            lang=tts_language,
            mode="single",
            rank=None,
            track_name=track.track_name,
            artist_name=artist.artist_name,
            voice_style="over",
        )

        await play_track_with_skip(
            track=track,
            lang=tts_language,
            mode="single",
            rank=None,
            track_name=track.track_name,
            artist_name=artist.artist_name,
            full_flag=PLAY_FULL_TRACK,
            already_playing=True,
        )

    # ─────────────────────────────────────────────
    # BEFORE MODE — narration first
    # ─────────────────────────────────────────────
    else:
        logger.info("🎧 SINGLE: before-track mode")

        await play_narrations(
            play_intro=play_intro,
            play_detail=play_detail,
            play_artist=play_artist_description,
            intro_jobs=intro_jobs,
            detail_bucket=detail_bucket,
            detail_key=detail_key,
            artist_bucket=artist_bucket,
            artist_key=artist_key,
            lang=tts_language,
            mode="single",
            rank=None,
            track_name=track.track_name,
            artist_name=artist.artist_name,
            voice_style="before",
        )

        if play_track and track.spotify_track_id:
            await play_track_with_skip(
                track=track,
                lang=tts_language,
                mode="single",
                rank=None,
                track_name=track.track_name,
                artist_name=artist.artist_name,
                full_flag=PLAY_FULL_TRACK,
            )

    await cancel_current_sequence()
    logger.info("✅ SINGLE-PLAY completed.")


# ─────────────────────────────────────────────
# PUBLIC ENDPOINT
# ─────────────────────────────────────────────
@router.get("/play-one")
async def play_one_track(
    track_id: int = Query(...),
    tts_language: str = Query("en"),
    play_intro: bool = Query(True),
    play_detail: bool = Query(True),
    play_artist_description: bool = Query(True),
    play_track: bool = Query(True),
    voice_style: Literal["before", "over"] = Query("before"),
):
    coro = _run_single_track(
        track_id=track_id,
        tts_language=tts_language,
        play_intro=play_intro,
        play_detail=play_detail,
        play_artist_description=play_artist_description,
        play_track=play_track,
        voice_style=voice_style,
    )

    await start_new_sequence(coro)

    return {
        "status": "started",
        "track_id": track_id,
        "voice_style": voice_style,
    }
