# backend/services/radio_runtime.py
from __future__ import annotations

import asyncio
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)   # ✅ DEFINE LOGGER FIRST

from sqlmodel import Session as SQLSession

from backend.database import engine
from backend.services.localization import get_localized_texts
from backend.services.playback_helpers import (
    bucket_for,
    key_for,
    build_intro_filename,
    build_collection_intro_filename,
    build_detail_filename,
    build_artist_filename,
)

from backend.services.radio_render import clean_text
from backend.state.skip import skip_event
from backend.state.playback_runtime import bind_task, current_runtime, current_user_id

_CATALOG_63_INTRO_SLUG = "1950s-tv_themes"


def start_playback_sequence(coro) -> None:
    """
    Register the main playback coroutine so skip_to_next / skip_to_prev can cancel it.
    """
    runtime = current_runtime()

    # Cancel any previous running sequence
    if runtime.current_task and not runtime.current_task.done():
        logger.info("🔁 Cancelling old playback task")
        runtime.current_task.cancel()

    runtime.current_task = asyncio.create_task(coro)
    bind_task(runtime.current_task, current_user_id())
    logger.info("▶️ Playback sequence started")
from backend.state.playback_flags import flags


async def _respect_user_controls() -> None:
    """
    Central cooperative checkpoint for pause / stop.
    IMPORTANT: Do NOT abort if a new playback session is actively running.
    """
    status = current_runtime().status
    while status.is_paused:
        await asyncio.sleep(0.25)

    # Only stop if no active playback is intended
    if status.stopped and not flags.is_playing:
        logger.info("🛑 Playback stopped by user.")
        raise asyncio.CancelledError("Playback stopped")


def _phase_context(
    *,
    lang: str | None = None,
    mode: str | None = None,
    rank: Optional[int] = None,
    track_name: Optional[str] = None,
    artist_name: Optional[str] = None,
    elapsed_seconds: Optional[float] = None,
    duration_seconds: Optional[float] = None,
) -> dict:
    ctx: dict = {}
    if lang is not None:
        ctx["lang"] = lang
    if mode is not None:
        ctx["mode"] = mode
    if rank is not None:
        ctx["rank"] = rank
    if track_name is not None:
        ctx["track_name"] = track_name
    if artist_name is not None:
        ctx["artist_name"] = artist_name
    if elapsed_seconds is not None:
        ctx["elapsed_seconds"] = float(elapsed_seconds)
    if duration_seconds is not None:
        ctx["duration_seconds"] = float(duration_seconds)
    return ctx


# ─────────────────────────────────────────────
# Collection logging helpers
# ─────────────────────────────────────────────
def _narration_text_diagnostic(value: object) -> tuple[bool, int]:
    """Return logging-safe narration metadata without coercing arbitrary values."""
    if type(value) is str:
        return bool(value), len(value)
    return False, 0


def _log_narration_text_diagnostics(*, phase: str, intro: object, detail: object, artist: object) -> None:
    """Log bounded narration diagnostics only; narration bodies stay out of logs."""
    has_intro, intro_chars = _narration_text_diagnostic(intro)
    has_detail, detail_chars = _narration_text_diagnostic(detail)
    has_artist, artist_chars = _narration_text_diagnostic(artist)
    logger.info(
        "narration_texts phase=%s has_intro=%s intro_chars=%d has_detail=%s detail_chars=%d has_artist=%s artist_chars=%d",
        phase,
        has_intro,
        intro_chars,
        has_detail,
        detail_chars,
        has_artist,
        artist_chars,
    )


def log_collection_header_and_texts(
    *,
    collection,
    ctr,
    track,
    artist,
    intro: str | None = None,
    detail_text: str | None = None,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    intro_text = clean_text(intro or getattr(ctr, "intro", None))
    detail_text2 = clean_text(detail_text or getattr(track, "detail", None))
    artist_text = clean_text(getattr(artist, "artist_description", None))
    _log_narration_text_diagnostics(
        phase="collection",
        intro=intro_text,
        detail=detail_text2,
        artist=artist_text,
    )

    return intro_text, detail_text2, artist_text


def collection_intro_jobs(*, lang: str, collection_slug: str, rank: int):
    # allow all languages
    pass

    bucket = bucket_for(lang, "collections_intro")
    filename = build_collection_intro_filename(collection_slug, rank)
    key = key_for("collections_intro", filename)

    if not (bucket and key):
        return []

    return [(bucket, key, collection_slug, collection_slug, rank)]


# ─────────────────────────────────────────────
# Decade/Genre header logging
# ─────────────────────────────────────────────
def log_header_and_texts(
    *,
    lang: str,
    track,
    artist,
    tr_rows,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    intro_text_loc: str | None = None
    detail_text_loc: str | None = None

    if tr_rows:
        first_rk = tr_rows[0][0]
        with SQLSession(engine) as s_loc:
            intro_text_loc, detail_text_loc = get_localized_texts(
                s_loc, lang, first_rk, track
            )

    detail_text = (
        clean_text(detail_text_loc)
        if detail_text_loc
        else clean_text(getattr(track, "detail", None))
    )
    artist_text = clean_text(getattr(artist, "artist_description", None))
    _log_narration_text_diagnostics(
        phase="decade_genre",
        intro=intro_text_loc,
        detail=detail_text,
        artist=artist_text,
    )

    return intro_text_loc, detail_text, artist_text


# ─────────────────────────────────────────────
# Narration asset builders
# ─────────────────────────────────────────────
def _locale_narration_keys(*, lang: str, ranking_id: int | None = None, track_id: int | None = None) -> tuple[Optional[str], Optional[str]]:
    """Return an explicitly mapped localized narration asset, when one exists."""
    if lang == "en":
        return None, None

    from sqlmodel import select
    from backend.models.dbmodels import TrackLocale, TrackRankingLocale

    with SQLSession(engine) as session:
        if ranking_id is not None:
            locale = session.exec(
                select(TrackRankingLocale).where(
                    TrackRankingLocale.track_ranking_id == ranking_id,
                    TrackRankingLocale.language_code == lang,
                )
            ).first()
        elif track_id is not None:
            locale = session.exec(
                select(TrackLocale).where(
                    TrackLocale.track_id == track_id,
                    TrackLocale.language_code == lang,
                )
            ).first()
        else:
            return None, None

    return getattr(locale, "tts_bucket", None), getattr(locale, "tts_key", None)


def build_intro_jobs(*, lang: str, tr_rows, mapped_bucket: str | None = None, mapped_key: str | None = None) -> List[Tuple[str, str, str, str, int]]:
    jobs: List[Tuple[str, str, str, str, int]] = []
    if not tr_rows:
        return jobs

    for tr, decade_name, genre_name in tr_rows:
        bucket, key = mapped_bucket, mapped_key
        if not (bucket and key):
            bucket, key = (
                _locale_narration_keys(lang=lang, ranking_id=getattr(tr, "id", None))
                if getattr(tr, "decade_genre_id", None) == 63
                else (None, None)
            )
        if not (bucket and key):
            intro_filename = (
                f"{_CATALOG_63_INTRO_SLUG}_{tr.ranking:02d}.mp3"
                if getattr(tr, "decade_genre_id", None) == 63
                else build_intro_filename(decade_name, genre_name, tr.ranking)
            )
            bucket = bucket_for(lang, "intro")
            key = key_for("intro", intro_filename)
        if bucket and key:
            jobs.append((bucket, key, decade_name, genre_name, tr.ranking))

    return jobs


def narration_keys_for(*, lang: str, track, artist, decade_genre_id: int | None = None, mapped_detail_bucket: str | None = None, mapped_detail_key: str | None = None):
    # Catalog 63's replacement is intentionally isolated: Track rows can be
    # shared by other catalogs, whose historical naming convention remains intact.
    detail_bucket, detail_key = mapped_detail_bucket, mapped_detail_key
    if not (detail_bucket and detail_key):
        detail_bucket, detail_key = (
            _locale_narration_keys(lang=lang, track_id=getattr(track, "id", None))
            if decade_genre_id == 63
            else (None, None)
        )
    detail_filename = build_detail_filename(track.spotify_track_id)
    artist_filename = build_artist_filename(artist.spotify_artist_id)

    if not detail_key:
        detail_key = key_for("detail", detail_filename) if detail_filename else None
    artist_key = key_for("artist", artist_filename) if artist_filename else None

    detail_bucket = detail_bucket or (bucket_for(lang, "detail") if detail_key else None)
    artist_bucket = bucket_for(lang, "artist") if artist_key else None

    return detail_bucket, detail_key, artist_bucket, artist_key


def short_detail_keys_for(*, lang: str, track, decade_genre_id: int | None = None, mapped_short_detail_key: str | None = None):
    """Resolve the short-detail asset using catalog-scoped locale mappings."""
    short_detail_key = mapped_short_detail_key
    if not short_detail_key and decade_genre_id == 63:
        if lang == "en":
            short_detail_key = getattr(track, "short_detail_tts_key", None)
        else:
            from sqlmodel import select
            from backend.models.dbmodels import TrackLocale

            with SQLSession(engine) as session:
                locale = session.exec(
                    select(TrackLocale).where(
                        TrackLocale.track_id == track.id,
                        TrackLocale.language_code == lang,
                    )
                ).first()
            short_detail_key = getattr(locale, "short_detail_tts_key", None)

    filename = build_detail_filename(track.spotify_track_id)
    short_detail_key = short_detail_key or key_for("short_detail", filename)
    return bucket_for(lang, "detail"), short_detail_key

def skip_to_next() -> None:
    """
    Signals the currently running narration/track loop to skip.
    Does NOT start new sequences. The active sequence runner (if any)
    will advance to the next rank on its own.
    """
    logger.info("⏭ skip_to_next requested")
    skip_event.set()


def skip_to_prev() -> None:
    """
    Signals skip. True 'prev' requires the sequence runner to support jumping.
    For now, treat as skip (same behavior as next).
    """
    logger.info("⏮ skip_to_prev requested")
    skip_event.set()
