from __future__ import annotations

import asyncio
import logging
import random

from backend.state.playback_state import status, mark_playing, update_phase
from backend.state.playback_flags import flags
from backend.state.narration import track_done_event
from backend.services.collections_radio_loader import get_valid_collections, load_collection_rows
from backend.services.block_builder import build_track_block
from backend.services.collection_sequence import publish_narration_phase, _extract_bucket_key
from backend.services.radio_runtime import collection_intro_jobs, narration_keys_for
from backend.services.audio_urls import resolve_audio_ref
from backend.services.bed_tracks import BED_BUCKET, get_collection_group_bed_key

logger = logging.getLogger(__name__)


async def run_collections_radio_sequence(
        *,
        tts_language: str = "en",
        collection_group_slug: str | None = None,
        voices: list[str] | None = None,
        voice_style: str = "before",
) -> None:
    voices = voices or []

    play_intro = "intro" in voices
    play_detail = "detail" in voices
    play_artist = "artist" in voices

    logger.info(
        "🎛️ COLLECTIONS RADIO FLAGS | intro=%s detail=%s artist=%s",
        play_intro,
        play_detail,
        play_artist,
    )

    status.stopped = False
    status.cancel_requested = False
    status.language = tts_language

    flags.is_playing = True
    flags.stopped = False
    flags.cancel_requested = False
    flags.mode = "collections_radio"

    mark_playing(
        mode="collection",
        language=tts_language,
        context={
            "mode": "collections_radio",
            "collection_group_slug": collection_group_slug or "ALL",
        },
    )

    from backend.database import get_db_session

    try:
        with get_db_session() as session:
            collections = get_valid_collections(session, collection_group_slug)

        if not collections:
            logger.warning("No collections found for group=%s", collection_group_slug)
            return

        random.shuffle(collections)

        set_number = 0

        while True:
            for collection_meta in collections:
                if status.stopped:
                    logger.info("🛑 Collections radio stopped")
                    return

                set_number += 1

                collection_slug = collection_meta["collection_slug"]
                collection_name = collection_meta["collection_name"]
                group_slug = collection_meta["collection_group_slug"]
                group_name = collection_meta["collection_group_name"]

                logger.info(
                    "🎲 COLLECTION SET chosen: %s (%s)",
                    collection_name,
                    group_name,
                )

                update_phase(
                    "loading",
                    track_name="",
                    artist_name="",
                    context={
                        "mode": "collections_radio",
                        "collection_slug": collection_slug,
                        "collection_name": collection_name,
                        "collection_group_slug": group_slug,
                        "collection_group_name": group_name,
                        "set_number": set_number,
                    },
                )

                with get_db_session() as session:
                    rows = await asyncio.to_thread(load_collection_rows, session, collection_slug, tts_language)

                if not rows:
                    logger.warning("No rows for collection=%s", collection_slug)
                    continue

                block_rows = build_track_block(rows, set_number=set_number)

                for idx, (track, artist, ctr, collection, ctr_locale, track_locale, artist_locale) in enumerate(
                        block_rows, start=1):
                    if status.stopped:
                        logger.info("🛑 Collections radio stopped")
                        return

                    rank = ctr.ranking
                    status.current_rank = rank
                    status.current_ranking_id = ctr.id
                    flags.current_rank = rank

                    radio_context = {
                        "mode": "collections_radio",
                        "collection_slug": collection_slug,
                        "collection_name": collection_name,
                        "collection_group_slug": group_slug,
                        "collection_group_name": group_name,
                        "set_number": set_number,
                        "block_size": len(block_rows),
                        "block_position": idx,
                        "ranking_id": ctr.id,
                        "album_artwork": getattr(track, "album_artwork", None),
                        "artist_artwork": getattr(artist, "artist_artwork", None),
                        "spotify_track_id": getattr(track, "spotify_track_id", None),
                        "track_name": getattr(track, "track_name", None),
                        "artist_name": getattr(artist, "artist_name", None),
                        "intro": (
                                getattr(ctr_locale, "intro_text", None)
                                or getattr(ctr, "intro_text", None)
                                or getattr(ctr, "intro", None)
                        ),
                        "detail": (
                                getattr(track_locale, "detail_text", None)
                                or getattr(track, "detail", None)
                                or getattr(track, "detail_text", None)
                        ),
                        "artist_text": (
                                getattr(artist_locale, "artist_description_text", None)
                                or getattr(artist, "artist_description", None)
                                or getattr(artist, "artist_description_text", None)
                        ),
                    }

                    # We'll wire liner / set_intro / intro-detail-artist / track next
                    logger.info(
                        "🎵 COLLECTION TRACK %d/%d | %s — %s",
                        idx,
                        len(block_rows),
                        track.track_name,
                        artist.artist_name,
                    )

                    # ───────── BED TRACK ─────────
                    bed_key = get_collection_group_bed_key(group_slug)
                    bed_audio_url = resolve_audio_ref(BED_BUCKET, bed_key)

                    # ───────── COLLECTION SET INTRO ─────────
                    if idx == 1:
                        logger.info(
                            "🎬 COLLECTION SET INTRO | %s",
                            collection_slug,
                        )

                        if tts_language == "en":
                            set_intro_bucket = getattr(collection, "set_intro_tts_bucket", None)
                            set_intro_key = getattr(collection, "set_intro_tts_key", None)
                        else:
                            set_intro_bucket = getattr(ctr_locale, "set_intro_tts_bucket", None)
                            set_intro_key = getattr(ctr_locale, "set_intro_tts_key", None)

                        logger.info(
                            "🧪 set intro mp3 | %s/%s",
                            set_intro_bucket,
                            set_intro_key,
                        )

                        if set_intro_bucket and set_intro_key:
                            await publish_narration_phase(
                                "collection_intro",
                                track=track,
                                artist=artist,
                                rank=rank,
                                collection_slug=collection_slug,
                                bucket=set_intro_bucket,
                                key=set_intro_key,
                                voice_style=voice_style,
                                extra_context={
                                    **radio_context,
                                    "bed_bucket": BED_BUCKET,
                                    "bed_key": bed_key,
                                    "bed_audio_url": bed_audio_url,
                                },
                            )


                    # ───────── INTRO ─────────
                    if play_intro:
                        intro_jobs = collection_intro_jobs(
                            lang=tts_language,
                            collection_slug=collection_slug,
                            rank=rank,
                        )

                        logger.info("🧪 intro_jobs: %s", intro_jobs)


                        if intro_jobs:
                            bucket, key = _extract_bucket_key(intro_jobs[0])

                            if bucket and key:
                                await publish_narration_phase(
                                    "intro",
                                    track=track,
                                    artist=artist,
                                    rank=rank,
                                    collection_slug=collection_slug,
                                    bucket=bucket,
                                    key=key,
                                    voice_style=voice_style,
                                    extra_context={
                                        **radio_context,
                                        "bed_bucket": BED_BUCKET,
                                        "bed_key": bed_key,
                                        "bed_audio_url": bed_audio_url,
                                    },
                                )

                    detail_bucket, detail_key, artist_bucket, artist_key = narration_keys_for(
                        lang=tts_language,
                        track=track,
                        artist=artist,
                    )

                    logger.info(
                        "🧪 narration keys | detail=%s/%s artist=%s/%s",
                        detail_bucket,
                        detail_key,
                        artist_bucket,
                        artist_key,
                    )

                    # ───────── DETAIL ─────────
                    if play_detail and detail_bucket and detail_key:
                        await publish_narration_phase(
                            "detail",
                            track=track,
                            artist=artist,
                            rank=rank,
                            collection_slug=collection_slug,
                            bucket=detail_bucket,
                            key=detail_key,
                            voice_style=voice_style,
                            extra_context={
                                **radio_context,
                                "bed_bucket": BED_BUCKET,
                                "bed_key": bed_key,
                                "bed_audio_url": bed_audio_url,
                            },
                        )

                    # ───────── ARTIST ─────────
                    if play_artist and artist_bucket and artist_key:
                        await publish_narration_phase(
                            "artist",
                            track=track,
                            artist=artist,
                            rank=rank,
                            collection_slug=collection_slug,
                            bucket=artist_bucket,
                            key=artist_key,
                            voice_style=voice_style,
                            extra_context={
                                **radio_context,
                                "bed_bucket": BED_BUCKET,
                                "bed_key": bed_key,
                                "bed_audio_url": bed_audio_url,
                            },
                        )

                    # ───────── TRACK ─────────
                    if getattr(track, "spotify_track_id", None):
                        track_done_event.clear()

                        update_phase(
                            "track",
                            track_name=track.track_name,
                            artist_name=artist.artist_name,
                            current_rank=rank,
                            context={
                                **radio_context,
                                "mode": "spotify",
                                "spotify_track_id": track.spotify_track_id,
                                "collection_name": collection_name,
                                "collection_group_name": group_name,
                            },
                        )

                        await track_done_event.wait()

    except asyncio.CancelledError:
        logger.info("⛔ Collections radio cancelled")
        raise

    finally:
        flags.is_playing = False
        flags.stopped = True
        logger.info("📻 Collections radio stopped")
