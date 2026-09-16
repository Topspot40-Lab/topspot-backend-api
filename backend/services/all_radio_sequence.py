from __future__ import annotations

import asyncio
import logging
from backend.models import (
    Decade,
    Genre,
    DecadeGenre,
    TrackRanking,
    TrackLocale,
    ArtistLocale,
    TrackRankingLocale,
)

from sqlmodel import Session, select
from backend.database import engine

from backend.services.decade_genre_sequence import (
    _extract_bucket_key,
    publish_narration_phase,
    publish_narration_queue_phase,
)
from backend.services.radio_runtime import (
    build_intro_jobs,
    narration_keys_for,
    short_detail_keys_for,
)
from backend.config.playback_block_config import MIN_TRACKS_PER_BLOCK
from backend.services.decade_genre_loader import load_decade_genre_rows
from backend.services.block_builder import build_track_block
from backend.state.playback_state import begin_track, mark_playing, update_phase
from backend.state.playback_flags import flags
from backend.state.narration import track_done_event
from backend.state.playback_runtime import current_runtime, current_user_id

from backend.services.bed_tracks import BED_BUCKET, get_genre_bed_key
from backend.services.audio_urls import resolve_audio_ref

logger = logging.getLogger(__name__)


def detail_audio_keys_for_radio(*, detail_length: str, lang: str, track, decade_genre_id: int | None, artist):
    """Use the same short/full narration asset resolvers as normal playback."""
    if detail_length == "short":
        return short_detail_keys_for(
            lang=lang,
            track=track,
            decade_genre_id=decade_genre_id,
        )
    detail_bucket, detail_key, _, _ = narration_keys_for(
        lang=lang,
        track=track,
        artist=artist,
        decade_genre_id=decade_genre_id,
    )
    return detail_bucket, detail_key


def radio_artist_identity(artist) -> str:
    """Match the established primary-artist-once-per-session behavior."""
    spotify_artist_id = getattr(artist, "spotify_artist_id", None)
    if spotify_artist_id:
        return f"spotify:{spotify_artist_id}"
    artist_id = getattr(artist, "id", None)
    if artist_id is not None:
        return f"artist:{artist_id}"
    return f"artist-name:{getattr(artist, 'artist_name', '').strip().lower()}"


def selected_radio_narration_phases(
        *,
        first_track: bool,
        play_intro: bool,
        has_intro: bool,
        play_detail: bool,
        has_detail: bool,
        play_artist: bool,
        has_artist: bool,
) -> list[str]:
    """The authoritative phase order, shared by every radio track and set."""
    phases: list[str] = ["set_intro"] if first_track else []
    if play_intro and has_intro:
        phases.append("intro")
    if play_detail and has_detail:
        phases.append("detail")
    if play_artist and has_artist:
        phases.append("artist")
    return phases

def resolve_radio_narration_policy(
        status,
        *,
        default_play_detail: bool,
        default_detail_length: str,
) -> tuple[bool, bool, str, bool]:
    """Snapshot the current radio narration policy for one complete set."""
    selection = getattr(status, "selection", {}) or {}
    voices = selection.get("voices", [])

    play_intro = "intro" in voices
    detail_length = selection.get("detail_length", default_detail_length)
    if detail_length not in {"off", "short", "long"}:
        detail_length = "long" if default_play_detail else "off"

    return (
        play_intro,
        "detail" in voices and detail_length != "off",
        detail_length,
        "artist" in voices,
    )


VALID_BUCKETS_CACHE = None

import random

LINER_FILES = [f"liner_{i:02}.mp3" for i in range(1, 31)]


def get_random_station_liner(lang: str = "en"):
    filename = random.choice(LINER_FILES)

    lang = (lang or "en").lower().replace("-", "")

    if lang in ("ptbr", "pt_br", "pt-br", "pt"):
        bucket = "audio-ptbr"
    elif lang == "es":
        bucket = "audio-es"
    else:
        bucket = "audio-en"

    key = f"station-liner/{filename}"

    return bucket, key

import os

def get_liner_probability() -> float:
    try:
        return float(os.getenv("LINER_PROBABILITY", "0.35"))
    except ValueError:
        return 0.35


def get_valid_buckets(session):
    q = (
        select(Decade.slug, Genre.slug)
        .join(DecadeGenre, DecadeGenre.decade_id == Decade.id)
        .join(Genre, Genre.id == DecadeGenre.genre_id)
        .join(TrackRanking, TrackRanking.decade_genre_id == DecadeGenre.id)
        .group_by(Decade.slug, Genre.slug)
    )

    rows = session.exec(q).all()

    return [(d, g) for d, g in rows]


def build_decade_genre_intro_url(decade_slug: str, genre_slug: str) -> str:
    slug = f"{decade_slug}-{genre_slug}"
    return (
        "https://iizlnzmmhkzedqkolgir.supabase.co"
        f"/storage/v1/object/public/audio-en/decade-genre-intro/{slug}.mp3"
    )


def build_set_intro_bucket_key(decade_slug: str, genre_slug: str, lang: str = "en") -> tuple[str, str]:
    bucket_map = {
        "en": "audio-en",
        "es": "audio-es",
        "ptbr": "audio-ptbr",
    }

    bucket = bucket_map.get(lang, "audio-en")
    slug = f"{decade_slug}-{genre_slug}"
    key = f"decade-genre-intro/{slug}.mp3"

    return bucket, key


async def publish_set_intro_phase(
        *,
        tts_languages: list[str],
        decade_slug: str,
        genre_slug: str,
        decade_name: str,
        genre_name: str,
        track,
        artist,
        rank: int,
        radio_context: dict,
) -> None:

    set_intro_audio_queue = []

    for lang in tts_languages:

        normalized_lang = "ptbr" if lang in ("pt-BR", "ptbr") else lang

        bucket, key = build_set_intro_bucket_key(
            decade_slug,
            genre_slug,
            normalized_lang,
        )

        logger.info("set_intro_audio_prepared source=all_radio")

        set_intro_audio_queue.append({
            "language": normalized_lang,
            "bucket": bucket,
            "key": key,
            "url": resolve_audio_ref(bucket, key),
        })

    if set_intro_audio_queue:
        await publish_narration_queue_phase(
            "set_intro",
            track=track,
            artist=artist,
            rank=rank,
            decade=decade_name,
            genre=genre_name,
            audio_queue=set_intro_audio_queue,
            texts={},
            voice_style="before",
            extra_context={
                **radio_context,
                "set_intro": True,
                "set_intro_slug": f"{decade_slug}-{genre_slug}",
            },
        )


async def run_all_radio_sequence(
        *,
        tts_language: str = "en",
        tts_languages: list[str] | None = None,
        category: str | None = None,
        genre_filter: str | None = None,
        play_intro: bool = True,
        play_detail: bool = True,
        detail_length: str = "long",
        play_artist_description: bool = False,
        voice_style: str = "before",   # ✅ ADD THIS
):
    user_id = current_user_id()
    status = current_runtime().status

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

    # remove duplicates, preserve order
    langs = list(dict.fromkeys(langs))

    # current single-language compatibility
    lang = langs[0] if langs else "en"

    logger.info("🌎 RADIO LANGUAGES: %s", langs)

    play_intro, play_detail, detail_length, play_artist = resolve_radio_narration_policy(
        status,
        default_play_detail=play_detail,
        default_detail_length=detail_length,
    )

    """
    ALL / ALL radio mode.

    Chooses a random decade+genre bucket, builds
    an ~8-12 minute block, plays it, then repeats.
    """

    logger.info("📻 ALL-ALL RADIO MODE START")
    played_artist_ids: set[str] = set()

    status.stopped = False
    status.cancel_requested = False
    status.language = lang

    flags.is_playing = True
    flags.stopped = False
    flags.cancel_requested = False
    flags.mode = "all_radio"

    mark_playing(
        user_id=user_id,
        mode="all_radio",
        language=lang,
        context={
            "mode": "all_radio",
            "category": category,

        }
    )

    global VALID_BUCKETS_CACHE

    previous_bucket = None
    last_played_ranking_id = None
    set_number = 0

    recent_decades = []
    MAX_RECENT_DECADES = 3

    recent_artists = []
    MAX_RECENT_ARTISTS = 5

    try:

        while True:
            # Snapshot the latest selection only at the set boundary. Changes
            # made during a set are intentionally deferred until the next set.
            play_intro, play_detail, detail_length, play_artist = resolve_radio_narration_policy(
                status,
                default_play_detail=play_detail,
                default_detail_length=detail_length,
            )
            logger.debug(
                "🎛️ RADIO SET POLICY | intro=%s detail=%s detail_length=%s artist=%s",
                play_intro,
                play_detail,
                detail_length,
                play_artist,
            )

            # ─────────────────────────────
            # BUILD VALID BUCKET LIST
            # ─────────────────────────────
            if VALID_BUCKETS_CACHE is None:
                from backend.database import get_db_session

                with get_db_session() as session:
                    VALID_BUCKETS_CACHE = get_valid_buckets(session)

                if not VALID_BUCKETS_CACHE:
                    logger.error("❌ No valid radio buckets found")
                    return

            # ALWAYS assign first
            valid_buckets = VALID_BUCKETS_CACHE

            # 🎯 Apply genre filter (once, clean)
            if genre_filter and genre_filter != "ALL":
                logger.info("🎸 GENRE FILTER ACTIVE: %s", genre_filter)
                valid_buckets = [(d, g) for (d, g) in valid_buckets if g == genre_filter]

            # 🕒 Build station clock from filtered buckets
            genres = list({g for _, g in valid_buckets})
            random.shuffle(genres)

            logger.debug("🕒 Station clock genres: %s", genres)

            clock_index = 0

            valid_buckets = VALID_BUCKETS_CACHE
            # 🎯 Apply genre filter
            if genre_filter and genre_filter != "ALL":
                valid_buckets = [(d, g) for (d, g) in valid_buckets if g == genre_filter]

            # 🎯 Apply genre filter (for Nostalgia Radio station selection)
            if genre_filter and genre_filter != "ALL":
                valid_buckets = [(d, g) for (d, g) in valid_buckets if g == genre_filter]

            # ─────────────────────────────
            # PICK RANDOM BUCKET
            # ─────────────────────────────
            # avoid repeating recent decades
            filtered = [
                (d, g) for (d, g) in valid_buckets
                if d not in recent_decades
            ]

            if not filtered:
                filtered = valid_buckets

            if genres:
                target_genre = genres[clock_index]

                candidates = [(d, g) for (d, g) in filtered if g == target_genre]
            else:
                candidates = filtered

            if not candidates:
                candidates = filtered

            decade, genre = random.choice(candidates)

            while (decade, genre) == previous_bucket:
                decade, genre = random.choice(valid_buckets)

            previous_bucket = (decade, genre)
            set_number += 1

            recent_decades.append(decade)

            if len(recent_decades) > MAX_RECENT_DECADES:
                recent_decades.pop(0)

            logger.info("🎲 Bucket chosen: %s / %s", decade, genre)

            update_phase(
                user_id,
                "loading",
                track_name="",
                artist_name="",
                context={
                    "mode": "all_radio",
                    "decade": decade,
                    "genre": genre,
                    "set_number": set_number,
                },
            )

            # ─────────────────────────────
            # LOAD ROWS
            # ─────────────────────────────
            rows = await asyncio.to_thread(
                load_decade_genre_rows,
                decade=decade,
                genre=genre,
                start_rank=1,
                end_rank=40,
            )

            if not rows:
                logger.warning("No rows for %s/%s", decade, genre)
                continue

            # ─────────────────────────────
            # BUILD BLOCK
            # ─────────────────────────────
            block_rows = build_track_block(rows)

            # avoid repeating recent artists
            filtered_block = [
                row for row in block_rows
                if row[1].artist_name not in recent_artists
            ]

            # Only apply filter if it doesn't shrink too much
            if len(filtered_block) >= MIN_TRACKS_PER_BLOCK:
                block_rows = filtered_block

            # SINGLE MODE → only keep one track
            if category == "single" and flags.mode != "all_radio":
                block_rows = block_rows[:1]

            total_ms = sum(row[0].duration_ms for row in block_rows if row[0].duration_ms)

            logger.info(
                "🎼 SET %d | %s / %s | %d tracks | %.1f min",
                set_number,
                decade,
                genre,
                len(block_rows),
                total_ms / 60000,
            )

            # ─────────────────────────────
            # PLAY BLOCK
            # ─────────────────────────────
            set_bed_key = get_genre_bed_key(genre)
            set_bed_audio_url = resolve_audio_ref(BED_BUCKET, set_bed_key)

            logger.info("bed_track_selected source=all_radio")
            for idx, (track, artist, tr_rank, decade_obj, genre_obj) in enumerate(block_rows, start=1):

                if status.stopped:
                    logger.info("🛑 Radio mode stopped")
                    return

                rank = tr_rank.ranking

                flags.current_rank = rank
                status.current_rank = rank
                status.current_ranking_id = tr_rank.id

                logger.info(
                    "🎵 TRACK %d/%d | %s — %s",
                    idx,
                    len(block_rows),
                    track.track_name,
                    artist.artist_name
                )

                recent_artists.append(artist.artist_name)
                if len(recent_artists) > MAX_RECENT_ARTISTS:
                    recent_artists.pop(0)

                # Ignore duplicate finish handling
                if tr_rank.id == last_played_ranking_id:
                    continue

                last_played_ranking_id = tr_rank.id

                logger.info(
                    "📻 RADIO starting narrated pipeline rank=%s intro=%s detail=%s artist=%s",
                    rank,
                    play_intro,
                    play_detail,
                    play_artist,
                )

                # Optional prelude, same idea as DG mode
                update_phase(
                    user_id,
                    "prelude",
                    is_playing=True,
                    current_rank=rank,
                    track_name=track.track_name,
                    artist_name=artist.artist_name,
                    context={
                        "lang": lang,
                        "mode": "all_radio",
                        "rank": rank,
                        "track_name": track.track_name,
                        "artist_name": artist.artist_name,
                        "decade": decade,
                        "genre": genre,
                        "voice_style": "before",
                        "set_number": set_number,
                        "block_size": len(block_rows),
                        "block_position": idx,
                        "year": track.year_released,
                        "album_artwork": track.album_artwork,
                        "artist_artwork": artist.artist_artwork,
                        "duration_ms": track.duration_ms,
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
                        decade_genre_id=tr_rank.decade_genre_id,
                    )

                    detail_by_lang[narration_lang] = detail_audio_keys_for_radio(
                        detail_length=detail_length,
                        lang=narration_lang,
                        track=track,
                        artist=artist,
                        decade_genre_id=tr_rank.decade_genre_id,
                    )
                    artist_by_lang[narration_lang] = (abucket, akey)

                artist_identity = radio_artist_identity(artist)
                play_artist_for_track = play_artist and artist_identity not in played_artist_ids

                # 🎯 Determine last narration phase for this track
                selected_phases = selected_radio_narration_phases(
                    first_track=idx == 1,
                    play_intro=play_intro,
                    has_intro=any(intro_jobs_by_lang.values()),
                    play_detail=play_detail,
                    has_detail=any(bucket and key for bucket, key in detail_by_lang.values()),
                    play_artist=play_artist_for_track,
                    has_artist=any(bucket and key for bucket, key in artist_by_lang.values()),
                )

                status.last_narration_phase = selected_phases[-1] if selected_phases else None

                logger.info("🎯 RADIO last narration phase set to: %s", status.last_narration_phase)

                texts_by_language = {}

                with Session(engine) as db:

                    for narration_lang in langs:

                        locale_code = (
                            "pt-BR"
                            if narration_lang in ("ptbr", "pt-BR")
                            else narration_lang
                        )

                        intro_text = getattr(tr_rank, "intro", None)
                        detail_text = (
                            getattr(track, "short_detail", None)
                            if detail_length == "short"
                            else getattr(track, "detail", None)
                        )
                        artist_text = getattr(artist, "artist_description", None)

                        if locale_code != "en":

                            ranking_locale = db.exec(
                                select(TrackRankingLocale).where(
                                    TrackRankingLocale.track_ranking_id == tr_rank.id,
                                    TrackRankingLocale.language_code == locale_code,
                                )
                            ).first()

                            track_locale = db.exec(
                                select(TrackLocale).where(
                                    TrackLocale.track_id == track.id,
                                    TrackLocale.language_code == locale_code,
                                )
                            ).first()

                            artist_locale = db.exec(
                                select(ArtistLocale).where(
                                    ArtistLocale.artist_id == artist.id,
                                    ArtistLocale.language_code == locale_code,
                                )
                            ).first()

                            if ranking_locale and ranking_locale.intro_text:
                                intro_text = ranking_locale.intro_text

                            localized_detail = (
                                getattr(track_locale, "short_detail_text", None)
                                if detail_length == "short"
                                else getattr(track_locale, "detail_text", None)
                            )
                            if localized_detail:
                                detail_text = localized_detail

                            if artist_locale and artist_locale.artist_description_text:
                                artist_text = artist_locale.artist_description_text

                        texts_by_language[narration_lang] = {
                            "intro": intro_text,
                            "detail": detail_text,
                            "artist": artist_text,
                        }

                logger.info(
                    "🌎 RADIO TEXTS BUILT | langs=%s",
                    list(texts_by_language.keys()),
                )


                radio_context = {
                    "mode": "all_radio",
                    "decade_slug": decade,
                    "genre_slug": genre,
                    "decade_name": decade_obj.decade_name,
                    "genre_name": genre_obj.genre_name,
                    "set_number": set_number,
                    "block_size": len(block_rows),
                    "block_position": idx,
                    "ranking_id": tr_rank.id,
                    "year": track.year_released,
                    "album_artwork": track.album_artwork,
                    "artist_artwork": artist.artist_artwork,
                    # build_track_block already requires this authoritative
                    # Spotify duration. Keep it on every radio status frame,
                    # including prelude/set_intro and the final track frame.
                    "duration_ms": track.duration_ms,
                    "detail_length": detail_length,
                    "bed_bucket": BED_BUCKET,
                    "bed_key": set_bed_key,
                    "bed_audio_url": set_bed_audio_url,
                    "intro": intro_text,
                    "detail": detail_text,
                    "artist_text": artist_text,
                    "spotify_track_id": getattr(track, "spotify_track_id", None),
                    "track_name": getattr(track, "track_name", None),
                    "artist_name": getattr(artist, "artist_name", None),
                }

                # ───────── SET INTRO (first track in set only) ─────────
                if idx == 1:

                    # 🎙️ STATION LINER (between sets, skip first set)
                    if set_number > 1 and random.random() < get_liner_probability():
                        liner_bucket, liner_key = get_random_station_liner(lang)

                        logger.info("station_liner_selected source=all_radio")

                        await publish_narration_phase(
                            "liner",
                            track=track,
                            artist=artist,
                            rank=rank,
                            decade=decade_obj.decade_name,
                            genre=genre,
                            bucket=liner_bucket,
                            key=liner_key,
                            voice_style="before",
                            extra_context={
                                **radio_context,
                                "station_liner": True,
                                "liner_key": liner_key,
                                "between_sets": True,
                            },
                        )

                    # 🎙️ SET INTRO
                    await publish_set_intro_phase(
                        tts_languages=langs,
                        decade_slug=decade,
                        genre_slug=genre,
                        decade_name=decade_obj.decade_name,
                        genre_name=genre_obj.genre_name,
                        track=track,
                        artist=artist,
                        rank=rank,
                        radio_context=radio_context,
                    )

                # ───────── INTRO ─────────
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
                            texts=texts_by_language,  # next step: multi-language text bundle
                            voice_style="before",
                            extra_context=radio_context,
                        )

                # ───────── DETAIL ─────────
                if play_detail:
                    detail_audio_queue = []

                    for narration_lang in langs:
                        detail_bucket, detail_key = detail_by_lang.get(narration_lang, (None, None))
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
                            texts=texts_by_language,  # later: multi-language More Info bundle
                            voice_style="before",
                            extra_context=radio_context,
                        )

                # ───────── ARTIST ─────────
                if play_artist_for_track:
                    artist_audio_queue = []

                    for narration_lang in langs:
                        artist_bucket, artist_key = artist_by_lang.get(narration_lang, (None, None))
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
                            texts=texts_by_language ,
                            voice_style="before",
                            extra_context=radio_context,
                        )
                        played_artist_ids.add(artist_identity)

                # ───────── TRACK ─────────
                if track.spotify_track_id:
                    track_done_event(user_id).clear()
                    # The track duration plus this start timestamp are the
                    # authoritative clock; never expose the default epoch.
                    begin_track(user_id, (track.duration_ms or 0) / 1000.0)

                    update_phase(
                        user_id,
                        "track",
                        is_playing=True,
                        stopped=False,
                        track_name=track.track_name,
                        artist_name=artist.artist_name,
                        current_rank=rank,
                        current_ranking_id=tr_rank.id,
                        spotify_track_id=track.spotify_track_id,
                        context={
                            **radio_context,

                            "mode": "spotify",

                            "intro": intro_text,
                            "detail": detail_text,
                            "artist_text": artist_text,

                            "spotify_track_id": track.spotify_track_id,
                        },
                    )

                    logger.info(
                        "🎯 RADIO PUBLISHED track frame rank=%s spotify=%s",
                        rank,
                        track.spotify_track_id,
                    )


                    # ✅ wait for Spotify track to finish
                    await track_done_event(user_id).wait()

                    # small buffer to avoid noise / abrupt transition
                    await asyncio.sleep(0.75)


    except asyncio.CancelledError:
        logger.info("⛔ ALL RADIO sequence cancelled")
        raise

    finally:
        flags.is_playing = False
        flags.stopped = True
        logger.info("📻 ALL RADIO mode stopped")
