from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from backend.studio.audio.build_language_masters import (
    media_duration,
    reference_durations,
)
from backend.studio.production import Production
from backend.studio.render.build_story_video import (
    audio_mix_settings,
    ensure_bed_track,
)
from backend.studio.studio_config import (
    ASSETS_DIR,
    INTRO_PAUSE_SECONDS,
    OUTRO_PAUSE_SECONDS,
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


def build_youtube_master(
    *,
    production: Production,
) -> Path:
    output_dir = production.work_root / "output"
    audio_dir = production.work_root / "audio"

    opening = output_dir / "opening.mp4"
    image_sequence = output_dir / "image_sequence.mp4"
    brand_image = ASSETS_DIR / "old_dog_new_tracks.png"

    for required in (
        opening,
        image_sequence,
        brand_image,
    ):
        if not required.exists():
            raise FileNotFoundError(required)

    targets = reference_durations(production)

    opening_seconds = media_duration(opening)
    sequence_seconds = media_duration(image_sequence)

    intro_visual_seconds = (
        targets.intro + INTRO_PAUSE_SECONDS
    )
    outro_visual_seconds = (
        OUTRO_PAUSE_SECONDS + targets.outro
    )

    total_seconds = (
        opening_seconds
        + intro_visual_seconds
        + targets.story
        + outro_visual_seconds
    )

    visual_scale = targets.story / sequence_seconds

    mix = audio_mix_settings(production.manifest)
    bed_key = str(mix["bed_key"])
    bed_name = Path(bed_key).name

    bed_audio = audio_dir / f"bed_youtube_{bed_name}"

    english = production.documentary.language("en")

    if not english.tts_bucket:
        raise RuntimeError("English audio bucket is missing.")

    ensure_bed_track(
        bucket=english.tts_bucket,
        bed_key=bed_key,
        destination=bed_audio,
    )

    bed_fade_out_start = max(0.0, total_seconds - 4.0)

    filter_complex = (
        f"[1:v]"
        f"setpts=PTS*{visual_scale:.12f},"
        f"setpts=PTS-STARTPTS"
        f"[story_video];"

        f"[2:v]"
        f"scale=1920:1080:"
        f"force_original_aspect_ratio=decrease,"
        f"pad=1920:1080:"
        f"(ow-iw)/2:(oh-ih)/2:black,"
        f"format=yuv420p,"
        f"split=2"
        f"[intro_source][outro_source];"

        f"[intro_source]"
        f"trim=duration={intro_visual_seconds:.8f},"
        f"setpts=PTS-STARTPTS"
        f"[intro_video];"

        f"[outro_source]"
        f"trim=duration={outro_visual_seconds:.8f},"
        f"setpts=PTS-STARTPTS"
        f"[outro_video];"

        f"[0:v]"
        f"setpts=PTS-STARTPTS"
        f"[opening_video];"

        f"[opening_video]"
        f"[intro_video]"
        f"[story_video]"
        f"[outro_video]"
        f"concat=n=4:v=1:a=0"
        f"[video];"

        f"[3:a]"
        f"aresample=44100,"
        f"aformat=sample_fmts=fltp:"
        f"sample_rates=44100:"
        f"channel_layouts=stereo,"
        f"atrim=duration={total_seconds:.8f},"
        f"asetpts=PTS-STARTPTS,"
        f"volume={float(mix['bed_volume_db']):.3f}dB,"
        f"afade=t=in:st=0:d=4,"
        f"afade=t=out:"
        f"st={bed_fade_out_start:.8f}:d=4,"
        f"alimiter=limit=0.95"
        f"[audio]"
    )

    youtube_dir = output_dir / "youtube"
    youtube_dir.mkdir(parents=True, exist_ok=True)

    output = youtube_dir / f"{production.slug}.mp4"

    run_ffmpeg(
        [
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
            f"{total_seconds:.8f}",
            str(output),
        ]
    )

    print()
    print(f"✅ YouTube master rendered: {output}")
    print(f"   Duration: {total_seconds:.3f} seconds")
    print("   Audio: bed track only")

    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a language-neutral TopSpot YouTube video "
            "containing visuals and bed music only."
        )
    )
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    production = Production(args.slug)
    production.ensure_work_dirs()

    build_youtube_master(
        production=production,
    )


if __name__ == "__main__":
    main()
