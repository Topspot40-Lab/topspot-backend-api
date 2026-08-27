from __future__ import annotations

from io import BytesIO, TextIOWrapper
from pathlib import Path

import backend.config  # noqa: F401
from backend.studio.render import build_story_video


class _BedStorage:
    def download(self, _: str) -> bytes:
        return b"bed-track"


def test_ensure_bed_track_status_is_windows_console_safe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Status output must not fail under the legacy Windows CP1252 console."""
    console = TextIOWrapper(BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr("sys.stdout", console)
    monkeypatch.setattr(
        build_story_video.supabase.storage,
        "from_",
        lambda _: _BedStorage(),
    )

    destination = tmp_path / "bed.mp3"
    build_story_video.ensure_bed_track(
        bucket="audio-en",
        bed_key="bed-tracks/docuseries/bed_01.mp3",
        destination=destination,
    )

    console.flush()
    assert destination.read_bytes() == b"bed-track"
    assert "[ok] Downloaded bed track" in console.buffer.getvalue().decode("cp1252")