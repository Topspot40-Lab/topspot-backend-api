# backend/services/audio_urls.py
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")

# ✅ master switch: local (default) vs remote (Render)
AUDIO_MODE = os.getenv("AUDIO_MODE", "local").strip().lower()

# Optional: where local audio files live on disk (only used in local mode)
# Set this if you want a single canonical local folder, otherwise we just return the object_path.
LOCAL_AUDIO_ROOT = os.getenv("LOCAL_AUDIO_ROOT", "").strip()


def supabase_public_url(bucket: str, object_path: str) -> str:
    if not SUPABASE_URL:
        raise RuntimeError("Missing SUPABASE_URL")

    object_path = object_path.lstrip("/")
    if object_path.startswith(bucket + "/"):
        object_path = object_path[len(bucket) + 1 :]

    safe_path = quote(object_path, safe="/")
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{safe_path}"


def resolve_audio_ref(bucket: str, object_path: str) -> str:
    """
    Return an audio reference appropriate for the environment:

    - AUDIO_MODE=remote  -> Supabase public URL (Render-friendly)
    - AUDIO_MODE=local   -> local filesystem path (Rule #1 safe)
    """
    object_path = object_path.lstrip("/")
    if object_path.startswith(bucket + "/"):
        object_path = object_path[len(bucket) + 1 :]

    if AUDIO_MODE == "remote":
        return supabase_public_url(bucket, object_path)

    # local mode
    if LOCAL_AUDIO_ROOT:
        return str(Path(LOCAL_AUDIO_ROOT) / bucket / object_path)

    # fallback (not recommended but kept for safety)
    return object_path


def is_remote_audio() -> bool:
    return AUDIO_MODE == "remote"
