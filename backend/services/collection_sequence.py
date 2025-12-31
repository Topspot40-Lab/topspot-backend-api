from __future__ import annotations

import asyncio
import logging
import random
from typing import Literal

from sqlmodel import select

from backend.database import get_db_session
from backend.models.dbmodels import (
    Track,
    Artist,
    Collection,
    CollectionTrackRanking,
)

from backend.services.radio_runtime import (
    log_header_and_texts,
    collection_intro_jobs,
    narration_keys_for,
    play_narrations,
    play_track_with_skip,
)

from backend.services.spotify.playback import play_spotify_track
from backend.config.volume import PLAY_FULL_TRACK

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# COLLECTION PLAYBACK SEQUENCE (SERVICE)
# ─────────────────────────────────────────────
async def run_collection_sequence(
    *,
    collection_slug: str,
    start_rank: int,
    end_rank: int,
    mode: Literal["count_up", "count_down", "random"],
    tts_language: str,
    play_intro: bool,
    play_detail: bool,
    play_artist_description: bool,
    play_track: bool,
    text_intro: bool,
    text_detail: bool,
    text_artist_description: bool,
    voice_style: Literal["before", "over"] = "before",
):
    logger.info(
        "🎧 COLLECTION START: %s %s-%s mode=%s voice_style=%s",
        collection_slug,
        start_rank,
        end_rank,
        mode,
        voice_style,
    )

    # ─────────── DB FETCH ───────────
    with get_db_session() as db:
        stmt = (
            select(
                Track,
                Artist,
                CollectionTrackRanking.ranking,
            )
            .join(Artist, Artist.id == Track.artist_id)
            .join(CollectionTrackRanking, CollectionTrackRanking.track_id == Track.id)
            .join(Collection, Collection.id == CollectionTrackRanking.collection_id)
            .where(
                Collection.slug == collection_slug,
                CollectionTrackRanking.ranking >= start_rank,
                CollectionTrackRanking.ranking <= end_rank,
            )
            .order_by(CollectionTrackRanking.ranking)
        )

        rows = db.exec(stmt).all()

    if not rows:
        logger.warning("⚠️ No tracks found for collection: %s", collection_slug)
        return

    # ─────────── ORDERING ───────────
    if mode == "count_down":
        rows.reverse()
    elif mode == "random":
        random.shuffle(rows)
    # count_up already ordered by SQL

    # ─────────────────────────────────────────────
    # MAIN LOOP
    # ─────────────────────────────────────────────
    for track, artist, rank in rows:
        logger.info("──────────────────────────────────────────────")
        logger.info("▶ Rank #%02d: %s — %s", rank, track.track_name, artist.artist_name)

        log_header_and_texts(
            lang=tts_language,
            track=track,
            artist=artist,
            tr_rows=[],
        )

        intro_jobs = (
            collection_intro_jobs(
                lang=tts_language,
                collection_slug=collection_slug,
                rank=rank,
            )
            if play_intro
            else []
        )

        detail_bucket, detail_key, artist_bucket, artist_key = narration_keys_for(
            lang=tts_language,
            track=track,
            artist=artist,
        )

        # ─────────────────────────────────────────────
        # OVER MODE — track first
        # ─────────────────────────────────────────────
        if voice_style == "over" and play_track and track.spotify_track_id:
            play_spotify_track(track.spotify_track_id)

            # narration runs inline but ducks volume
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
                mode="collection",
                rank=rank,
                track_name=track.track_name,
                artist_name=artist.artist_name,
                voice_style="over",
            )

            await play_track_with_skip(
                track=track,
                lang=tts_language,
                mode="collection",
                rank=rank,
                track_name=track.track_name,
                artist_name=artist.artist_name,
                full_flag=PLAY_FULL_TRACK,
                already_playing=True,
            )

        # ─────────────────────────────────────────────
        # BEFORE MODE — narration first
        # ─────────────────────────────────────────────
        else:
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
                mode="collection",
                rank=rank,
                track_name=track.track_name,
                artist_name=artist.artist_name,
                voice_style="before",
            )

            if play_track:
                await play_track_with_skip(
                    track=track,
                    lang=tts_language,
                    mode="collection",
                    rank=rank,
                    track_name=track.track_name,
                    artist_name=artist.artist_name,
                    full_flag=PLAY_FULL_TRACK,
                )

        # small breathing room between tracks
        await asyncio.sleep(0.4)

    logger.info("✅ Collection playback finished cleanly.")
