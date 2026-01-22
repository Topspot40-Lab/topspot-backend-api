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

from backend.state.playback_state import mark_playing, update_phase
from backend.services.audio_urls import resolve_audio_ref, is_remote_audio

from backend.services.radio_runtime import (
    log_header_and_texts,
    collection_intro_jobs,
    narration_keys_for,
)

logger = logging.getLogger(__name__)


def _extract_bucket_key(job):
    """
    Supports:
      - tuple/list: (bucket, key, ...)
      - dict: {"bucket": "...", "key": "..."} (or object_path)
      - object: .bucket / .key / .object_path
    """
    if job is None:
        return None, None

    if isinstance(job, (tuple, list)) and len(job) >= 2:
        return job[0], job[1]

    if isinstance(job, dict):
        return job.get("bucket"), job.get("key") or job.get("object_path")

    bucket = getattr(job, "bucket", None)
    key = getattr(job, "key", None) or getattr(job, "object_path", None)
    return bucket, key


# ─────────────────────────────────────────────
# COLLECTION PLAYBACK SEQUENCE (PUBLISHER ONLY)
# One-rank-at-a-time: publishes intro url + spotify_track_id then returns.
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

    # Tell frontend a sequence is active
    mark_playing(mode="collection", language=tts_language)

    # ─────────── ORDERING ───────────
    if mode == "count_down":
        rows.reverse()
    elif mode == "random":
        random.shuffle(rows)

    # ✅ CRITICAL: publish ONE rank only, then return
    # Frontend Next/Prev calls this endpoint again with a new start_rank.
    track, artist, rank = rows[0]

    logger.info("──────────────────────────────────────────────")
    logger.info("▶ Rank #%02d: %s — %s", rank, track.track_name, artist.artist_name)

    log_header_and_texts(
        lang=tts_language,
        track=track,
        artist=artist,
        tr_rows=[],
    )

    # ─────────────────────────────────────────────
    # INTRO PHASE (publish URL for frontend)
    # ─────────────────────────────────────────────
    if play_intro:
        intro_jobs = collection_intro_jobs(
            lang=tts_language,
            collection_slug=collection_slug,
            rank=rank,
        )
    else:
        intro_jobs = []

    if play_intro and intro_jobs:
        j0 = intro_jobs[0]
        bucket, key = _extract_bucket_key(j0)

        if bucket and key:
            audio_url = resolve_audio_ref(bucket, key)

            update_phase(
                "intro",
                track_name=track.track_name,
                artist_name=artist.artist_name,
                current_rank=int(rank),
                context={
                    "mode": "collection",
                    "collection_slug": collection_slug,
                    "bucket": bucket,
                    "key": key,
                    "audio_url": audio_url,
                    "source": "remote" if is_remote_audio() else "local",
                    "voice_style": voice_style,
                },
            )

            logger.info("🎙 Published INTRO frame: %s", audio_url)

            # wait for frontend to finish playing narration
            from backend.state.skip import skip_event

            if voice_style == "before":
                logger.info("⏸ Waiting for narration to finish (before mode)")
                skip_event.clear()
                await skip_event.wait()

        else:
            logger.warning("⚠️ Intro job malformed: %r", j0)

    # ─────────────────────────────────────────────
    # OPTIONAL: publish detail/artist URLs too (same pattern)
    # (kept here but off unless flags are true)
    # ─────────────────────────────────────────────
    detail_bucket, detail_key, artist_bucket, artist_key = narration_keys_for(
        lang=tts_language,
        track=track,
        artist=artist,
    )

    if play_detail and detail_bucket and detail_key:
        detail_url = resolve_audio_ref(detail_bucket, detail_key)
        update_phase(
            "detail",
            track_name=track.track_name,
            artist_name=artist.artist_name,
            current_rank=int(rank),
            context={
                "mode": "collection",
                "collection_slug": collection_slug,
                "bucket": detail_bucket,
                "key": detail_key,
                "audio_url": detail_url,
                "source": "remote" if is_remote_audio() else "local",
                "voice_style": voice_style,
            },
        )
        logger.info("🧾 Published DETAIL frame: %s", detail_url)
        await asyncio.sleep(0.15)

    if play_artist_description and artist_bucket and artist_key:
        artist_url = resolve_audio_ref(artist_bucket, artist_key)
        update_phase(
            "artist",
            track_name=track.track_name,
            artist_name=artist.artist_name,
            current_rank=int(rank),
            context={
                "mode": "collection",
                "collection_slug": collection_slug,
                "bucket": artist_bucket,
                "key": artist_key,
                "audio_url": artist_url,
                "source": "remote" if is_remote_audio() else "local",
                "voice_style": voice_style,
            },
        )
        logger.info("👤 Published ARTIST frame: %s", artist_url)
        await asyncio.sleep(0.15)

    logger.warning(
        "DEBUG BEFORE TRACK: play_track=%s spotify_id=%s",
        play_track,
        track.spotify_track_id,
    )

    # ─────────────────────────────────────────────
    # TRACK PHASE (publish spotify id for frontend to request playback)
    # ─────────────────────────────────────────────
    if play_track and track.spotify_track_id:
        update_phase(
            "track",
            track_name=track.track_name,
            artist_name=artist.artist_name,
            current_rank=int(rank),
            context={
                "mode": "spotify",
                "collection_slug": collection_slug,
                "spotify_track_id": track.spotify_track_id,
            },
        )
        logger.info("🎯 PUBLISHED track frame rank=%s spotify=%s", rank, track.spotify_track_id)

    logger.info("✅ Collection publish finished (single-rank).")
