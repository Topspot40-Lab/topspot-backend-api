from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from backend.studio.studio_config import (
    BLACK_SECONDS,
    FADE_SECONDS,
    FPS,
    LANGUAGE_SECONDS,
    LOGO_SECONDS,
    PRODUCTIONS_DIR,
    TITLE_SECONDS,
)


def run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("FFmpeg failed.")


def render_card(
    *,
    source: Path,
    destination: Path,
    duration: float,
) -> None:
    fade_out_start = max(0.0, duration - FADE_SECONDS)

    command = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(source),
        "-t",
        str(duration),
        "-vf",
        (
            f"fade=t=in:st=0:d={FADE_SECONDS},"
            f"fade=t=out:st={fade_out_start}:d={FADE_SECONDS},"
            "format=yuv420p"
        ),
        "-r",
        str(FPS),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(destination),
    ]

    run_ffmpeg(command)

def render_black(
        *,
        destination: Path,
        duration: float,
) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s=1920x1080:r={FPS}",
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(destination),
    ]

    run_ffmpeg(command)


def concatenate_videos(
    parts: list[Path],
    destination: Path,
) -> None:
    concat_file = destination.parent / "opening_concat.txt"

    concat_file.write_text(
        "\n".join(
            f"file '{part.resolve().as_posix()}'"
            for part in parts
        ),
        encoding="utf-8",
    )

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(destination),
    ]

    run_ffmpeg(command)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    root = PRODUCTIONS_DIR / args.slug
    manifest_path = root / "manifest.json"

    if not manifest_path.exists():
        raise SystemExit(
            f"Manifest not found: {manifest_path}"
        )

    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    logo = root / manifest["cards"]["logo"]
    languages = root / manifest["cards"]["languages"]
    title = root / manifest["cards"]["title"]

    output = root / "output" / "opening.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    print("🎬 TopSpot40 Studio")
    print(f"Production: {manifest['title']}")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)

        logo_video = work / "01_logo.mp4"
        language_video = work / "02_languages.mp4"
        title_video = work / "03_title.mp4"
        black_video = work / "04_black.mp4"

        render_card(
            source=logo,
            destination=logo_video,
            duration=LOGO_SECONDS,
        )
        print("✓ Logo card")

        render_card(
            source=languages,
            destination=language_video,
            duration=LANGUAGE_SECONDS,
        )
        print("✓ Language card")

        render_card(
            source=title,
            destination=title_video,
            duration=TITLE_SECONDS,
        )
        print("✓ Title card")

        render_black(
            destination=black_video,
            duration=BLACK_SECONDS,
        )
        print("✓ Black transition")

        concatenate_videos(
            [
                logo_video,
                language_video,
                title_video,
                black_video,
            ],
            output,
        )
    print()
    print(f"✅ Opening rendered: {output}")


if __name__ == "__main__":
    main()
