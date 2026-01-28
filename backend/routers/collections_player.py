from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from backend.routers.playback_control import start_new_sequence
from backend.services.collection_sequence import (
    run_collection_sequence,
    run_collection_continuous_sequence,
)

router = APIRouter(
    prefix="/supabase/collections",
    tags=["Supabase: Collections"],
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# PUBLIC — START COLLECTION PLAYBACK
# ─────────────────────────────────────────────
@router.get("/play-collection-sequence")
async def play_collection_sequence(
        collection_slug: str = Query(...),
        start_rank: int = Query(1),
        end_rank: int = Query(40),
        mode: Literal["count_up", "count_down", "random"] = Query("count_up"),
        continuous: bool = Query(False),  # 👈 add this
        tts_language: Literal["en", "es", "ptbr", "pt-BR"] = Query("en"),
        play_intro: bool = Query(True),
        play_detail: bool = Query(True),
        play_artist_description: bool = Query(True),
        play_track: bool = Query(True),
        text_intro: bool = Query(True),
        text_detail: bool = Query(False),
        text_artist_description: bool = Query(False),
        voice_style: Literal["before", "over"] = Query("before"),
):
    logger.info(
        "▶ COLLECTION REQUEST: slug=%s %s-%s mode=%s continuous=%s lang=%s "
        "intro=%s detail=%s artist=%s track=%s voice=%s",
        collection_slug,
        start_rank,
        end_rank,
        mode,
        continuous,
        tts_language,
        play_intro,
        play_detail,
        play_artist_description,
        play_track,
        voice_style,
    )

    try:
        if continuous:
            coro = run_collection_continuous_sequence(
                collection_slug=collection_slug,
                start_rank=start_rank,
                end_rank=end_rank,
                mode=mode,
                tts_language=tts_language,
                play_intro=play_intro,
                play_detail=play_detail,
                play_artist_description=play_artist_description,
                play_track=play_track,
                voice_style=voice_style,
            )
        else:
            coro = run_collection_sequence(
                collection_slug=collection_slug,
                start_rank=start_rank,
                end_rank=end_rank,
                mode=mode,
                tts_language=tts_language,
                play_intro=play_intro,
                play_detail=play_detail,
                play_artist_description=play_artist_description,
                play_track=play_track,
                text_intro=text_intro,
                text_detail=text_detail,
                text_artist_description=text_artist_description,
                voice_style=voice_style,
            )

        await start_new_sequence(coro)
    except Exception as exc:
        logger.exception("❌ Failed to start collection sequence")
        return JSONResponse(
            status_code=500,
            content={
                "error": "collection_start_failed",
                "detail": str(exc),
            },
        )

    return {
        "status": "started",
        "collection": collection_slug,
        "range": [start_rank, end_rank],
        "mode": mode,
        "continuous": continuous,
        "voice_style": voice_style,
    }
