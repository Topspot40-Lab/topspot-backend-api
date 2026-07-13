from __future__ import annotations

import argparse
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from backend.studio.production import Production
from backend.studio.studio_config import (
    INTRO_PAUSE_SECONDS,
    OPENING_VISUAL_SECONDS,
    OUTRO_PAUSE_SECONDS,
)


LANGUAGES = ("en", "es", "pt-BR")


@dataclass(frozen=True)
class SegmentDurations:
    intro: float
    story: float
    outro: float

    @property
    def total(self) -> float:
        return (
            OPENING_VISUAL_SECONDS
            + self.intro
            + INTRO_PAUSE_SECONDS
            + self.story
            + OUTRO_PAUSE_SECONDS
            + self.outro
        )


def run(command: list[str]) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("FFmpeg command failed.")


def media_duration(path: Path) -> float:
    if not path.exists():
        raise FileNotFoundError(path)

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    return float(result.stdout.strip())


def safe_language(code: str) -> str:
    return code.replace("/", "-").replace("\\", "-")


def download_if_missing(
    *,
    bucket: str,
    key: str,
    destination: Path,
) -> None:
    if destination.exists() and destination.stat().st_size > 0:
        return

    from backend.services.supabase_client import supabase

    data = supabase.storage.from_(bucket).download(key)

    if not data:
        raise RuntimeError(f"Empty download: {bucket}/{key}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)

    print(
        f"✓ Downloaded {destination} "
        f"({destination.stat().st_size:,} bytes)"
    )


def ensure_language_parts(
    production: Production,
    language_code: str,
) -> tuple[Path, Path, Path]:
    language = production.documentary.language(language_code)
    safe = safe_language(language_code)
    audio_dir = production.work_root / "audio"

    intro = audio_dir / f"intro_{safe}.mp3"
    story = production.audio(language_code)
    outro = audio_dir / f"outro_{safe}.mp3"

    if not language.tts_bucket:
        raise RuntimeError(
            f"Missing TTS bucket for {language_code}"
        )

    download_if_missing(
        bucket=language.tts_bucket,
        key="youtube/intro.mp3",
        destination=intro,
    )

    download_if_missing(
        bucket=language.tts_bucket,
        key="youtube/outro.mp3",
        destination=outro,
    )

    if not story.exists() or story.stat().st_size == 0:
        raise FileNotFoundError(
            f"Story narration missing: {story}"
        )

    return intro, story, outro


def fit_audio(
    *,
    source: Path,
    destination: Path,
    target_seconds: float,
) -> None:
    source_seconds = media_duration(source)
    tempo = source_seconds / target_seconds

    if not 0.5 <= tempo <= 2.0:
        raise RuntimeError(
            f"Unsupported tempo adjustment for {source}: {tempo:.3f}"
        )

    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-af",
            (
                "aresample=44100,"
                "aformat=sample_fmts=fltp:"
                "sample_rates=44100:"
                "channel_layouts=stereo,"
                f"atempo={tempo:.8f},"
                "apad,"
                f"atrim=duration={target_seconds:.8f}"
            ),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(destination),
        ]
    )


def create_silence(
    destination: Path,
    seconds: float,
) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            f"{seconds:.8f}",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(destination),
        ]
    )


def concatenate_audio(
    *,
    parts: list[Path],
    destination: Path,
) -> None:
    inputs: list[str] = []

    for part in parts:
        inputs.extend(["-i", str(part)])

    labels = "".join(
        f"[{index}:a]"
        for index in range(len(parts))
    )

    run(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            f"{labels}concat=n={len(parts)}:v=0:a=1[a]",
            "-map",
            "[a]",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(destination),
        ]
    )


def reference_durations(
    production: Production,
) -> SegmentDurations:
    intro, story, outro = ensure_language_parts(
        production,
        "en",
    )

    return SegmentDurations(
        intro=media_duration(intro),
        story=media_duration(story),
        outro=media_duration(outro),
    )


def build_language_master(
    *,
    production: Production,
    language_code: str,
    targets: SegmentDurations,
) -> Path:
    intro, story, outro = ensure_language_parts(
        production,
        language_code,
    )

    youtube_dir = production.work_root / "output" / "youtube"
    youtube_dir.mkdir(parents=True, exist_ok=True)

    destination = (
        youtube_dir
        / f"{production.slug}_{safe_language(language_code)}.mp3"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)

        fitted_intro = work / "intro.mp3"
        fitted_story = work / "story.mp3"
        fitted_outro = work / "outro.mp3"

        opening_silence = work / "opening_silence.mp3"
        intro_pause = work / "intro_pause.mp3"
        outro_pause = work / "outro_pause.mp3"

        fit_audio(
            source=intro,
            destination=fitted_intro,
            target_seconds=targets.intro,
        )
        fit_audio(
            source=story,
            destination=fitted_story,
            target_seconds=targets.story,
        )
        fit_audio(
            source=outro,
            destination=fitted_outro,
            target_seconds=targets.outro,
        )

        create_silence(
            opening_silence,
            OPENING_VISUAL_SECONDS,
        )
        create_silence(
            intro_pause,
            INTRO_PAUSE_SECONDS,
        )
        create_silence(
            outro_pause,
            OUTRO_PAUSE_SECONDS,
        )

        concatenate_audio(
            parts=[
                opening_silence,
                fitted_intro,
                intro_pause,
                fitted_story,
                outro_pause,
                fitted_outro,
            ],
            destination=destination,
        )

    print(
        f"✓ {language_code}: {destination} "
        f"({media_duration(destination):.3f} seconds)"
    )

    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build synchronized complete-language MP3 masters "
            "for a TopSpot Studio production."
        )
    )
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    production = Production(args.slug)
    production.ensure_work_dirs()

    targets = reference_durations(production)

    print("🎙 Building synchronized language masters")
    print(f"Production: {production.documentary.title}")
    print(f"Target duration: {targets.total:.3f} seconds")
    print()

    for language_code in LANGUAGES:
        build_language_master(
            production=production,
            language_code=language_code,
            targets=targets,
        )

    print()
    print("✅ Three language MP3 masters complete")


if __name__ == "__main__":
    main()
