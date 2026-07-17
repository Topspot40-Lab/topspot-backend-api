from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from backend.services.supabase_client import supabase
from backend.studio.production import Production
from backend.studio.studio_config import (
    ASSETS_DIR,
    BED_TRACK_BUCKET,
    INTRO_PAUSE_SECONDS,
    OUTRO_PAUSE_SECONDS,
)


DEFAULT_BED_KEY = "bed-tracks/docuseries/bed_01.mp3"
DEFAULT_BED_VOLUME_DB = -26.0
DEFAULT_DUCK_THRESHOLD = 0.03
DEFAULT_DUCK_RATIO = 8.0
DEFAULT_DUCK_ATTACK_MS = 25
DEFAULT_DUCK_RELEASE_MS = 500


def media_duration(path: Path) -> float:
    if not path.exists():
        raise FileNotFoundError(f"Media file not found: {path}")

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


def run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("FFmpeg failed.")


def safe_language_name(language: str) -> str:
    return language.replace("/", "-").replace("\\", "-")


def audio_mix_settings(
    manifest: dict[str, Any],
) -> dict[str, Any]:
    configured = manifest.get("audio_mix", {})

    return {
        "bed_key": configured.get(
            "bed_key",
            DEFAULT_BED_KEY,
        ),
        "bed_volume_db": float(
            configured.get(
                "bed_volume_db",
                DEFAULT_BED_VOLUME_DB,
            )
        ),
        "duck_threshold": float(
            configured.get(
                "duck_threshold",
                DEFAULT_DUCK_THRESHOLD,
            )
        ),
        "duck_ratio": float(
            configured.get(
                "duck_ratio",
                DEFAULT_DUCK_RATIO,
            )
        ),
        "duck_attack_ms": int(
            configured.get(
                "duck_attack_ms",
                DEFAULT_DUCK_ATTACK_MS,
            )
        ),
        "duck_release_ms": int(
            configured.get(
                "duck_release_ms",
                DEFAULT_DUCK_RELEASE_MS,
            )
        ),
    }


def ensure_bed_track(
    *,
    bucket: str,
    bed_key: str,
    destination: Path,
) -> None:
    if destination.exists() and destination.stat().st_size > 0:
        print(f"✓ Using local bed track: {destination}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)

    print(f"Downloading bed track: {bucket}/{bed_key}")

    data = supabase.storage.from_(bucket).download(bed_key)

    if not data:
        raise RuntimeError(
            f"Downloaded bed track was empty: "
            f"{bucket}/{bed_key}"
        )

    destination.write_bytes(data)

    print(
        f"✓ Downloaded bed track: {destination} "
        f"({destination.stat().st_size:,} bytes)"
    )


def build_story_video(
    *,
    opening: Path,
    image_sequence: Path,
    brand_image: Path,
    intro_audio: Path,
    story_audio: Path,
    outro_audio: Path,
    bed_audio: Path,
    output: Path,
    bed_volume_db: float,
    duck_threshold: float,
    duck_ratio: float,
    duck_attack_ms: int,
    duck_release_ms: int,
) -> None:
    opening_seconds = media_duration(opening)
    sequence_seconds = media_duration(image_sequence)
    intro_seconds = media_duration(intro_audio)
    story_seconds = media_duration(story_audio)
    outro_seconds = media_duration(outro_audio)

    if sequence_seconds <= 0:
        raise RuntimeError("Image sequence has no duration.")

    visual_scale = story_seconds / sequence_seconds

    intro_visual_seconds = (
        intro_seconds
        + INTRO_PAUSE_SECONDS
    )

    outro_visual_seconds = (
        OUTRO_PAUSE_SECONDS
        + outro_seconds
    )

    total_seconds = (
        opening_seconds
        + intro_seconds
        + INTRO_PAUSE_SECONDS
        + story_seconds
        + OUTRO_PAUSE_SECONDS
        + outro_seconds
    )

    intro_fade_out_start = max(
        0.0,
        intro_visual_seconds - 0.75,
    )

    outro_fade_out_start = max(
        0.0,
        outro_visual_seconds - 1.25,
    )

    bed_fade_out_start = max(
        0.0,
        total_seconds - 4.0,
    )

    filter_complex = (
        # Story images scaled to the actual narration duration.
        f"[1:v]"
        f"setpts=PTS*{visual_scale:.12f},"
        f"setpts=PTS-STARTPTS,"
        f"setsar=1"
        f"[story_video];"

        # Old Dog artwork used for both branded sections.
        f"[2:v]"
        f"scale=1920:1080:"
        f"force_original_aspect_ratio=decrease,"
        f"pad=1920:1080:"
        f"(ow-iw)/2:(oh-ih)/2:black,"
        f"format=yuv420p,"
        f"setsar=1,"
        f"split=2"
        f"[dog_intro_source][dog_outro_source];"

        f"[dog_intro_source]"
        f"trim=duration={intro_visual_seconds:.6f},"
        f"setpts=PTS-STARTPTS,"
        f"fade=t=in:st=0:d=0.75,"
        f"fade=t=out:"
        f"st={intro_fade_out_start:.6f}:d=0.75"
        f"[intro_video];"

        f"[dog_outro_source]"
        f"trim=duration={outro_visual_seconds:.6f},"
        f"setpts=PTS-STARTPTS,"
        f"fade=t=in:st=0:d=0.75,"
        f"fade=t=out:"
        f"st={outro_fade_out_start:.6f}:d=1.25"
        f"[outro_video];"

        f"[0:v]"
        f"setpts=PTS-STARTPTS,"
        f"setsar=1"
        f"[opening_video];"

        # Complete visual program.
        f"[opening_video]"
        f"[intro_video]"
        f"[story_video]"
        f"[outro_video]"
        f"concat=n=4:v=1:a=0"
        f"[video];"

        # Opening silence exists only in the final timeline.
        f"anullsrc=r=44100:cl=stereo,"
        f"atrim=duration={opening_seconds:.6f}"
        f"[opening_silence];"

        f"[3:a]"
        f"aresample=44100,"
        f"aformat=sample_fmts=fltp:"
        f"sample_rates=44100:"
        f"channel_layouts=stereo,"
        f"asetpts=PTS-STARTPTS"
        f"[intro];"

        f"anullsrc=r=44100:cl=stereo,"
        f"atrim=duration={INTRO_PAUSE_SECONDS:.6f}"
        f"[pause_after_intro];"

        f"[4:a]"
        f"aresample=44100,"
        f"aformat=sample_fmts=fltp:"
        f"sample_rates=44100:"
        f"channel_layouts=stereo,"
        f"asetpts=PTS-STARTPTS"
        f"[story];"

        f"anullsrc=r=44100:cl=stereo,"
        f"atrim=duration={OUTRO_PAUSE_SECONDS:.6f}"
        f"[pause_before_outro];"

        f"[5:a]"
        f"aresample=44100,"
        f"aformat=sample_fmts=fltp:"
        f"sample_rates=44100:"
        f"channel_layouts=stereo,"
        f"asetpts=PTS-STARTPTS"
        f"[outro];"

        # Complete narration program.
        f"[opening_silence]"
        f"[intro]"
        f"[pause_after_intro]"
        f"[story]"
        f"[pause_before_outro]"
        f"[outro]"
        f"concat=n=6:v=0:a=1,"
        f"asplit=2"
        f"[narration_duck][narration_mix];"

        # Looping bed track, softly mixed across the whole video.
        f"[6:a]"
        f"aresample=44100,"
        f"aformat=sample_fmts=fltp:"
        f"sample_rates=44100:"
        f"channel_layouts=stereo,"
        f"atrim=duration={total_seconds:.6f},"
        f"asetpts=PTS-STARTPTS,"
        f"volume={bed_volume_db:.3f}dB,"
        f"afade=t=in:st=0:d=4,"
        f"afade=t=out:"
        f"st={bed_fade_out_start:.6f}:d=4"
        f"[bed_base];"

        # Duck the music whenever narration is present.
        f"[bed_base][narration_duck]"
        f"sidechaincompress="
        f"threshold={duck_threshold:.6f}:"
        f"ratio={duck_ratio:.3f}:"
        f"attack={duck_attack_ms}:"
        f"release={duck_release_ms}"
        f"[bed_ducked];"

        # Narration remains dominant; bed supplies atmosphere.
        f"[narration_mix][bed_ducked]"
        f"amix=inputs=2:"
        f"duration=first:"
        f"dropout_transition=0,"
        f"alimiter=limit=0.95"
        f"[audio]"
    )

    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(opening),
        "-i",
        str(image_sequence),
        "-loop",
        "1",
        "-framerate",
        "30",
        "-i",
        str(brand_image),
        "-i",
        str(intro_audio),
        "-i",
        str(story_audio),
        "-i",
        str(outro_audio),
        "-stream_loop",
        "-1",
        "-i",
        str(bed_audio),
        "-filter_complex",
        filter_complex,
        "-map",
        "[video]",
        "-map",
        "[audio]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-t",
        f"{total_seconds:.6f}",
        str(output),
    ]

    print()
    print("🎬 TopSpot40 Story Video")
    print()
    print(f"Opening:          {opening_seconds:8.3f} sec")
    print(f"Intro:            {intro_seconds:8.3f} sec")
    print(f"Intro pause:      {INTRO_PAUSE_SECONDS:8.3f} sec")
    print(f"Story:            {story_seconds:8.3f} sec")
    print(f"Outro pause:      {OUTRO_PAUSE_SECONDS:8.3f} sec")
    print(f"Outro:            {outro_seconds:8.3f} sec")
    print(f"Bed volume:       {bed_volume_db:8.1f} dB")
    print(f"Visual scale:     {visual_scale:8.6f}")
    print(f"Final duration:   {total_seconds:8.3f} sec")
    print()

    run_ffmpeg(command)

    print()
    print(f"✅ Story video rendered: {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--language", default="en")
    args = parser.parse_args()

    production = Production(args.slug)
    production.ensure_work_dirs()

    language_entry = production.language(args.language)
    locale_id = int(language_entry["locale_id"])
    bucket = str(language_entry["bucket"])

    safe_language = safe_language_name(args.language)

    audio_dir = production.work_root / "audio"
    output_dir = production.work_root / "output"

    opening = output_dir / "opening.mp4"
    image_sequence = output_dir / "image_sequence.mp4"
    brand_image = ASSETS_DIR / "old_dog_new_tracks.png"

    intro_audio = audio_dir / f"intro_{safe_language}.mp3"
    story_audio = (
        audio_dir
        / f"story_{safe_language}_{locale_id}.mp3"
    )
    outro_audio = audio_dir / f"outro_{safe_language}.mp3"

    mix = audio_mix_settings(production.manifest)
    bed_key = str(mix["bed_key"])
    bed_name = Path(bed_key).name
    bed_audio = audio_dir / f"bed_{safe_language}_{bed_name}"

    ensure_bed_track(
        bucket=BED_TRACK_BUCKET,
        bed_key=bed_key,
        destination=bed_audio,
    )

    output = output_dir / f"{args.slug}_{safe_language}.mp4"

    build_story_video(
        opening=opening,
        image_sequence=image_sequence,
        brand_image=brand_image,
        intro_audio=intro_audio,
        story_audio=story_audio,
        outro_audio=outro_audio,
        bed_audio=bed_audio,
        output=output,
        bed_volume_db=float(mix["bed_volume_db"]),
        duck_threshold=float(mix["duck_threshold"]),
        duck_ratio=float(mix["duck_ratio"]),
        duck_attack_ms=int(mix["duck_attack_ms"]),
        duck_release_ms=int(mix["duck_release_ms"]),
    )


if __name__ == "__main__":
    main()
