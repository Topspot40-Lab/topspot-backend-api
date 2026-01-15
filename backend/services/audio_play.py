from __future__ import annotations

import tempfile
import requests

from backend.services.audio_urls import resolve_audio_ref


try:
    from playsound3 import playsound  # type: ignore
except Exception:  # pragma: no cover
    playsound = None


def play_supabase_mp3(bucket: str, object_path: str) -> str:
    """
    Resolves and plays an MP3 from either:
      • Local filesystem (dev)
      • Supabase public URL (Render)
    """
    ref = resolve_audio_ref(bucket, object_path)
    print("🎧 MP3 REF:", ref)

    # Local file?
    if ref.startswith(("C:\\", "/", "./")):
        tmp_path = ref
    else:
        # Remote URL
        r = requests.get(ref, timeout=30)
        r.raise_for_status()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            f.write(r.content)
            tmp_path = f.name

        print("✅ Downloaded to:", tmp_path)

    if playsound is None:
        print("⚠️ playsound3 not installed; skipping playback.")
        return ref

    playsound(tmp_path)
    return ref
