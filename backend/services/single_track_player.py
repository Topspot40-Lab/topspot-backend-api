import logging
from typing import Literal

from backend.services.decade_genre_sequence import run_decade_genre_sequence
from backend.state.playback_flags import flags

logger = logging.getLogger(__name__)


async def play_one_server_side(
    *,
    decade: str,
    genre: str,
    rank: int,
    tts_language: str = "en",
    mode: Literal["count_up", "count_down", "random"] = "count_up",
    play_intro: bool = True,
    play_detail: bool = True,
    play_artist_description: bool = True,
    play_track: bool = True,
    text_intro: bool = False,
    text_detail: bool = False,
    text_artist_description: bool = False,
    voice_style: Literal["before", "over"] = "before",
) -> None:
    """
    Play a single track using the full sequence engine.
    (Pause mode only — no auto-advance logic here.)
    """

    logger.info(
        "🎯 Single-play request — %s/%s rank #%d, mode=%s, lang=%s, voice_style=%s",
        decade,
        genre,
        rank,
        mode,
        tts_language,
        voice_style,
    )

    # ─────────────────────────────────────────────
    # ✅ STEP 1: Persist playback intent (NO behavior change)
    # ─────────────────────────────────────────────
    flags.mode = mode
    flags.context = {
        "decade": decade,
        "genre": genre,
    }
    flags.current_rank = rank
    flags.lang = tts_language
    flags.voice_style = voice_style

    # ─────────────────────────────────────────────
    # Play exactly ONE rank (frontend controls selection)
    # ─────────────────────────────────────────────
    await run_decade_genre_sequence(
        decade=decade,
        genre=genre,
        start_rank=rank,
        end_rank=rank,
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
