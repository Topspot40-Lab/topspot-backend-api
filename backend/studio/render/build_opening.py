from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path
from backend.studio.production import Production
from backend.studio.timeline import build_opening_timeline

from backend.studio.studio_config import (
    BLACK_SECONDS,
    FADE_SECONDS,
    FPS,
    LANGUAGE_SECONDS,
    LOGO_SECONDS,
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

    production = Production(args.slug)
    production.ensure_work_dirs()

    missing = production.validate()
    if missing:
        print("❌ Production is missing required files:")
        for item in missing:
            print(f"  {item}")
        raise SystemExit(1)

    logo = production.card("logo")
    languages = production.card("languages")
    title = production.card("title")

    timeline = build_opening_timeline(
        logo=logo,
        languages=languages,
        title=title,
        logo_seconds=LOGO_SECONDS,
        language_seconds=LANGUAGE_SECONDS,
        title_seconds=TITLE_SECONDS,
        black_seconds=BLACK_SECONDS,
    )

    output = production.output("video").with_name("opening.mp4")
    output.parent.mkdir(parents=True, exist_ok=True)

    print("🎬 TopSpot40 Studio")
    print(f"Production: {production.title}")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        rendered_parts: list[Path] = []

        for index, item in enumerate(timeline.items, start=1):
            destination = work / f"{index:02d}_{item.name.replace(' ', '_')}.mp4"

            if item.kind == "card":
                if item.source is None:
                    raise RuntimeError(
                        f"Timeline card has no source: {item.name}"
                    )

                render_card(
                    source=item.source,
                    destination=destination,
                    duration=item.duration_seconds or 0.0,
                )

            elif item.kind == "black":
                render_black(
                    destination=destination,
                    duration=item.duration_seconds or 0.0,
                )

            else:
                raise RuntimeError(
                    f"Unsupported opening timeline item: {item.kind}"
                )

            rendered_parts.append(destination)
            print(f"✓ {item.name}")

        concatenate_videos(
            rendered_parts,
            output,
        )
    print()
    print(f"✅ Opening rendered: {output}")


if __name__ == "__main__":
    main()
