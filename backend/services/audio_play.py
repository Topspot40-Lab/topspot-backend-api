from __future__ import annotations

import tempfile
import requests

from backend.services.audio_urls import supabase_public_url

try:
    from playsound3 import playsound  # type: ignore
except Exception:  # pragma: no cover
    playsound = None


def play_supabase_mp3(bucket: str, object_path: str) -> str:
    """
    Downloads the MP3 from Supabase Storage using a FULL URL and plays it if audio support exists.
    Returns the resolved URL so you can copy/paste it into a browser for verification.
    """
    url = supabase_public_url(bucket, object_path)
    print("🎧 MP3 URL:", url)

    r = requests.get(url, timeout=30)
    r.raise_for_status()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
        f.write(r.content)
        tmp_path = f.name

    print("✅ Downloaded to:", tmp_path)

    if playsound is None:
        print("⚠️ playsound3 not installed; skipping playback. Install with: pip install playsound3")
        return url

    playsound(tmp_path)
    return url
