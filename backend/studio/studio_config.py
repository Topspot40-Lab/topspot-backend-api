"""
TopSpot40 Studio Configuration

Shared production settings for all Studio modules.
"""

from pathlib import Path


# ─────────────────────────────────────────────
# Studio directories
# ─────────────────────────────────────────────

STUDIO_ROOT = Path("backend/studio")
PRODUCTIONS_DIR = STUDIO_ROOT / "productions"
WORK_DIR = STUDIO_ROOT / "work"
ASSETS_DIR = STUDIO_ROOT / "assets"

# -----------------------------------------------------------------------------
# Ken Burns
# -----------------------------------------------------------------------------

KEN_BURNS_ENABLED = True

# Zoom limits
KEN_BURNS_MIN_ZOOM = 1.00
KEN_BURNS_MAX_ZOOM = 1.08



# ─────────────────────────────────────────────
# Video
# ─────────────────────────────────────────────

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 30

IMAGE_SECONDS = 8.0

# ─────────────────────────────────────────────
# Opening sequence
# ─────────────────────────────────────────────

LOGO_SECONDS = 2.0
LANGUAGE_SECONDS = 1.5
TITLE_SECONDS = 4.0
BLACK_SECONDS = 1.0
FADE_SECONDS = 0.5

OPENING_VISUAL_SECONDS = (
    LOGO_SECONDS
    + LANGUAGE_SECONDS
    + TITLE_SECONDS
    + BLACK_SECONDS
)


# ─────────────────────────────────────────────
# Audio

BED_TRACK_BUCKET = "audio-en"
# ─────────────────────────────────────────────

INTRO_PAUSE_SECONDS = 3.0
OUTRO_PAUSE_SECONDS = 3.0

INTRO_KEY = "youtube/intro.mp3"
OUTRO_KEY = "youtube/outro.mp3"
YOUTUBE_FOLDER = "music-docuseries-youtube"


# ─────────────────────────────────────────────
# Branding
# ─────────────────────────────────────────────

PROGRAM_NAME = "TopSpot40 Music Docuseries"
WEBSITE = "TopSpot40.com"
