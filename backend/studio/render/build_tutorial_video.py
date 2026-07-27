from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


STUDIO_DIR = Path(__file__).resolve().parents[1]
PRODUCTIONS_DIR = STUDIO_DIR / "productions"
WORK_DIR = STUDIO_DIR / "work"
FPS = 30
WIDTH = 1920
HEIGHT = 1080
FADE_SECONDS = 0.35


def run(command: list[str]) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("Command failed.")


def probe_duration(path: Path) -> float:
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
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def load_plan(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Tutorial plan not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def render_scene(
    *,
    image: Path,
    audio: Path,
    destination: Path,
    duration: float,
) -> None:
    fade_out_start = max(0.0, duration - FADE_SECONDS)
    video_filter = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fade=t=in:st=0:d={FADE_SECONDS},"
        f"fade=t=out:st={fade_out_start:.3f}:d={FADE_SECONDS},"
        "format=yuv420p"
    )

    run(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-i",
            str(image),
            "-i",
            str(audio),
            "-t",
            f"{duration:.3f}",
            "-vf",
            video_filter,
            "-af",
            "apad",
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            str(destination),
        ]
    )


def concatenate(parts: list[Path], destination: Path) -> None:
    concat_file = destination.parent / "tutorial_concat.txt"
    concat_file.write_text(
        "\n".join(
            f"file '{part.resolve().as_posix()}'"
            for part in parts
        ),
        encoding="utf-8",
    )
    run(
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
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a TopSpot40 screenshot tutorial from existing audio."
        )
    )
    parser.add_argument(
        "--slug",
        default="nostalgia_program_tutorial",
    )
    parser.add_argument(
        "--language",
        default="en",
        choices=("en", "es", "pt-BR"),
    )
    args = parser.parse_args()

    production_root = PRODUCTIONS_DIR / args.slug
    plan_path = production_root / f"tutorial_{args.language}.json"
    plan = load_plan(plan_path)

    screenshots_root = (
        production_root / "screenshots" / args.language
    )
    work_root = WORK_DIR / args.slug
    audio_root = work_root / "audio"
    output_root = work_root / "output"
    output_root.mkdir(parents=True, exist_ok=True)

    scenes = plan.get("scenes", [])
    if not scenes:
        raise SystemExit("Tutorial plan contains no scenes.")

    print("TOPSPOT40 STUDIO — SCREENSHOT TUTORIAL")
    print("=" * 72)
    print(f"Title:    {plan.get('title', args.slug)}")
    print(f"Language: {args.language}")
    print(f"Scenes:   {len(scenes)}")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_root = Path(tmpdir)
        rendered_parts: list[Path] = []

        for index, scene in enumerate(scenes, start=1):
            image = screenshots_root / str(scene["image"])
            if not image.exists():
                raise FileNotFoundError(
                    f"Tutorial screenshot missing: {image}"
                )

            audio_name = scene.get("audio_file")
            if not audio_name:
                raise ValueError(
                    f"Scene {index} does not define audio_file."
                )

            audio = audio_root / str(audio_name)
            if not audio.exists():
                raise FileNotFoundError(
                    f"Tutorial audio missing: {audio}"
                )

            audio_seconds = probe_duration(audio)
            hold_after = float(scene.get("hold_after_seconds", 0.8))
            duration = max(
                float(scene.get("minimum_seconds", 0.0)),
                audio_seconds + hold_after,
            )

            part = temp_root / f"{index:03d}.mp4"
            render_scene(
                image=image,
                audio=audio,
                destination=part,
                duration=duration,
            )
            rendered_parts.append(part)

            print(
                f"✓ Scene {index:02d}: {image.name} + "
                f"{audio.name} ({duration:.2f} seconds)"
            )

        output = output_root / f"{args.slug}_{args.language}.mp4"
        concatenate(rendered_parts, output)

    total_seconds = probe_duration(output)
    print()
    print(f"✅ Tutorial created: {output}")
    print(f"Duration: {total_seconds:.2f} seconds")


if __name__ == "__main__":
    main()
