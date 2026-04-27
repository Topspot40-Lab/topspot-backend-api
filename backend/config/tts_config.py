# backend/config/tts_config.py

import os
from .helpers import env_bool

_ELEVEN_MODEL_ID_DEFAULT = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2_5")

ELEVENLABS_ENABLE  = env_bool("ELEVENLABS_ENABLE", False)
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

VOICE_ID_INTRO  = os.getenv("VOICE_ID_INTRO",  "EXAVITQu4vr4xnSDxMaL")
VOICE_ID_ARTIST = os.getenv("VOICE_ID_ARTIST", "Vr6EZfGAz5W6T1wn6b4p")
VOICE_ID_TRACK  = os.getenv("VOICE_ID_TRACK",  "oWAxZDx7w5VEj9dCyTzz")

VOICE_STABILITY  = float(os.getenv("VOICE_STABILITY",  "0.5"))
VOICE_SIMILARITY = float(os.getenv("VOICE_SIMILARITY", "0.75"))

ELEVENLABS_MODEL = _ELEVEN_MODEL_ID_DEFAULT
ELEVEN_MODEL_ID  = _ELEVEN_MODEL_ID_DEFAULT
ELEVEN_MODEL_ID_ES    = os.getenv("ELEVENLABS_MODEL_ES",    "eleven_turbo_v2_5")
ELEVEN_MODEL_ID_PT_BR = os.getenv("ELEVENLABS_MODEL_PT_BR", "eleven_turbo_v2_5")

ELEVEN_MODELS_SUPPORT_LANGUAGE = {"eleven_turbo_v2_5", "eleven_flash_v2_5"}
ELEVEN_LANGUAGE_CODE_MAP = {"en":"en","es":"es","pt-BR":"pt"}

MODEL_BY_LANG = {"en": _ELEVEN_MODEL_ID_DEFAULT, "es": ELEVEN_MODEL_ID_ES, "pt-BR": ELEVEN_MODEL_ID_PT_BR}
SUPPORTED_LANGS  = ["en","es","pt-BR"]
DEFAULT_LANGUAGE = os.getenv("DEFAULT_TTS_LANGUAGE", "en")
DEFAULT_TTS_LANGUAGE = DEFAULT_LANGUAGE

SKIP_TTS_IF_EXISTS    = env_bool("SKIP_TTS_IF_EXISTS", True)
VOICE_PREVIEW_ENABLED = env_bool("VOICE_PREVIEW_ENABLED", False)

TTS_PROFILES = {
    "en": {
        "intro":  {"voice_id": "PrwKJdvtTbJVdosRhS1O",  "settings": {"stability": 0.5,  "similarity_boost": 0.8, "style": 0.4,  "use_speaker_boost": True}},
        "detail": {"voice_id": "pqHfZKP75CvOlQylNhV4", "settings": {"stability": 0.6,  "similarity_boost": 0.6, "style": 0.2,  "use_speaker_boost": False}},
        "artist": {"voice_id": "94zOad0g7T7K4oa7zhDq", "settings": {"stability": 0.55, "similarity_boost": 0.7, "style": 0.35, "use_speaker_boost": True}},
    },
    "es": {
        "intro":  {"voice_id": "PrwKJdvtTbJVdosRhS1O", "settings": {"stability": 0.5, "similarity_boost": 0.85, "style": 0.5, "use_speaker_boost": True}},
        "detail": {"voice_id": "94zOad0g7T7K4oa7zhDq", "settings": {"stability": 0.65, "similarity_boost": 0.7, "style": 0.25, "use_speaker_boost": False}},
        "artist": {"voice_id": "bIHbv24MWmeRgasZH58o", "settings": {"stability": 0.6, "similarity_boost": 0.8, "style": 0.4, "use_speaker_boost": True}},
    },
    "pt-BR": {
        "intro":  {"voice_id": "cyD08lEy76q03ER1jZ7y", "settings": {"stability": 0.5, "similarity_boost": 0.85, "style": 0.7, "use_speaker_boost": True}},
        "detail": {"voice_id": "cyD08lEy76q03ER1jZ7y", "settings": {"stability": 0.65, "similarity_boost": 0.7, "style": 0.25, "use_speaker_boost": False}},
        "artist": {"voice_id": "CstacWqMhJQlnfLPxRG4", "settings": {"stability": 0.6, "similarity_boost": 0.8, "style": 0.4, "use_speaker_boost": True}},
    },
}