# backend/config/__init__.py
"""
Lightweight config package initializer (no logging imports, no cycles).

It mirrors the old monolithic config so legacy imports like:
    from backend.config import (APP_VERSION, BASE_DIR, XAI_API_URL, DEFAULT_XAI_MODEL,
        MODEL_BY_LANG, TTS_PROFILES, SUPABASE_URL, BUCKETS, AUDIO_PREFIXES,
        SPOTIFY_BED_TRACK_ID, ENABLE_TRACK_DETAIL, ...)
keep working.

Rules:
- Read from env when present, else use sensible defaults (matching your old file).
- Provide dynamic __getattr__ to resolve future ALL_CAPS env vars automatically.
"""

from __future__ import annotations
import os, re, json
from typing import Any, Dict, List

from dotenv import load_dotenv
load_dotenv()  # ensure .env loads even in python shell


# ─────────────────────────────────────────────────────────────────────────────
# Single source of truth for volumes & play length
# (edit values in backend/config/volume.py, not here)
# ─────────────────────────────────────────────────────────────────────────────
from .volume import (
    INTRO_GAIN_DB, DETAIL_GAIN_DB, ARTIST_GAIN_DB,
    MAIN_VOLUME_PERCENT, BED_VOLUME_PERCENT, BED_FACTOR, BED_FADE_MS,
    PLAY_FULL_TRACK, TRACK_PLAY_SECONDS, FULL_TRACK_FALLBACK_SECONDS, MAX_FULL_TRACK_SECONDS,
    resolve_track_sleep_seconds,
)

# ----------------- helpers -----------------
def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None: return default
    s = v.strip().lower()
    if s in ("1","true","yes","on"): return True
    if s in ("0","false","no","off",""): return False
    return True

def _env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else str(v)

def _env_list(name: str, default: List[str] | None = None) -> List[str]:
    raw = os.getenv(name)
    if not raw: return list(default or [])
    s = raw.strip()
    if s.startswith("["):
        try:
            val = json.loads(s)
            if isinstance(val, list): return [str(x).strip() for x in val]
        except Exception:
            pass
    return [item.strip() for item in s.split(",") if item.strip()]

def _env_dict(name: str, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    raw = os.getenv(name)
    if not raw: return dict(default or {})
    try:
        val = json.loads(raw)
        if isinstance(val, dict): return val
    except Exception:
        pass
    return dict(default or {})

def _env_int(name: str, default: int) -> int:
    try:
        return int(_env_str(name, str(default)))
    except Exception:
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(_env_str(name, str(default)))
    except Exception:
        return default

def _extract_spotify_track_id(value: str | None) -> str | None:
    if not value: return None
    v = value.strip()
    m = re.match(r"^spotify:track:([A-Za-z0-9]{22})$", v)
    if m: return m.group(1)
    m = re.match(r"^https?://open\.spotify\.com/track/([A-Za-z0-9]{22})", v)
    if m: return m.group(1)
    v_no_q = v.split("?", 1)[0]
    if re.fullmatch(r"[A-Za-z0-9]{22}", v_no_q):
        return v_no_q
    return None

# ----------------- app metadata -----------------
APP_VERSION: str  = _env_str("APP_VERSION", "1.0.8")
LAST_UPDATED: str = _env_str("LAST_UPDATED", "2025-08-10: 11:00 am")

# ----------------- paths -----------------
from pathlib import Path
# Project root: .../topspot_json_creator
PROJECT_ROOT = Path(__file__).resolve().parents[2]

BASE_DIR: str   = _env_str("BASE_DIR", str(PROJECT_ROOT))
SCHEMA_PATH: str = _env_str("SCHEMA_PATH", str(PROJECT_ROOT / "backend" / "schemas" / "track_schema.json"))
TEST_JSON_DIR: str = _env_str("TEST_JSON_DIR", str(PROJECT_ROOT / "backend" / "tests" / "json_tests" / "xai"))

# Feature toggles (explicit defaults so imports never fail)
ENABLE_RANK_INTRO: bool    = _env_bool("ENABLE_RANK_INTRO", True)
ENABLE_TRACK_DETAIL: bool  = _env_bool("ENABLE_TRACK_DETAIL", True)
ENABLE_ARTIST_DETAIL: bool = _env_bool("ENABLE_ARTIST_DETAIL", True)

# ----------------- Spotify creds (client-credentials flow) -----------------
SPOTIFY_CLIENT_ID: str = _env_str("SPOTIFY_CLIENT_ID", "") or _env_str("SPOTIPY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET: str = _env_str("SPOTIFY_CLIENT_SECRET", "") or _env_str("SPOTIPY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI: str = _env_str("SPOTIFY_REDIRECT_URI", "") or _env_str("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
SPOTIFY_MARKET: str = _env_str("SPOTIFY_MARKET", "US")

# ───────── Detail generation knobs (used by xai_track_detail) ─────────
DETAIL_SENTENCES_MIN = _env_int("DETAIL_SENTENCES_MIN", 2)
DETAIL_SENTENCES_MAX = _env_int("DETAIL_SENTENCES_MAX", 3)
DETAIL_WORDS_MIN     = _env_int("DETAIL_WORDS_MIN", 60)
DETAIL_WORDS_MAX     = _env_int("DETAIL_WORDS_MAX", 90)
DETAIL_FORBID_NEW_FACTS = _env_bool("DETAIL_FORBID_NEW_FACTS", False)  # allow widely-known context
DETAIL_FOLK_ACOUSTIC_MODE = _env_bool("DETAIL_FOLK_ACOUSTIC_MODE", False)
DETAIL_FALLBACK_SENTENCE  = _env_bool("DETAIL_FALLBACK_SENTENCE", False)  # turn off generic line
# Optional: a default theme hint if caller doesn't pass one
DETAIL_GENRE_CONTEXT_DEFAULT = _env_str("DETAIL_GENRE_CONTEXT_DEFAULT", "")




def spotify_creds_ok() -> bool:
    return bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)

# ----------------- provider/LLM (xAI) -----------------
LLM_PROVIDER: str = _env_str("LLM_PROVIDER", "xai")

XAI_API_KEY: str   = _env_str("XAI_API_KEY", "")
XAI_API_BASE: str  = _env_str("XAI_API_BASE", "https://api.x.ai/v1")
XAI_API_URL: str   = _env_str("XAI_API_URL", f"{XAI_API_BASE}/chat/completions")
DEFAULT_XAI_MODEL: str = _env_str("XAI_MODEL", "grok-3-latest")
XAI_MODEL: str     = _env_str("XAI_MODEL", DEFAULT_XAI_MODEL)

# HTTP behavior / retries
XAI_CONNECT_TIMEOUT: int = _env_int("XAI_CONNECT_TIMEOUT", 10)
XAI_READ_TIMEOUT: int    = _env_int("XAI_READ_TIMEOUT", 120)
XAI_MAX_RETRIES: int     = _env_int("XAI_MAX_RETRIES", 3)
XAI_BACKOFF_FACTOR: float = _env_float("XAI_BACKOFF_FACTOR", 1.5)
XAI_TIMEOUT_SECONDS: int  = _env_int("XAI_TIMEOUT_SECONDS", XAI_READ_TIMEOUT)

# Gen defaults
TEMPERATURE_DEFAULT: float = _env_float("TEMPERATURE_DEFAULT", 0.3)
TOP_P_DEFAULT: float       = _env_float("TOP_P_DEFAULT", 1.0)
TOP_K_DEFAULT: int         = _env_int("TOP_K_DEFAULT", 40)
MAX_TOKENS_DEFAULT: int    = _env_int("MAX_TOKENS_DEFAULT", 1024)

# Fallback/testing
FALLBACK_TO_TEST_ON_XAI_ERROR: bool = _env_bool("FALLBACK_TO_TEST_ON_XAI_ERROR", True)
FALLBACK_TEST_FILE_NUMBER:   int    = _env_int("FALLBACK_TEST_FILE_NUMBER", 1)

# ----------------- Supabase -----------------
SUPABASE_URL: str              = _env_str("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY: str = _env_str("SUPABASE_SERVICE_ROLE_KEY", "")

# Language→bucket and kind prefixes (dicts, as in old config)
LANGUAGE_BUCKETS: Dict[str, str] = _env_dict("LANGUAGE_BUCKETS", {
    "en":    "audio-en",
    "es":    "audio-es",
    "pt-BR": "audio-ptbr",
})
BUCKETS: Dict[str, Dict[str, str]] = _env_dict("BUCKETS", {
    lang: {"intro": b, "detail": b, "artist": b, "collections_intro": b}
    for lang, b in LANGUAGE_BUCKETS.items()
})
AUDIO_PREFIXES: Dict[str, str] = _env_dict(
    "AUDIO_PREFIXES",
    {"intro": "intro", "detail": "detail", "artist": "artist", "collections_intro": "collections-intro"}
)

# Legacy single-purpose bucket names (kept for back-compat)
BUCKET_TRACK_INTRO:   str = _env_str("BUCKET_TRACK_INTRO",  "track-intro-mp3-files")
BUCKET_TRACK_DETAIL:  str = _env_str("BUCKET_TRACK_DETAIL", "track-detail-mp3-files")
BUCKET_ARTIST:        str = _env_str("BUCKET_ARTIST",       "artist-mp3-files")
BUCKET_SPOTIFY_TRACK: str = _env_str("BUCKET_SPOTIFY_TRACK","spotify-track-mp3-files")
SUPABASE_BUCKET_ARTIST_MP3: str = _env_str("SUPABASE_BUCKET_ARTIST_MP3", BUCKETS.get("en", {}).get("artist", "audio-en"))

# ----------------- Spotify ─ playback bed/mix -----------------
# NOTE: All *volume* numbers (MAIN_VOLUME_PERCENT, BED_* etc.) come from volume.py.
BED_ENABLED: bool          = _env_bool("BED_ENABLED", True)
BED_DEVICE_ID: str | None  = _env_str("BED_DEVICE_ID") or None

_bed_id_raw = (
    _env_str("BED_SPOTIFY_TRACK_ID")
    or _env_str("SPOTIFY_BED_TRACK_ID")
    or "2ggZjjqszgPpFUMyCwPrrj"
)
BED_SPOTIFY_TRACK_ID: str | None = _extract_spotify_track_id(_bed_id_raw)
SPOTIFY_BED_TRACK_ID: str | None = BED_SPOTIFY_TRACK_ID  # alias

# ----------------- ElevenLabs TTS -----------------
ELEVENLABS_ENABLE: bool  = _env_bool("ELEVENLABS_ENABLE", False)
ELEVENLABS_API_KEY: str  = _env_str("ELEVENLABS_API_KEY", "") or _env_str("ELEVEN_API_KEY", "")
# Single voice IDs (back-compat exports)
VOICE_ID_INTRO:  str = _env_str("VOICE_ID_INTRO",  "EXAVITQu4vr4xnSDxMaL")
VOICE_ID_ARTIST: str = _env_str("VOICE_ID_ARTIST", "Vr6EZfGAz5W6T1wn6b4p")
VOICE_ID_TRACK:  str = _env_str("VOICE_ID_TRACK",  "oWAxZDx7w5VEj9dCyTzz")

VOICE_STABILITY:  float = _env_float("VOICE_STABILITY",  0.5)
VOICE_SIMILARITY: float = _env_float("VOICE_SIMILARITY", 0.75)

_ELEVEN_MODEL_ID_DEFAULT = _env_str("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
ELEVENLABS_MODEL: str = _ELEVEN_MODEL_ID_DEFAULT                  # alias
ELEVEN_MODEL_ID:  str = _ELEVEN_MODEL_ID_DEFAULT                  # back-compat
ELEVEN_MODEL_ID_ES:    str = _env_str("ELEVENLABS_MODEL_ES",    "eleven_turbo_v2_5")
ELEVEN_MODEL_ID_PT_BR: str = _env_str("ELEVENLABS_MODEL_PT_BR", "eleven_turbo_v2_5")

ELEVEN_MODELS_SUPPORT_LANGUAGE = {"eleven_turbo_v2_5", "eleven_flash_v2_5"}
ELEVEN_LANGUAGE_CODE_MAP = {"en": "en", "es": "es", "pt-BR": "pt"}

# Canonical per-language map used by services
MODEL_BY_LANG: Dict[str, str] = {
    "en":    _ELEVEN_MODEL_ID_DEFAULT,
    "es":    ELEVEN_MODEL_ID_ES,
    "pt-BR": ELEVEN_MODEL_ID_PT_BR,
}

SUPPORTED_LANGS: List[str]   = ["en", "es", "pt-BR"]
DEFAULT_LANGUAGE: str        = _env_str("DEFAULT_TTS_LANGUAGE", "en")
DEFAULT_TTS_LANGUAGE: str    = DEFAULT_LANGUAGE

# Feature toggles
SKIP_TTS_IF_EXISTS: bool     = _env_bool("SKIP_TTS_IF_EXISTS", True)
VOICE_PREVIEW_ENABLED: bool  = _env_bool("VOICE_PREVIEW_ENABLED", False)

# Profiles (defaults, env-overridable via TTS_PROFILES_JSON)
def _default_tts_profiles() -> Dict[str, Dict[str, Any]]:
    return {
        "en": {
            "intro":  {"voice_id": "PrwKJdvtTbJVdosRhS1O", "settings": {"stability": 0.5,  "similarity_boost": 0.8,  "style": 0.4,  "use_speaker_boost": True}},
            "detail": {"voice_id": "pqHfZKP75CvOlQylNhV4","settings": {"stability": 0.6,  "similarity_boost": 0.6,  "style": 0.2,  "use_speaker_boost": False}},
            "artist": {"voice_id": "94zOad0g7T7K4oa7zhDq","settings": {"stability": 0.55, "similarity_boost": 0.7,  "style": 0.35, "use_speaker_boost": True}},
        },
        "es": {
            "intro":  {"voice_id": "PrwKJdvtTbJVdosRhS1O","settings": {"stability": 0.5,  "similarity_boost": 0.85, "style": 0.5,  "use_speaker_boost": True}},
            "detail": {"voice_id": "94zOad0g7T7K4oa7zhDq","settings": {"stability": 0.65, "similarity_boost": 0.7,  "style": 0.25, "use_speaker_boost": False}},
            "artist": {"voice_id": "bIHbv24MWmeRgasZH58o","settings": {"stability": 0.6,  "similarity_boost": 0.8,  "style": 0.4,  "use_speaker_boost": True}},
        },
        "pt-BR": {
            "intro":  {"voice_id": "5dF3gH7abcXYZ1234567","settings": {"stability": 0.5,  "similarity_boost": 0.85, "style": 0.5,  "use_speaker_boost": True}},
            "detail": {"voice_id": "cyD08lEy76q03ER1jZ7y","settings": {"stability": 0.65, "similarity_boost": 0.7,  "style": 0.25, "use_speaker_boost": False}},
            "artist": {"voice_id": "CstacWqMhJQlnfLPxRG4","settings": {"stability": 0.6,  "similarity_boost": 0.8,  "style": 0.4,  "use_speaker_boost": True}},
        },
    }

_TTS_PROFILES_JSON = _env_str("TTS_PROFILES_JSON").strip()
if _TTS_PROFILES_JSON:
    try:
        parsed = json.loads(_TTS_PROFILES_JSON)
        TTS_PROFILES: Dict[str, Dict[str, Any]] = parsed if isinstance(parsed, dict) else _default_tts_profiles()
    except Exception:
        TTS_PROFILES = _default_tts_profiles()
else:
    TTS_PROFILES = _default_tts_profiles()

# ----------------- generation / misc toggles -----------------
BATCH_SIZE: int = _env_int("BATCH_SIZE", 10)

GENERATE_JSON_LOGGING_ENABLED: bool = _env_bool("GENERATE_JSON_LOGGING_ENABLED", False)
GENERATE_JSON_LOG_PATH:       str  = _env_str("GENERATE_JSON_LOG_PATH", "backend/logs/new_json_all_decades.log")

# DB query logging level (string like "DEBUG"/"INFO")
DB_QUERIES_LOG_LEVEL: str = _env_str("DB_QUERIES_LOG_LEVEL", "DEBUG").upper()

# Spotify blacklist (set or CSV env; keep backward-compatible set->list behavior)
SPOTIFY_BLACKLIST: List[str] = [s.lower() for s in _env_list("SPOTIFY_BLACKLIST", default=["garth brooks","chris gaines","bob seger","king crimson","joanna newsom"])]

# ----------------- dynamic env bridge -----------------
_NUMERIC_INT_SUFFIXES = ("TIMEOUT","RETRIES","MAX_TOKENS","TOP_K","N","COUNT","SIZE","PORT","BATCH_SIZE")
_NUMERIC_FLOAT_SUFFIXES = ("TEMPERATURE","TOP_P","P","FRACTION","RATIO")

def __getattr__(name: str):
    """
    Fallback for ALL_CAPS names not defined above.
    - *_PREFIXES or *_MAP → JSON dict
    - *LIST / BLACKLIST / WHITELIST → JSON/CSV → list[str]
    - numeric-ish suffixes → int/float
    - boolean-ish strings → bool
    - else → raw str
    """
    if not name.isupper(): raise AttributeError(name)
    val = os.getenv(name)
    if val is None: raise AttributeError(name)

    low = name.lower()
    if low.endswith("prefixes") or low.endswith("map"):
        return _env_dict(name, default={})
    if low.endswith("list") or "blacklist" in low or "whitelist" in low:
        return _env_list(name, default=[])
    if name.endswith(_NUMERIC_INT_SUFFIXES):
        return _env_int(name, 0)
    if name.endswith(_NUMERIC_FLOAT_SUFFIXES):
        return _env_float(name, 0.0)
    sval = val.strip().lower()
    if sval in ("1","true","yes","on","0","false","no","off",""):
        return _env_bool(name, False)
    return val

__all__ = [
    # meta
    "APP_VERSION","LAST_UPDATED",
    # paths
    "BASE_DIR","SCHEMA_PATH","TEST_JSON_DIR",
    # provider/xai
    "LLM_PROVIDER","XAI_API_KEY","XAI_API_BASE","XAI_API_URL","DEFAULT_XAI_MODEL","XAI_MODEL",
    "XAI_CONNECT_TIMEOUT","XAI_READ_TIMEOUT","XAI_MAX_RETRIES","XAI_BACKOFF_FACTOR","XAI_TIMEOUT_SECONDS",
    # gen defaults
    "TEMPERATURE_DEFAULT","TOP_P_DEFAULT","TOP_K_DEFAULT","MAX_TOKENS_DEFAULT",
    # fallbacks
    "FALLBACK_TO_TEST_ON_XAI_ERROR","FALLBACK_TEST_FILE_NUMBER",
    # supabase/buckets
    "SUPABASE_URL","SUPABASE_SERVICE_ROLE_KEY",
    "LANGUAGE_BUCKETS","BUCKETS","AUDIO_PREFIXES",
    "BUCKET_TRACK_INTRO","BUCKET_TRACK_DETAIL","BUCKET_ARTIST","BUCKET_SPOTIFY_TRACK","SUPABASE_BUCKET_ARTIST_MP3",
    # bed/mix (volumes come from volume.py)
    "BED_ENABLED","BED_DEVICE_ID",
    "BED_SPOTIFY_TRACK_ID","SPOTIFY_BED_TRACK_ID",
    # elevenlabs/tts
    "ELEVENLABS_ENABLE","ELEVENLABS_API_KEY",
    "VOICE_ID_INTRO","VOICE_ID_ARTIST","VOICE_ID_TRACK",
    "VOICE_STABILITY","VOICE_SIMILARITY",
    "ELEVENLABS_MODEL","ELEVEN_MODEL_ID","ELEVEN_MODEL_ID_ES","ELEVEN_MODEL_ID_PT_BR",
    "ELEVEN_MODELS_SUPPORT_LANGUAGE","ELEVEN_LANGUAGE_CODE_MAP",
    "MODEL_BY_LANG","SUPPORTED_LANGS","DEFAULT_LANGUAGE","DEFAULT_TTS_LANGUAGE",
    "TTS_PROFILES","SKIP_TTS_IF_EXISTS","VOICE_PREVIEW_ENABLED",
    # misc toggles
    "BATCH_SIZE","GENERATE_JSON_LOGGING_ENABLED","GENERATE_JSON_LOG_PATH","DB_QUERIES_LOG_LEVEL",
    # lists
    "SPOTIFY_BLACKLIST",
    "ENABLE_RANK_INTRO", "ENABLE_TRACK_DETAIL", "ENABLE_ARTIST_DETAIL",
    "SPOTIFY_CLIENT_ID","SPOTIFY_CLIENT_SECRET","SPOTIFY_REDIRECT_URI","SPOTIFY_MARKET","spotify_creds_ok",
    # volumes & play length (from volume.py)
    "INTRO_GAIN_DB","DETAIL_GAIN_DB","ARTIST_GAIN_DB",
    "MAIN_VOLUME_PERCENT","BED_VOLUME_PERCENT","BED_FACTOR","BED_FADE_MS",
    "PLAY_FULL_TRACK","TRACK_PLAY_SECONDS","FULL_TRACK_FALLBACK_SECONDS","MAX_FULL_TRACK_SECONDS",
    "resolve_track_sleep_seconds",
]
