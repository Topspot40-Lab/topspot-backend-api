from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from backend.studio.production import Production
from backend.studio.studio_config import (
    FADE_SECONDS,
    FPS,
    ASSETS_DIR,
    IMAGE_SECONDS,
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
        str(duration),
        "-vf",
        (
            "scale=1920:1080:"
            "force_original_aspect_ratio=decrease,"
            "pad=1920:1080:"
            "(ow-iw)/2:(oh-ih)/2:black,"
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

    images_dir = production.work_root / "images"
    storyboard_path = production.work_root / "storyboard.json"

    image_entries: list[tuple[Path, float, str]] = []

    if storyboard_path.exists():
        storyboard = json.loads(
            storyboard_path.read_text(encoding="utf-8")
        )

        historical_dir = (
            ASSETS_DIR
            / "historical"
            / production.slug
        )

        for scene in storyboard.get("scenes", []):
            scene_number = int(scene["scene"])
            scene_prefix = f"{scene_number:03d}_"

            historical_matches = []

            if historical_dir.exists():
                historical_matches = sorted(
                    candidate
                    for candidate in historical_dir.iterdir()
                    if candidate.is_file()
                    and candidate.name.startswith(scene_prefix)
                    and candidate.suffix.lower()
                    in SUPPORTED_EXTENSIONS
                )

            if historical_matches:
                image_path = historical_matches[0]
                source_kind = "historical"
            else:
                image_path = images_dir / scene["image_file"]
                source_kind = "AI"

            if not image_path.exists():
                raise SystemExit(
                    f"Storyboard image missing: {image_path}"
                )

            image_entries.append(
                (
                    image_path,
                    float(scene["duration_seconds"]),
                    source_kind,
                )
            )
    else:
        images = sorted(
            path
            for path in images_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )

        image_entries = [
            (image, IMAGE_SECONDS, "folder")
            for image in images
        ]

    if not image_entries:
        raise SystemExit(
            f"No images found: {images_dir}"
        )

    output = production.work_root / "output" / "image_sequence.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    print("🎬 TopSpot40 Studio")
    print(f"Production: {production.title}")
    print(f"Images: {len(image_entries)}")
    print("Timing: storyboard-driven" if storyboard_path.exists() else f"Seconds per image: {IMAGE_SECONDS}")
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
