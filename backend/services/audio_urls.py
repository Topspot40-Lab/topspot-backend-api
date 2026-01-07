# backend/services/audio_urls.py
from __future__ import annotations

from urllib.parse import quote
import os

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")

def supabase_public_url(bucket: str, object_path: str) -> str:
    if not SUPABASE_URL:
        raise RuntimeError("Missing SUPABASE_URL")

    # Ensure we don't accidentally pass "audio-en/intro/..." as object_path
    object_path = object_path.lstrip("/")
    if object_path.startswith(bucket + "/"):
        object_path = object_path[len(bucket) + 1 :]

    # URL-encode the path safely (spaces, unicode, etc.)
    safe_path = quote(object_path, safe="/")

    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{safe_path}"
