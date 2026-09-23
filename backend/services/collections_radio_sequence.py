from __future__ import annotations

import asyncio
import logging
import random

from backend.state.playback_state import begin_track, get_status, mark_playing, update_phase
from backend.state.playback_flags import flags
from backend.state.narration import track_done_event
from backend.state.playback_runtime import current_runtime, current_user_id
from backend.services.collections_radio_loader import get_valid_collections, load_collection_rows
from backend.services.block_builder import build_track_block
from backend.services.collection_sequence import publish_narration_phase, _extract_bucket_key
from backend.services.decade_genre_sequence import publish_narration_queue_phase
from backend.services.radio_runtime import collection_intro_jobs, narration_keys_for, short_detail_keys_for
from backend.services.audio_urls import resolve_audio_ref
from backend.services.bed_tracks import BED_BUCKET, get_collection_group_bed_key
from backend.services.radio_selection import (
    unused_session_candidates,
    unused_source_candidates,
)

from sqlmodel import select

from backend.database import get_db_session
from backend.models.collection_models import CollectionTrackRankingLocale
from backend.models.dbmodels import TrackLocale, ArtistLocale

logger = logging.getLogger(__name__)

def build_collection_radio_texts_by_language(session, *, ctr, track, artist) -> dict:
    ctr_locales = session.exec(
        select(CollectionTrackRankingLocale)
        .where(CollectionTrackRankingLocale.collection_track_ranking_id == ctr.id)
    ).all()

    track_locales = session.exec(
        select(TrackLocale)
        .where(TrackLocale.track_id == track.id)
    ).all()

    artist_locales = session.exec(
        select(ArtistLocale)
        .where(ArtistLocale.artist_id == artist.id)
    ).all()

    ctr_by_lang = {row.lang: row for row in ctr_locales}
    track_by_lang = {row.language_code: row for row in track_locales}
    artist_by_lang = {row.language_code: row for row in artist_locales}

    return {
        "en": {
            "intro": getattr(ctr, "intro", None) or getattr(ctr, "intro_text", None),
            "detail": getattr(track, "detail", None) or getattr(track, "detail_text", None),
            "artist": getattr(artist, "artist_description", None),
        },
        "es": {
            "intro": getattr(ctr_by_lang.get("es"), "intro_text", None),
            "detail": getattr(track_by_lang.get("es"), "detail_text", None),
            "artist": getattr(artist_by_lang.get("es"), "artist_description_text", None),
        },
        "ptbr": {
            "intro": (
                getattr(ctr_by_lang.get("ptbr"), "intro_text", None)
                or getattr(ctr_by_lang.get("pt-BR"), "intro_text", None)
            ),
            "detail": (
                getattr(track_by_lang.get("ptbr"), "detail_text", None)
                or getattr(track_by_lang.get("pt-BR"), "detail_text", None)
            ),
            "artist": (
                getattr(artist_by_lang.get("ptbr"), "artist_description_text", None)
                or getattr(artist_by_lang.get("pt-BR"), "artist_description_text", None)
            ),
        },
    }


def detail_audio_keys_for_collections_radio(*, detail_length: str, lang: str, track, artist):
    """Use the same short/full asset selection as Nostalgia Radio."""
    if detail_length == "short":
        bucket, key = short_detail_keys_for(lang=lang, track=track)
        logger.info(
            "collections_radio_detail_resolved module=%s detail_length=short bucket=%s key=%s",
            __file__, bucket, key,
        )
        return bucket, key
    detail_bucket, detail_key, _, _ = narration_keys_for(
        lang=lang,
        track=track,
        artist=artist,
    )
    logger.info(
        "collections_radio_detail_resolved module=%s detail_length=%s bucket=%s key=%s",
        __file__, detail_length, detail_bucket, detail_key,
    )
    return detail_bucket, detail_key


async def run_collections_radio_sequence(
        *,
        tts_language: str = "en",
        tts_languages: list[str] | None = None,
        collection_group_slug: str | None = None,
        collection_group_slugs: list[str] | None = None,
        voices: list[str] | None = None,
        detail_length: str = "long",
        voice_style: str = "before",
) -> None:
    user_id = current_user_id()
    status = current_runtime().status
    voices = voices or []

    play_intro = "intro" in voices
    if detail_length not in {"off", "short", "long"}:
        raise ValueError("detail_length must be one of: off, short, long")
    play_detail = "detail" in voices and detail_length != "off"
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

    logger.info(
        "collections_radio_runner_launch module=%s detail_length=%s voice_style=%s groups=%s legacy_group=%s",
        __file__, detail_length, voice_style, collection_group_slugs, collection_group_slug,
    )

    def normalize_lang(value: str) -> str:
        v = (value or "en").lower()
        if v in ("pt-br", "ptbr", "pt_br"):
            return "ptbr"
        if v == "es":
            return "es"
        return "en"

    langs = [
        normalize_lang(x)
        for x in (tts_languages or [tts_language])
    ]

    langs = list(dict.fromkeys(langs))

    logger.info("🌎 COLLECTION RADIO LANGUAGES: %s", langs)

    flags.is_playing = True
    flags.stopped = False
    flags.cancel_requested = False
    flags.mode = "collections_radio"

    mark_playing(
        user_id=user_id,
        mode="collection",
        language=tts_language,
        context={
            "mode": "collections_radio",
            "collection_group_slug": collection_group_slug or "ALL",
        },
    )

    try:
        with get_db_session() as session:
            collections = get_valid_collections(
                session,
                collection_group_slug,
                collection_group_slugs,
            )

        if not collections:
            logger.warning("No collections found for group=%s", collection_group_slug)
            return

        set_number = 0
        used_collection_slugs: set[object] = set()
        played_track_ids: set[object] = set()

        while True:
            unused_collections = unused_source_candidates(
                collections,
                used_collection_slugs,
                lambda collection: collection["collection_slug"],
            )

            while unused_collections:
                collection_meta = random.choice(unused_collections)
                unused_collections.remove(collection_meta)
                if status.stopped:
                    logger.info("🛑 Collections radio stopped")
                    return

                set_number += 1

                collection_slug = collection_meta["collection_slug"]
                used_collection_slugs.add(collection_slug)
                collection_name = collection_meta["collection_name"]
                group_slug = collection_meta["collection_group_slug"]
                group_name = collection_meta["collection_group_name"]

                logger.info(
                    "🎲 COLLECTION SET chosen: %s (%s)",
                    collection_name,
                    group_name,
                )

                update_phase(
                    user_id,
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
                    rows = await asyncio.to_thread(
                        load_collection_rows,
                        session,
                        collection_slug,
                        tts_language,
                    )

                    if not rows:
                        logger.warning("No rows for collection=%s", collection_slug)
                        continue

                    eligible_rows = unused_session_candidates(
                        rows,
                        played_track_ids,
                        lambda row: getattr(row[0], "id", None),
                    )
                    block_rows = build_track_block(eligible_rows, set_number=set_number)
                    played_track_ids.update(
                        getattr(row[0], "id", None) for row in block_rows
                    )

                    for idx, (track, artist, ctr, collection, ctr_locale, track_locale, artist_locale) in enumerate(
                            block_rows,
                            start=1,
                    ):
                        if status.stopped:
                            logger.info("🛑 Collections radio stopped")
                            return

                        rank = ctr.ranking
                        status.current_rank = rank
                        status.current_ranking_id = ctr.id
                        flags.current_rank = rank

                        texts_by_language = build_collection_radio_texts_by_language(
                            session,
                            ctr=ctr,
                            track=track,
                            artist=artist,
                        )

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
                            "textsByLanguage": texts_by_language,
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

                            logger.info("set_intro_audio_prepared source=collections_radio")

                            if set_intro_bucket and set_intro_key:
                                await publish_narration_phase(
                                    "collection_intro",
                                    user_id=user_id,
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
                            intro_audio_queue = []

                            for narration_lang in langs:
                                intro_jobs = collection_intro_jobs(
                                    lang=narration_lang,
                                    collection_slug=collection_slug,
                                    rank=rank,
                                )

                                if not intro_jobs:
                                    continue

                                bucket, key = _extract_bucket_key(intro_jobs[0])

                                if not bucket or not key:
                                    continue

                                intro_audio_queue.append({
                                    "language": narration_lang,
                                    "bucket": bucket,
                                    "key": key,
                                    "url": resolve_audio_ref(bucket, key),
                                })

                            if intro_audio_queue:
                                await publish_narration_queue_phase(
                                    "intro",
                                    track=track,
                                    artist=artist,
                                    rank=rank,
                                    decade=collection_name,
                                    genre=group_name,
                                    audio_queue=intro_audio_queue,
                                    texts={},
                                    voice_style=voice_style,
                                    extra_context={
                                        **radio_context,
                                        "bed_bucket": BED_BUCKET,
                                        "bed_key": bed_key,
                                        "bed_audio_url": bed_audio_url,
                                    },
                                )

                        # ───────── DETAIL / ARTIST KEYS ─────────
                        detail_by_lang = {}
                        artist_by_lang = {}

                        for narration_lang in langs:
                            detail_by_lang[narration_lang] = detail_audio_keys_for_collections_radio(
                                detail_length=detail_length,
                                lang=narration_lang,
                                track=track,
                                artist=artist,
                            )
                            _, _, abucket, akey = narration_keys_for(
                                lang=narration_lang,
                                track=track,
                                artist=artist,
                            )
                            artist_by_lang[narration_lang] = (abucket, akey)

                        # ───────── DETAIL ─────────
                        if play_detail:
                            detail_audio_queue = []

                            for narration_lang in langs:
                                detail_bucket, detail_key = detail_by_lang.get(
                                    narration_lang,
                                    (None, None),
                                )

                                if not detail_bucket or not detail_key:
                                    continue

                                detail_audio_queue.append({
                                    "language": narration_lang,
                                    "bucket": detail_bucket,
                                    "key": detail_key,
                                    "url": resolve_audio_ref(detail_bucket, detail_key),
                                })

                            if detail_audio_queue:
                                logger.info(
                                    "collections_radio_detail_publish detail_length=%s audio_queue=%s",
                                    detail_length,
                                    [
                                        {"bucket": item["bucket"], "key": item["key"], "url": item["url"]}
                                        for item in detail_audio_queue
                                    ],
                                )
                                await publish_narration_queue_phase(
                                    "detail",
                                    track=track,
                                    artist=artist,
                                    rank=rank,
                                    decade=collection_name,
                                    genre=group_name,
                                    audio_queue=detail_audio_queue,
                                    texts={},
                                    voice_style=voice_style,
                                    extra_context={
                                        **radio_context,
                                        "bed_bucket": BED_BUCKET,
                                        "bed_key": bed_key,
                                        "bed_audio_url": bed_audio_url,
                                    },
                                )

                        # ───────── ARTIST ─────────
                        if play_artist:
                            artist_audio_queue = []

                            for narration_lang in langs:
                                artist_bucket, artist_key = artist_by_lang.get(
                                    narration_lang,
                                    (None, None),
                                )

                                if not artist_bucket or not artist_key:
                                    continue

                                artist_audio_queue.append({
                                    "language": narration_lang,
                                    "bucket": artist_bucket,
                                    "key": artist_key,
                                    "url": resolve_audio_ref(artist_bucket, artist_key),
                                })

                            if artist_audio_queue:
                                await publish_narration_queue_phase(
                                    "artist",
                                    track=track,
                                    artist=artist,
                                    rank=rank,
                                    decade=collection_name,
                                    genre=group_name,
                                    audio_queue=artist_audio_queue,
                                    texts={},
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
                            track_done_event(user_id).clear()
                            begin_track(user_id, (getattr(track, "duration_ms", 0) or 0) / 1000.0)

                            update_phase(
                                user_id,
                                "track",
                                is_playing=True,
                                stopped=False,
                                track_name=track.track_name,
                                artist_name=artist.artist_name,
                                current_rank=rank,
                                current_ranking_id=ctr.id,
                                spotify_track_id=track.spotify_track_id,
                                context={
                                    **radio_context,
                                    "mode": "spotify",
                                    "spotify_track_id": track.spotify_track_id,
                                    "collection_name": collection_name,
                                    "collection_group_name": group_name,
                                },
                            )
                            public_status = get_status(user_id)
                            logger.info(
                                "collections_radio_track_published phase=%s ranking_id=%s spotify_id=%s "
                                "public_phase=%s public_rank=%s public_ranking_id=%s public_spotify_id=%s "
                                "public_context_ranking_id=%s public_context_spotify_id=%s",
                                "track",
                                ctr.id,
                                track.spotify_track_id,
                                public_status.phase,
                                public_status.current_rank,
                                public_status.current_ranking_id,
                                getattr(public_status, "spotify_track_id", None),
                                (public_status.context or {}).get("ranking_id"),
                                (public_status.context or {}).get("spotify_track_id"),
                            )

                            await track_done_event(user_id).wait()

    except asyncio.CancelledError:
        logger.info("⛔ Collections radio cancelled")
        raise

    finally:
        flags.is_playing = False
        flags.stopped = True
        logger.info("📻 Collections radio stopped")
