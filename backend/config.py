# backend/config.py

SUPABASE_URL = ""
SUPABASE_SERVICE_ROLE_KEY = ""

# Audio buckets (safe defaults)
BUCKETS = {
    "en": {
        "intro": "audio-en",
        "detail": "audio-en",
        "artist": "audio-en",
    }
}

AUDIO_PREFIXES = {
    "intro": "intro",
    "detail": "detail",
    "artist": "artist",
}

INTRO_GAIN_DB = -4.0
DETAIL_GAIN_DB = 0.0
ARTIST_GAIN_DB = 0.0


# backend/config.py

SPOTIFY_BED_TRACK_ID = None  # narration bed disabled for now
