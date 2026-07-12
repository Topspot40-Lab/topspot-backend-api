from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import requests
from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import MusicDocuseries, MusicDocuseriesLocale
from backend.services.supabase_storage import upload_bytes


SUPABASE_PUBLIC_BASE = (
    "https://iizlnzmmhkzedqkolgir.supabase.co"
    "/storage/v1/object/public"
)

# ─────────── YouTube Production Settings ───────────

INTRO_PAUSE_SECONDS = 3.0
OUTRO_PAUSE_SECONDS = 3.0

INTRO_KEY = "youtube/intro.mp3"
OUTRO_KEY = "youtube/outro.mp3"

YOUTUBE_FOLDER = "music-docuseries-youtube"


def public_url(bucket: str, key: str) -> str:
    return f"{SUPABASE_PUBLIC_BASE}/{bucket}/{key}"


def download_file(url: str, destination: Path) -> None:
    response = requests.get(url, timeout=(10, 300))
    response.raise_for_status()
    destination.write_bytes(response.content)


def normalize_mp3(source: Path, destination: Path) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-ar",
        "44100",
        "-ac",
        "2",
        "-b:a",
        "192k",
        str(destination),
    ]

    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


def create_silence(destination: Path, seconds: float) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-t",
        str(seconds),
        "-b:a",
        "192k",
        str(destination),
    ]

    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


def concatenate_mp3s(parts: list[Path], destination: Path) -> None:
    list_file = destination.parent / "concat.txt"

    list_file.write_text(
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
        str(list_file),
        "-c",
        "copy",
        str(destination),
    ]

    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


def build_one(locale: MusicDocuseriesLocale) -> None:
    if not locale.tts_bucket or not locale.tts_key:
        raise RuntimeError(
            f"Locale {locale.id} has no narration TTS."
        )

    intro_key = INTRO_KEY
    outro_key = OUTRO_KEY
    output_key = f"{YOUTUBE_FOLDER}/{locale.id}.mp3"

    print("=" * 80)
    print(f"Building YouTube audio for locale {locale.id}")
    print(f"Language: {locale.language_code}")
    print(f"Bucket:   {locale.tts_bucket}")
    print(f"Story:    {locale.tts_key}")
    print(f"Output:   {output_key}")
    print(f"Intro pause: {INTRO_PAUSE_SECONDS} seconds")
    print(f"Outro pause: {OUTRO_PAUSE_SECONDS} seconds")

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)

        raw_intro = work / "intro_raw.mp3"
        raw_story = work / "story_raw.mp3"
        raw_outro = work / "outro_raw.mp3"

        intro = work / "intro.mp3"
        story = work / "story.mp3"
        outro = work / "outro.mp3"

        pause_after_intro = work / "pause_after_intro.mp3"
        pause_before_outro = work / "pause_before_outro.mp3"

        output = work / "youtube_complete.mp3"

        download_file(
            public_url(locale.tts_bucket, intro_key),
            raw_intro,
        )
        download_file(
            public_url(locale.tts_bucket, locale.tts_key),
            raw_story,
        )
        download_file(
            public_url(locale.tts_bucket, outro_key),
            raw_outro,
        )

        normalize_mp3(raw_intro, intro)
        normalize_mp3(raw_story, story)
        normalize_mp3(raw_outro, outro)

        create_silence(
            pause_after_intro,
            INTRO_PAUSE_SECONDS,
        )
        create_silence(
            pause_before_outro,
            OUTRO_PAUSE_SECONDS,
        )

        concatenate_mp3s(
            [
                intro,
                pause_after_intro,
                story,
                pause_before_outro,
                outro,
            ],
            output,
        )

        upload_bytes(
            bucket=locale.tts_bucket,
            key=output_key,
            data=output.read_bytes(),
            content_type="audio/mpeg",
        )

    print(f"✅ Uploaded {locale.tts_bucket}/{output_key}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    with Session(engine) as session:
        item = session.exec(
            select(MusicDocuseries)
            .where(MusicDocuseries.slug == args.slug)
        ).first()

        if not item:
            raise SystemExit(
                f"Music Docuseries item not found: {args.slug}"
            )

        locales = session.exec(
            select(MusicDocuseriesLocale)
            .where(
                MusicDocuseriesLocale.docuseries_id == item.id
            )
            .where(
                MusicDocuseriesLocale.language_code.in_(
                    ["en", "es", "pt-BR"]
                )
            )
            .order_by(MusicDocuseriesLocale.language_code)
        ).all()

        if len(locales) != 3:
            raise SystemExit(
                f"Expected 3 locales, found {len(locales)}"
            )

        print(item.title)

        for locale in locales:
            build_one(locale)

    print("=" * 80)
    print("Done.")
    print("Built 3 YouTube-ready audio tracks.")


if __name__ == "__main__":
    main()
