from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from backend.studio.production import Production
from backend.studio.studio_config import (
    ASSETS_DIR,
    FADE_SECONDS,
    FPS,
)


SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


def run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("FFmpeg failed.")


def render_image(
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
        f"{duration:.6f}",
        "-vf",
        (
            "scale=1920:1080:"
            "force_original_aspect_ratio=decrease,"
            "pad=1920:1080:"
            "(ow-iw)/2:(oh-ih)/2:black,"
            f"fade=t=in:st=0:d={FADE_SECONDS},"
            f"fade=t=out:st={fade_out_start:.6f}:d={FADE_SECONDS},"
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


def concatenate_videos(
    parts: list[Path],
    destination: Path,
) -> None:
    concat_file = destination.parent / "image_sequence_concat.txt"

    concat_file.write_text(
        "\n".join(
            f"file '{part.resolve().as_posix()}'"
            for part in parts
        ),
        encoding="utf-8",
    )

    run_ffmpeg(
        [
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
    )


def load_storyboard(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Storyboard not found: {path}")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid storyboard JSON: {path}") from exc


def find_historical_image(
    *,
    historical_dir: Path,
    shot_number: int,
) -> Path | None:
    if not historical_dir.exists():
        return None

    prefixes = (
        f"{shot_number:03d}_",
        f"{shot_number:02d}_",
    )

    matches = sorted(
        candidate
        for candidate in historical_dir.iterdir()
        if candidate.is_file()
        and candidate.name.startswith(prefixes)
        and candidate.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    return matches[0] if matches else None


def collect_image_entries(
    production: Production,
) -> list[tuple[Path, float, str]]:
    storyboard_path = (
        production.production_root / "storyboard.json"
    )
    storyboard = load_storyboard(storyboard_path)

    images_dir = production.work_root / "images"
    historical_dir = (
        ASSETS_DIR
        / "historical"
        / production.slug
    )

    entries: list[tuple[Path, float, str]] = []

    for scene in storyboard.get("scenes", []):
        for shot in scene.get("visual_shots", []):
            shot_number = int(shot["shot_number"])
            filename = str(
                shot.get("filename")
                or f"{shot_number:03d}.png"
            )
            duration = float(shot["estimated_seconds"])

            historical_image = find_historical_image(
                historical_dir=historical_dir,
                shot_number=shot_number,
            )

            if historical_image is not None:
                image_path = historical_image
                source_kind = "historical"
            else:
                image_path = images_dir / filename
                source_kind = "AI"

            if not image_path.exists():
                raise FileNotFoundError(
                    f"Storyboard image missing: {image_path}"
                )

            entries.append(
                (
                    image_path,
                    duration,
                    source_kind,
                )
            )

    return entries


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render the visual shots in a TopSpot Studio storyboard "
            "into one silent image-sequence video."
        )
    )
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    production = Production(args.slug)
    production.ensure_work_dirs()

    image_entries = collect_image_entries(production)

    if not image_entries:
        raise SystemExit(
            f"No visual shots found for production: {args.slug}"
        )

    output = (
        production.work_root
        / "output"
        / "image_sequence.mp4"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    print("🎬 TopSpot40 Studio")
    print(f"Production: {production.documentary.title}")
    print(f"Visual shots: {len(image_entries)}")
    print("Timing: storyboard-driven")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        rendered_parts: list[Path] = []

        for index, (image, duration, source_kind) in enumerate(
            image_entries,
            start=1,
        ):
            destination = work / f"{index:03d}.mp4"

            render_image(
                source=image,
                destination=destination,
                duration=duration,
            )

            rendered_parts.append(destination)

            print(
                f"✓ {image.name} "
                f"({duration:.3f} seconds, {source_kind})"
            )

        concatenate_videos(
            rendered_parts,
            output,
        )

    print()
    print(f"✅ Image sequence rendered: {output}")


if __name__ == "__main__":
    main()
