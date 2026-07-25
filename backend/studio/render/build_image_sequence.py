from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.studio.historical_assets import (
    historical_directories_for_production,
)

from backend.studio.production import Production
from backend.studio.render.motion_controller import (
    MotionKind,
    select_motion,
)
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


@dataclass(frozen=True)
class ImageEntry:
    shot_number: int
    image: Path
    duration: float
    source_kind: str
    scene_text: str


def run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("FFmpeg failed.")


def build_ken_burns_filter(
    *,
    duration: float,
    shot_number: int,
    source_kind: str,
    scene_text: str,
    previous_kind: MotionKind | None,
) -> tuple[str, str, MotionKind]:
    """
    Build the FFmpeg filter for a controller-selected camera move.

    The Motion Controller owns motion selection. This renderer only
    translates the decision into the final video filter.
    """
    fade_out_start = max(
        0.0,
        duration - FADE_SECONDS,
    )

    total_frames = max(
        2,
        round(duration * FPS),
    )

    motion = select_motion(
        shot_number=shot_number,
        total_frames=total_frames,
        duration=duration,
        source_kind=source_kind,
        scene_text=scene_text,
        previous_kind=previous_kind,
    )

    visual_filter = (
        "scale=1920:1080:"
        "force_original_aspect_ratio=decrease,"
        "pad=1920:1080:"
        "(ow-iw)/2:(oh-ih)/2:black,"
        "zoompan="
        f"z='{motion.zoom_expression}':"
        f"x='{motion.x_expression}':"
        f"y='{motion.y_expression}':"
        "d=1:"
        "s=1920x1080:"
        f"fps={FPS},"
        f"fade=t=in:st=0:d={FADE_SECONDS},"
        f"fade=t=out:st={fade_out_start:.6f}:"
        f"d={FADE_SECONDS},"
        "format=yuv420p"
    )

    return visual_filter, motion.name, motion.kind

def render_image(
    *,
    source: Path,
    destination: Path,
    duration: float,
    shot_number: int,
    source_kind: str,
    scene_text: str,
    previous_kind: MotionKind | None,
) -> tuple[str, MotionKind]:
    (
        visual_filter,
        motion_name,
        motion_kind,
    ) = build_ken_burns_filter(
        duration=duration,
        shot_number=shot_number,
        source_kind=source_kind,
        scene_text=scene_text,
        previous_kind=previous_kind,
    )

    command = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(FPS),
        "-i",
        str(source),
        "-t",
        f"{duration:.6f}",
        "-vf",
        visual_filter,
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

    return motion_name, motion_kind


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


def resolve_curated_historical_image(
    shot: dict[str, Any],
) -> Path | None:
    historical_asset = shot.get(
        "historical_asset"
    )

    if not isinstance(historical_asset, dict):
        return None

    approved_image = str(
        historical_asset.get(
            "approved_image"
        )
        or ""
    ).strip()

    if not approved_image:
        return None

    candidate = Path(approved_image)

    if not candidate.is_absolute():
        candidate = (
            ASSETS_DIR.parent
            / candidate
        )

    return candidate


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
) -> list[ImageEntry]:
    storyboard_path = (
        production.production_root / "storyboard.json"
    )
    storyboard = load_storyboard(storyboard_path)

    images_dir = production.work_root / "images"
    historical_dir = (
        historical_directories_for_production(
            production
        ).photos
    )

    entries: list[ImageEntry] = []

    for scene in storyboard.get("scenes", []):
        for shot in scene.get("visual_shots", []):
            shot_number = int(shot["shot_number"])
            filename = str(
                shot.get("filename")
                or f"{shot_number:03d}.png"
            )
            duration = float(shot["estimated_seconds"])

            historical_image = (
                resolve_curated_historical_image(
                    shot
                )
            )

            if historical_image is None:
                historical_image = (
                    find_historical_image(
                        historical_dir=historical_dir,
                        shot_number=shot_number,
                    )
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

            scene_text = " ".join(
                value
                for value in (
                    str(scene.get("narration") or ""),
                    str(scene.get("visual_intent") or ""),
                    str(shot.get("visual_intent") or ""),
                    str(shot.get("prompt") or ""),
                )
                if value
            )

            entries.append(
                ImageEntry(
                    shot_number=shot_number,
                    image=image_path,
                    duration=duration,
                    source_kind=source_kind,
                    scene_text=scene_text,
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

    station_name = "render_image_sequence"
    production.session.start_station(station_name)

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

        previous_kind: MotionKind | None = None

        for index, entry in enumerate(
            image_entries,
            start=1,
        ):
            destination = work / f"{index:03d}.mp4"

            motion_name, motion_kind = render_image(
                source=entry.image,
                destination=destination,
                duration=entry.duration,
                shot_number=entry.shot_number,
                source_kind=entry.source_kind,
                scene_text=entry.scene_text,
                previous_kind=previous_kind,
            )

            previous_kind = motion_kind
            rendered_parts.append(destination)

            print(
                f"✓ {entry.image.name} "
                f"({entry.duration:.3f} seconds, "
                f"{entry.source_kind}, "
                f"Ken Burns: {motion_name})"
            )

        concatenate_videos(
            rendered_parts,
            output,
        )

    ai_count = sum(
        1
        for entry in image_entries
        if entry.source_kind.casefold() == "ai"
    )
    historical_count = len(image_entries) - ai_count
    total_duration = round(
        sum(entry.duration for entry in image_entries),
        3,
    )

    production.session.metric(
        "visual_shots",
        len(image_entries),
        station=station_name,
    )
    production.session.metric(
        "ai_images",
        ai_count,
        station=station_name,
    )
    production.session.metric(
        "historical_images",
        historical_count,
        station=station_name,
    )
    production.session.metric(
        "video_duration_seconds",
        total_duration,
        station=station_name,
    )
    production.session.metric(
        "fps",
        FPS,
        station=station_name,
    )
    production.session.metric(
        "resolution",
        "1920x1080",
        station=station_name,
    )

    production.session.artifact(
        "image_sequence",
        output,
        station=station_name,
    )

    production.session.finish_station(
        station_name,
        success=True,
    )

    print()
    print(f"✅ Image sequence rendered: {output}")


if __name__ == "__main__":
    main()
