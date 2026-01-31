from __future__ import annotations

import logging
import random
from typing import Literal

from fastapi import APIRouter, Query, Depends
from sqlmodel import select

from backend.database import get_db
from backend.models.dbmodels import (
    Track,
    Artist,
    TrackRanking,
    DecadeGenre,
    Decade,
    Genre,
)

from backend.services.single_track_player import play_one_server_side
from backend.services.decade_genre_sequence import run_decade_genre_sequence

from backend.routers.playback_control import start_new_sequence
from backend.state.playback_flags import flags

router = APIRouter(prefix="/supabase/decade-genre", tags=["Supabase: Decade/Genre"])
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# FAST PLAY-FIRST (INSTANT START)
# ─────────────────────────────────────────────
@router.get("/play-first")
async def play_first_decade_genre(
    decade: str = Query(...),
    genre: str = Query(...),
    mode: Literal["count_up", "count_down", "random"] = Query("count_up"),
    tts_language: Literal["en", "es", "ptbr", "pt-BR"] = Query("en"),
    play_intro: bool = Query(True),
    play_detail: bool = Query(True),
    play_artist_description: bool = Query(True),
    play_track: bool = Query(True),
    voice_style: Literal["before", "over"] = Query("before"),
):
    logger.info(
        "⚡ FAST PLAY-FIRST (SERIALIZED): %s/%s lang=%s voice_style=%s",
        decade,
        genre,
        tts_language,
        voice_style,
    )

    async def _run_serial_fast_then_full():
        # ✅ First: rank #1 only
        await run_decade_genre_sequence(
            decade=decade,
            genre=genre,
            start_rank=1,
            end_rank=1,
            mode=mode,
            tts_language=tts_language,
            play_intro=play_intro,
            play_detail=play_detail,
            play_artist_description=play_artist_description,
            play_track=play_track,
            voice_style=voice_style,
        )

        # ✅ THEN continue with 2–40 (no overlap possible)
        await run_decade_genre_sequence(
            decade=decade,
            genre=genre,
            start_rank=2,
            end_rank=40,
            mode=mode,
            tts_language=tts_language,
            play_intro=play_intro,
            play_detail=play_detail,
            play_artist_description=play_artist_description,
            play_track=play_track,
            voice_style=voice_style,
        )

    await start_new_sequence(_run_serial_fast_then_full())

    return {
        "status": "started-fast-serialized",
        "decade": decade,
        "genre": genre,
        "mode": mode,
        "voice_style": voice_style,
    }


# ─────────────────────────────────────────────
# START NEW SEQUENCE (FULL RANGE)
# ─────────────────────────────────────────────
@router.get("/play-sequence")
async def play_sequence_decade_genre(
    decade: str = Query(...),
    genre: str = Query(...),
    start_rank: int = Query(1),
    end_rank: int = Query(40),
    mode: Literal["count_up", "count_down", "random"] = Query("count_up"),
    tts_language: Literal["en", "es", "ptbr", "pt-BR"] = Query("en"),
    play_intro: bool = Query(True),
    play_detail: bool = Query(True),
    play_artist_description: bool = Query(True),
    play_track: bool = Query(False),
    voice_style: Literal["before", "over"] = Query("before"),
):
    logger.info(
        "▶ Launch request: %s/%s %d-%d mode=%s lang=%s voice_style=%s",
        decade,
        genre,
        start_rank,
        end_rank,
        mode,
        tts_language,
        voice_style,
    )

    coro = run_decade_genre_sequence(
        decade=decade,
        genre=genre,
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

    await start_new_sequence(coro)

    return {
        "status": "started",
        "decade": decade,
        "genre": genre,
        "mode": mode,
        "range": [start_rank, end_rank],
        "voice_style": voice_style,
    }


# ─────────────────────────────────────────────
# NEXT TRACK (SINGLE ADVANCE)
# ─────────────────────────────────────────────
@router.post("/next")
async def play_next_decade_genre():
    """
    Advances playback to the NEXT logical track based on:
    - current rank
    - current mode (count_up, count_down, random)
    - current decade/genre
    """

    if not flags.context:
        return {"status": "error", "message": "No active decade/genre context."}

    decade = flags.context.get("decade")
    genre = flags.context.get("genre")
    mode = flags.mode or "count_up"
    current_rank = flags.current_rank

    if not decade or not genre or current_rank is None:
        return {"status": "error", "message": "Missing playback state."}

    db = next(get_db())
    q = (
        select(Track, Artist, TrackRanking)
        .join(Artist, Artist.id == Track.artist_id)
        .join(TrackRanking, TrackRanking.track_id == Track.id)
        .join(DecadeGenre, DecadeGenre.id == TrackRanking.decade_genre_id)
        .join(Decade, Decade.id == DecadeGenre.decade_id)
        .join(Genre, Genre.id == DecadeGenre.genre_id)
        .where(
            Decade.slug == decade,
            Genre.slug == genre,
        )
        .order_by(TrackRanking.ranking)
    )

    rows = db.exec(q).all()

    if not rows:
        return {"status": "error", "message": "No tracks found."}

    ranks = [r[2].ranking for r in rows]

    if current_rank not in ranks:
        return {"status": "error", "message": "Current rank not in sequence."}

    idx = ranks.index(current_rank)

    if mode == "count_up":
        next_idx = idx + 1
    elif mode == "count_down":
        next_idx = idx - 1
    else:
        remaining = [r for r in ranks if r != current_rank]
        if not remaining:
            return {"status": "done", "message": "No more tracks."}
        next_rank = random.choice(remaining)
        next_idx = ranks.index(next_rank)

    if next_idx < 0 or next_idx >= len(ranks):
        return {"status": "done", "message": "End of sequence reached."}

    next_rank = ranks[next_idx]

    logger.info(
        "⏭ NEXT pressed → %s/%s advancing from #%d → #%d (mode=%s)",
        decade,
        genre,
        current_rank,
        next_rank,
        mode,
    )

    await start_new_sequence(
        play_one_server_side(
            decade=decade,
            genre=genre,
            rank=next_rank,
            tts_language=getattr(flags, "lang", "en"),
            mode=mode,
            play_intro=True,
            play_detail=True,
            play_artist_description=True,
            play_track=True,
            voice_style=getattr(flags, "voice_style", "before"),
        )
    )

    return {
        "status": "playing-next",
        "from": current_rank,
        "to": next_rank,
        "mode": mode,
    }


# ─────────────────────────────────────────────
# FRONTEND METADATA (SEQUENCE PREVIEW)
# ─────────────────────────────────────────────
@router.get("/get-sequence")
async def get_sequence_decade_genre(
    decade: str = Query(...),
    genre: str = Query(...),
    start_rank: int = Query(1),
    end_rank: int = Query(40),
    db=Depends(get_db),
):
    q = (
        select(Track, Artist, TrackRanking, Decade, Genre)
        .join(Artist, Artist.id == Track.artist_id)
        .join(TrackRanking, TrackRanking.track_id == Track.id)
        .join(DecadeGenre, DecadeGenre.id == TrackRanking.decade_genre_id)
        .join(Decade, Decade.id == DecadeGenre.decade_id)
        .join(Genre, Genre.id == DecadeGenre.genre_id)
        .where(
            Decade.slug == decade,
            Genre.slug == genre,
            TrackRanking.ranking >= start_rank,
            TrackRanking.ranking <= end_rank,
        )
        .order_by(TrackRanking.ranking)
    )

    rows = db.exec(q).all()

    if not rows:
        return {"status": "empty", "tracks": []}

    tracks = [
        {
            "rank": tr_rank.ranking,
            "trackName": track.track_name,
            "artistName": artist.artist_name,

            # 🎨 ARTWORK
            "albumArtwork": getattr(track, "album_artwork", None),
            "artistArtwork": getattr(artist, "artist_artwork", None),

            # 📝 TEXT CONTENT
            "detail": getattr(track, "detail", None),
            "artistDescription": getattr(artist, "artist_description", None),

            # 📅 META
            "albumName": getattr(track, "album_name", None),
            "yearReleased": getattr(track, "year_released", None),
            "durationMs": getattr(track, "duration_ms", None),
            "spotifyTrackId": getattr(track, "spotify_track_id", None),
            # ✅ INTRO TEXT (from track_ranking)
            "intro": tr_rank.intro,
        }
        for track, artist, tr_rank, _, _ in rows
    ]

    return {"status": "ok", "total": len(tracks), "tracks": tracks}
