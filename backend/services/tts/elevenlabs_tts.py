# backend/services/tts/elevenlabs_tts.py

from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import requests
import json
import logging

from backend.config import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_MODEL,            # default model fallback
    VOICE_STABILITY,             # default stability if no per-voice settings provided
    VOICE_SIMILARITY,            # default similarity if no per-voice settings provided
    ELEVEN_MODELS_SUPPORT_LANGUAGE,  # {"eleven_turbo_v2_5", "eleven_flash_v2_5"}
    ELEVEN_LANGUAGE_CODE_MAP,        # {"en":"en","es":"es","pt-BR":"pt"}
)

logger = logging.getLogger("tts_logger")

ELEVEN_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


def generate_tts_mp3(
    *,
    text: str,
    out_path: Path,
    voice_id: str,
    overwrite: bool = False,
    play: bool = False,
    # NEW / optional knobs (match routers/batch):
    settings: Optional[Dict[str, Any]] = None,
    model_id: Optional[str] = None,
    language: Optional[str] = None,   # "en" | "es" | "pt-BR"
    timeout: Tuple[float, float] = (10.0, 120.0),  # (connect, read)
) -> str:
    """
    Synthesize `text` with ElevenLabs and write MP3 to `out_path`.

    - `settings` maps to ElevenLabs voice_settings (stability, similarity_boost, style, use_speaker_boost).
    - `model_id` overrides the default model from config.
    - `language` is enforced ONLY for Turbo/Flash v2.5 models (es/pt require ISO codes).
    """
    if out_path.exists() and not overwrite:
        logger.debug("⚠️ Skipping TTS (exists): %s", out_path)
        return str(out_path)

    if not ELEVENLABS_API_KEY:
        raise RuntimeError("Missing ELEVENLABS_API_KEY")

    # Effective model selection
    effective_model = model_id or ELEVENLABS_MODEL

    # Default voice settings if caller didn't provide any
    voice_settings = settings if settings is not None else {
        "stability": VOICE_STABILITY,
        "similarity_boost": VOICE_SIMILARITY,
    }

    # Map app language → API language code (pt-BR → pt)
    api_lang = None
    if language:
        api_lang = ELEVEN_LANGUAGE_CODE_MAP.get(language, language)

    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    payload: Dict[str, Any] = {
        "text": text,
        "model_id": effective_model,
        "voice_settings": voice_settings,
    }

    # Only Turbo/Flash v2.5 currently honor the `language` field
    if api_lang and effective_model in ELEVEN_MODELS_SUPPORT_LANGUAGE:
        payload["language"] = api_lang

    url = ELEVEN_TTS_URL.format(voice_id=voice_id)

    logger.debug(
        "🎤 ElevenLabs request | voice_id=%s | model_id=%s | lang=%s | settings=%s | out=%s",
        voice_id, effective_model, api_lang, voice_settings, out_path
    )

    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=timeout)
    if r.status_code != 200:
        # include a short snippet of the error body for logs
        snippet = r.text[:500]
        raise RuntimeError(f"❌ ElevenLabs error {r.status_code}: {snippet}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)

    logger.info("✅ TTS generated: %s", out_path)

    if play:
        try:
            from playsound import playsound
            playsound(str(out_path), block=False)
        except Exception as e:
            logger.warning("⚠️ Could not play sound: %s", e)

    return str(out_path)
