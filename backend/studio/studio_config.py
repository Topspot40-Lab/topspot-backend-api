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


# ─────────────────────────────────────────────
# Video
# ─────────────────────────────────────────────

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 30


# ─────────────────────────────────────────────
# Opening sequence
# ─────────────────────────────────────────────

LOGO_SECONDS = 5.0
LANGUAGE_SECONDS = 8.0
TITLE_SECONDS = 8.0
BLACK_SECONDS = 1.5
FADE_SECONDS = 1.25


# ─────────────────────────────────────────────
# Audio
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
