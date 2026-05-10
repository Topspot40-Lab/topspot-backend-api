from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Literal

from backend.services.decade_genre_loader import load_decade_genre_rows
from backend.services.playback_ordering import order_rows_for_mode
from backend.state.narration import narration_done_event, track_done_event
from backend.services.bed_tracks import BED_BUCKET, get_genre_bed_key
from backend.services.audio_urls import resolve_audio_ref

# Legacy flags (still used by runtime helpers)
from backend.state.playback_flags import flags

from backend.services.radio_runtime import (
    log_header_and_texts,
    build_intro_jobs,
    narration_keys_for,
)

from backend.services.audio_urls import resolve_audio_ref, is_remote_audio

from backend.state.playback_state import (
    status,
    mark_playing,
    update_phase,
)

from backend.state.narration import narration_done_event

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


async def publish_narration_phase(
        phase: Literal["set_intro", "liner", "intro", "detail", "artist"],
        *,
        track,
        artist,
        rank: int,
        decade: str,
        genre: str,
        bucket: str,
        key: str,
        voice_style: Literal["before", "over"],
        extra_context: dict | None = None,
):
    audio_url = resolve_audio_ref(bucket, key)

    logger.info("🎙 publish_narration_phase phase=%s decade=%s genre=%s bucket=%s key=%s",
                phase, decade, genre, bucket, key)

    base_context = {
        "lang": getattr(status, "language", None),
        "mode": "decade_genre",
        "decade": decade,
        "genre": genre,
        "rank": int(rank),
        "track_name": track.track_name,
        "artist_name": artist.artist_name,
        "bucket": bucket,
        "key": key,
        "audio_url": audio_url,
        "source": "remote" if is_remote_audio() else "local",
        "voice_style": voice_style,

        # artwork + ids for UI continuity
        "spotify_track_id": getattr(track, "spotify_track_id", None),
        "album_artwork": getattr(track, "album_artwork", None),
        "artist_artwork": getattr(artist, "artist_artwork", None),
        "year": getattr(track, "year_released", None),

    }

    if extra_context:
        base_context.update(extra_context)

    update_phase(
        phase,
        track_name=track.track_name,
        artist_name=artist.artist_name,
        current_rank=int(rank),
        context=base_context,
    )

    logger.info("🎙 Published %s frame: %s", phase.upper(), audio_url)

    # Same behavior as collections:
    # - "before": backend waits until frontend signals narration finished
    # - "over": do not wait (narration overlaps track)
    if voice_style == "before":
        narration_done_event.clear()
        await narration_done_event.wait()

async def publish_narration_queue_phase(
        phase: Literal["set_intro", "liner", "intro", "detail", "artist"],
        *,
        track,
        artist,
        rank: int,
        decade: str,
        genre: str,
        audio_queue: list[dict],
        texts: dict | None,
        voice_style: Literal["before", "over"],
        extra_context: dict | None = None,
):
    """
    Publishes one narration phase with multiple language audio URLs.
    Frontend plays audio_queue in order, then sends narration-finished once.
    """

    logger.info(
        "🎙 publish_narration_queue_phase phase=%s decade=%s genre=%s items=%d",
        phase,
        decade,
        genre,
        len(audio_queue),
    )

    base_context = {
        "lang": audio_queue[0].get("language") if audio_queue else getattr(status, "language", None),
        "languages": [item.get("language") for item in audio_queue],
        "mode": "decade_genre",
        "decade": decade,
        "genre": genre,
        "rank": int(rank),
        "track_name": track.track_name,
        "artist_name": artist.artist_name,

        # backward compatibility: first audio URL
        "audio_url": audio_queue[0].get("url") if audio_queue else None,

        # new multi-language payload
        "audio_queue": audio_queue,
        "texts": texts or {},

        "source": "remote" if is_remote_audio() else "local",
        "voice_style": voice_style,

        "spotify_track_id": getattr(track, "spotify_track_id", None),
        "album_artwork": getattr(track, "album_artwork", None),
        "artist_artwork": getattr(artist, "artist_artwork", None),
        "year": getattr(track, "year_released", None),
    }

    if extra_context:
        base_context.update(extra_context)

    update_phase(
        phase,
        track_name=track.track_name,
        artist_name=artist.artist_name,
        current_rank=int(rank),
        context=base_context,
    )

    logger.info("🎙 Published %s queue frame: %d item(s)", phase.upper(), len(audio_queue))

    if voice_style == "before":
        narration_done_event.clear()
        await narration_done_event.wait()


# ─────────────────────────────────────────────
# PAUSE / CANCEL HELPERS
# ─────────────────────────────────────────────
async def _wait_if_paused() -> None:
    """Cooperative pause loop driven by playback_state.status."""
    while getattr(status, "is_paused", False):
        await asyncio.sleep(0.25)


def _is_cancelled_or_stopped() -> bool:
    """
    Unified cancel / stop check.

    NOTE:
    We must check BOTH playback_state (new)
    and playback_flags (legacy) because runtime helpers
    still rely on flags during Option A.
    """
    if getattr(status, "stopped", False):
        return True
    if getattr(status, "cancel_requested", False):
        return True

    if getattr(flags, "stopped", False):
        return True
    if getattr(flags, "cancel_requested", False):
        return True

    return False


# ─────────────────────────────────────────────
# MAIN SEQUENCE ENGINE (DECADE / GENRE)
# Publisher-style (like collections):
# Publishes intro/detail/artist/track frames for ONE rank, then returns.
# Frontend controls actual playback and Next/Prev navigation.
# ─────────────────────────────────────────────
async def run_decade_genre_sequence(
        *,
        decade: str,
        genre: str,
        start_rank: int,
        end_rank: int,
        mode: Literal["count_up", "count_down", "random"],
        tts_language: str,
        tts_languages: list[str] | None = None,
        play_intro: bool,
        play_detail: bool,
        play_artist_description: bool,
        play_track: bool,
        voice_style: Literal["before", "over"] = "before",
) -> None:
    logger.info(
        "🎧 Starting sequence (publisher): %s/%s %d-%d mode=%s lang=%s voice=%s",
        decade,
        genre,
        start_rank,
        end_rank,
        mode,
        tts_language,
        voice_style,
    )

    # ─────────── RESET PLAYBACK STATE ───────────
    status.stopped = False
    status.cancel_requested = False
    status.language = tts_language

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

    logger.info("🌎 DG SINGLE LANGUAGES: %s", langs)

    # 🔥 HARD RESET PHASE STATE
    status.phase = None
    status.bed_playing = False

    # 🔁 TEMP: Reset legacy flags (critical)
    flags.is_playing = True
    flags.stopped = False
    flags.cancel_requested = False
    flags.current_rank = start_rank
    flags.mode = "decade_genre"

    mark_playing(
        mode="decade_genre",
        language=tts_language,
        context={
            "decade": decade,
            "genre": genre,
            "start_rank": start_rank,
            "end_rank": end_rank,
            "order": mode,
        },
    )

    update_phase(
        "loading",
        current_rank=start_rank,
        track_name="",
        artist_name="",
        context={
            "lang": tts_language,
            "mode": "decade_genre",
            "decade": decade,
            "genre": genre,
        },
    )

    try:
        # ─────────── LOAD TRACK ROWS ───────────
        logger.info(
            "🧨 Loading rows decade=%r genre=%r start=%d end=%d",
            decade,
            genre,
            start_rank,
            end_rank,
        )

        t0 = time.time()
        try:
            rows = await asyncio.wait_for(
                asyncio.to_thread(
                    load_decade_genre_rows,
                    decade=decade,
                    genre=genre,
                    start_rank=start_rank,
                    end_rank=end_rank,
                ),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.error("⏱️ load_decade_genre_rows timeout (>30s)")
            return

        logger.info("📦 Loaded %d rows in %.2fs", len(rows), time.time() - t0)

        if not rows:
            logger.error("❌ NO TRACK ROWS — decade=%s genre=%s", decade, genre)
            return

        if _is_cancelled_or_stopped():
            logger.info("🛑 Cancelled/stopped before publish")
            return

        await _wait_if_paused()

        # Order rows in the same way the old engine did
        rows = order_rows_for_mode(rows, mode)

        # Pick ONE row to publish (publisher behavior)
        # - count_up: first row in ordered list
        # - count_down: first row after ordering (ordering already reversed)
        # - random: shuffle already handled by order_rows_for_mode; if not, do it here
        if mode == "random":
            random.shuffle(rows)

        track, artist, tr_rank, decade_obj, genre_obj = rows[0]
        rank = int(tr_rank.ranking)
        flags.current_rank = rank

        status.current_rank = rank  # ⭐ ADD
        status.current_ranking_id = tr_rank.id  # ⭐ ADD

        logger.info(f"📻 Playing rank {rank}")

        logger.info("▶ Publish Rank #%02d: %s — %s", rank, track.track_name, artist.artist_name)

        update_phase(
            "prelude",
            is_playing=True,
            current_rank=rank,
            track_name=track.track_name,
            artist_name=artist.artist_name,
            context={
                "lang": tts_language,
                "mode": "decade_genre",
                "rank": rank,
                "track_name": track.track_name,
                "artist_name": artist.artist_name,
                "decade": decade,
                "genre": genre,
                "voice_style": voice_style,
            },
        )

        # ─────────── NARRATION JOBS ───────────
        intro_jobs_by_lang = {}
        detail_by_lang = {}
        artist_by_lang = {}

        for narration_lang in langs:
            log_header_and_texts(
                lang=narration_lang,
                track=track,
                artist=artist,
                tr_rows=[(tr_rank, decade_obj.decade_name, genre_obj.genre_name)],
            )

            intro_jobs_by_lang[narration_lang] = build_intro_jobs(
                lang=narration_lang,
                tr_rows=[(tr_rank, decade_obj.slug, genre_obj.slug)],
            )

            dbucket, dkey, abucket, akey = narration_keys_for(
                lang=narration_lang,
                track=track,
                artist=artist,
            )

            detail_by_lang[narration_lang] = (dbucket, dkey)
            artist_by_lang[narration_lang] = (abucket, akey)

        selected_phases = []

        if play_intro:
            for narration_lang in langs:
                if intro_jobs_by_lang.get(narration_lang):
                    selected_phases.append("intro")
                    break

        if play_detail:
            for narration_lang in langs:
                dbucket, dkey = detail_by_lang.get(narration_lang, (None, None))
                if dbucket and dkey:
                    selected_phases.append("detail")
                    break

        if play_artist_description:
            for narration_lang in langs:
                abucket, akey = artist_by_lang.get(narration_lang, (None, None))
                if abucket and akey:
                    selected_phases.append("artist")
                    break

        status.last_narration_phase = selected_phases[-1] if selected_phases else None

        bed_key = get_genre_bed_key(genre)
        bed_audio_url = resolve_audio_ref(BED_BUCKET, bed_key)

        logger.info("🎧 Selected bed track: %s/%s", BED_BUCKET, bed_key)

        logger.debug("🎯 Last narration phase set to: %s", status.last_narration_phase)

        # ───────── INTRO ─────────
        if play_intro:
            intro_audio_queue = []

            for narration_lang in langs:
                intro_jobs = intro_jobs_by_lang.get(narration_lang, [])
                if not intro_jobs:
                    continue

                ib, ik = _extract_bucket_key(intro_jobs[0])
                if not ib or not ik:
                    continue

                intro_audio_queue.append({
                    "language": narration_lang,
                    "bucket": ib,
                    "key": ik,
                    "url": resolve_audio_ref(ib, ik),
                })

            if intro_audio_queue:
                await publish_narration_queue_phase(
                    "intro",
                    track=track,
                    artist=artist,
                    rank=rank,
                    decade=decade_obj.decade_name,
                    genre=genre,
                    audio_queue=intro_audio_queue,
                    texts={},
                    voice_style=voice_style,
                    extra_context={
                        "bed_bucket": BED_BUCKET,
                        "bed_key": bed_key,
                        "bed_audio_url": bed_audio_url,
                    }
                )

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
                await publish_narration_queue_phase(
                    "detail",
                    track=track,
                    artist=artist,
                    rank=rank,
                    decade=decade_obj.decade_name,
                    genre=genre,
                    audio_queue=detail_audio_queue,
                    texts={},
                    voice_style=voice_style,
                    extra_context={
                        "bed_bucket": BED_BUCKET,
                        "bed_key": bed_key,
                        "bed_audio_url": bed_audio_url,
                    }
                )

        # ───────── ARTIST ─────────
        if play_artist_description:
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
                    decade=decade_obj.decade_name,
                    genre=genre,
                    audio_queue=artist_audio_queue,
                    texts={},
                    voice_style=voice_style,
                    extra_context={
                        "bed_bucket": BED_BUCKET,
                        "bed_key": bed_key,
                        "bed_audio_url": bed_audio_url,
                    }
                )

        logger.info(
            "🔍 DEBUG spotify id for rank %s → %s",
            rank,
            track.spotify_track_id
        )

        # ───────── TRACK (publish spotify id) ─────────
        if play_track and track.spotify_track_id:
            update_phase(
                "track",
                track_name=track.track_name,
                artist_name=artist.artist_name,
                current_rank=rank,
                context={
                    "mode": "spotify",
                    "decade": decade,
                    "genre": genre,
                    "spotify_track_id": track.spotify_track_id,
                    "ranking_id": tr_rank.id,  # ⭐ ADD THIS
                },
            )

            logger.info("🎯 PUBLISHED track frame rank=%s spotify=%s", rank, track.spotify_track_id)

        logger.info("✅ Decade/genre publish finished (single-rank).")

    except asyncio.CancelledError:
        logger.info("⛔ Sequence task cancelled")
        raise
    except Exception:
        logger.exception("⚠️ Sequence error for %s/%s", decade, genre)
    finally:
        # reset legacy flags (keep your existing behavior)
        flags.is_playing = False
        flags.stopped = True
        logger.debug("🧹 Playback flags reset for %s/%s", decade, genre)


async def run_decade_genre_continuous_sequence(
        *,
        decade: str,
        genre: str,
        start_rank: int,
        end_rank: int,
        mode: Literal["count_up", "count_down", "random"],
        tts_language: str,
        tts_languages: list[str] | None = None,
        play_intro: bool,
        play_detail: bool,
        play_artist_description: bool,
        play_track: bool,
        voice_style: Literal["before", "over"] = "before",
) -> None:
    logger.info(
        "📻 CONTINUOUS MODE START: %s/%s %d-%d mode=%s lang=%s voice=%s",
        decade, genre, start_rank, end_rank, mode, tts_language, voice_style
    )

    # ─────────── RESET PLAYBACK STATE ───────────
    status.stopped = False
    status.cancel_requested = False
    status.language = tts_language

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

    logger.info("🌎 DG CONTINUOUS LANGUAGES: %s", langs)
    status.phase = None
    status.bed_playing = False

    flags.is_playing = True
    flags.stopped = False
    flags.cancel_requested = False
    flags.current_rank = start_rank
    flags.mode = "decade_genre"

    mark_playing(
        mode="decade_genre",
        language=tts_language,
        context={
            "decade": decade,
            "genre": genre,
            "start_rank": start_rank,
            "end_rank": end_rank,
            "order": mode,
        },
    )

    update_phase(
        "loading",
        current_rank=start_rank,
        track_name="",
        artist_name="",
        context={
            "lang": tts_language,
            "mode": "decade_genre",
            "decade": decade,
            "genre": genre,
        },
    )

    try:
        # ─────────── LOAD ROWS ONCE ───────────
        logger.debug("🧨 Loading decade/genre rows for continuous mode")

        rows = await asyncio.wait_for(
            asyncio.to_thread(
                load_decade_genre_rows,
                decade=decade,
                genre=genre,
                start_rank=start_rank,
                end_rank=end_rank,
            ),
            timeout=30.0,
        )

        if not rows:
            logger.error("❌ NO TRACK ROWS — decade=%s genre=%s", decade, genre)
            return

        # Order rows
        rows = order_rows_for_mode(rows, mode)
        if mode == "random":
            random.shuffle(rows)

        logger.info("🔥 Sequence START (continuous) rows=%d", len(rows))

        # ─────────── MAIN RADIO LOOP ───────────
        for (track, artist, tr_rank, decade_obj, genre_obj) in rows:
            if _is_cancelled_or_stopped():
                logger.info("🛑 Cancelled/stopped — exiting continuous loop")
                return

            await _wait_if_paused()

            rank = int(tr_rank.ranking)
            flags.current_rank = rank

            status.current_rank = rank  # ⭐ ADD
            status.current_ranking_id = tr_rank.id  # ⭐ ADD

            logger.info("▶ Publish Rank #%02d: %s — %s",
                        rank, track.track_name, artist.artist_name)

            update_phase(
                "prelude",
                is_playing=True,
                current_rank=rank,
                track_name=track.track_name,
                artist_name=artist.artist_name,
                context={
                    "lang": tts_language,
                    "mode": "decade_genre",
                    "rank": rank,
                    "track_name": track.track_name,
                    "artist_name": artist.artist_name,
                    "decade": decade,
                    "genre": genre,
                    "voice_style": voice_style,
                },
            )

            # ─────────── NARRATION JOBS ───────────
            intro_jobs_by_lang = {}
            detail_by_lang = {}
            artist_by_lang = {}

            for narration_lang in langs:

                intro_jobs_by_lang[narration_lang] = build_intro_jobs(
                    lang=narration_lang,
                    tr_rows=[(tr_rank, decade_obj.decade_name, genre_obj.genre_name)],
                )

                dbucket, dkey, abucket, akey = narration_keys_for(
                    lang=narration_lang,
                    track=track,
                    artist=artist,
                )

                detail_by_lang[narration_lang] = (dbucket, dkey)
                artist_by_lang[narration_lang] = (abucket, akey)

            selected_phases = []

            if play_intro:
                for narration_lang in langs:
                    if intro_jobs_by_lang.get(narration_lang):
                        selected_phases.append("intro")
                        break

            if play_detail:
                for narration_lang in langs:
                    dbucket, dkey = detail_by_lang.get(narration_lang, (None, None))
                    if dbucket and dkey:
                        selected_phases.append("detail")
                        break

            if play_artist_description:
                for narration_lang in langs:
                    abucket, akey = artist_by_lang.get(narration_lang, (None, None))
                    if abucket and akey:
                        selected_phases.append("artist")
                        break

            status.last_narration_phase = selected_phases[-1] if selected_phases else None

            bed_key = get_genre_bed_key(genre)
            bed_audio_url = resolve_audio_ref(BED_BUCKET, bed_key)

            logger.info("🎧 Selected bed track: %s/%s", BED_BUCKET, bed_key)

            logger.debug("🎯 Last narration phase set to: %s", status.last_narration_phase)

            # ───────── INTRO ─────────
            if play_intro:
                intro_audio_queue = []

                for narration_lang in langs:
                    intro_jobs = intro_jobs_by_lang.get(narration_lang, [])
                    if not intro_jobs:
                        continue

                    ib, ik = _extract_bucket_key(intro_jobs[0])
                    if not ib or not ik:
                        continue

                    intro_audio_queue.append({
                        "language": narration_lang,
                        "bucket": ib,
                        "key": ik,
                        "url": resolve_audio_ref(ib, ik),
                    })

                if intro_audio_queue:
                    await publish_narration_queue_phase(
                        "intro",
                        track=track,
                        artist=artist,
                        rank=rank,
                        decade=decade_obj.decade_name,
                        genre=genre,
                        audio_queue=intro_audio_queue,
                        texts={},
                        voice_style=voice_style,
                        extra_context={
                            "bed_bucket": BED_BUCKET,
                            "bed_key": bed_key,
                            "bed_audio_url": bed_audio_url,
                        }
                    )

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
                    await publish_narration_queue_phase(
                        "detail",
                        track=track,
                        artist=artist,
                        rank=rank,
                        decade=decade_obj.decade_name,
                        genre=genre,
                        audio_queue=detail_audio_queue,
                        texts={},
                        voice_style=voice_style,
                        extra_context={
                            "bed_bucket": BED_BUCKET,
                            "bed_key": bed_key,
                            "bed_audio_url": bed_audio_url,
                        }
                    )

            # ───────── ARTIST ─────────
            if play_artist_description:
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
                        decade=decade_obj.decade_name,
                        genre=genre,
                        audio_queue=artist_audio_queue,
                        texts={},
                        voice_style=voice_style,
                        extra_context={
                            "bed_bucket": BED_BUCKET,
                            "bed_key": bed_key,
                            "bed_audio_url": bed_audio_url,
                        }
                    )

            # ───────── TRACK ─────────
            if play_track and track.spotify_track_id:
                track_done_event.clear()

                update_phase(
                    "track",
                    track_name=track.track_name,
                    artist_name=artist.artist_name,
                    current_rank=rank,
                    context={
                        "mode": "spotify",
                        "decade": decade,
                        "genre": genre,
                        "spotify_track_id": track.spotify_track_id,
                        "ranking_id": tr_rank.id,  # ⭐ ADD THIS
                    },
                )

                logger.info("🎯 PUBLISHED track frame rank=%s spotify=%s",
                            rank, track.spotify_track_id)

                # 🔥 This is the radio heartbeat:
                # Wait until frontend says Spotify finished
                await track_done_event.wait()

        logger.info("🏁 Sequence COMPLETE (continuous)")

    except asyncio.TimeoutError:
        logger.error("⏱️ load_decade_genre_rows timeout (>30s)")
    except asyncio.CancelledError:
        logger.info("⛔ Continuous sequence task cancelled")
        raise
    except Exception:
        logger.exception("⚠️ Continuous sequence error for %s/%s", decade, genre)
    finally:
        flags.is_playing = False
        flags.stopped = True
        logger.debug("🧹 Playback flags reset for %s/%s", decade, genre)
