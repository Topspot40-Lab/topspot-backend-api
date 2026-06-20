from __future__ import annotations

import argparse
import tempfile
from datetime import datetime, UTC
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import MusicDocuseries, MusicDocuseriesLocale
from backend.config.tts_config import TTS_PROFILES, MODEL_BY_LANG
from backend.services.tts.elevenlabs_tts import generate_tts_mp3
from backend.services.supabase_storage import upload_bytes


BUCKET_BY_LANG = {
    "en": "audio-en",
    "es": "audio-es",
    "pt-BR": "audio-ptbr",
}


def estimate_duration_seconds(text_value: str) -> int:
    words = len(text_value.split())
    return max(1, int(words / 2.5))


def normalize_language(value: str) -> str:
    if value.lower() in ("pt", "pt-br", "ptbr"):
        return "pt-BR"
    return value.lower()


def generate_one(
    *,
    session: Session,
    item: MusicDocuseries,
    locale: MusicDocuseriesLocale,
    language: str,
    bucket: str,
    voice_id: str,
    settings: dict | None,
    model_id: str | None,
    overwrite: bool,
    play: bool,
) -> bool:
    if locale.tts_key and not overwrite:
        print(f"Skipping existing Music Docuseries MP3: {item.slug}")
        print(f"Bucket: {locale.tts_bucket}")
        print(f"Key:    {locale.tts_key}")
        return False

    key = f"music-docuseries/{locale.id}.mp3"

    print("=" * 80)
    print("Generating Music Docuseries TTS")
    print(f"Title:    {item.title}")
    print(f"Slug:     {item.slug}")
    print(f"Locale:   {locale.id}")
    print(f"Language: {language}")
    print(f"Voice ID: {voice_id}")
    print(f"Model:    {model_id}")
    print(f"Bucket:   {bucket}")
    print(f"Key:      {key}")
    print(f"Chars:    {len(locale.story_text)}")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / f"music_docuseries_{locale.id}.mp3"

        generate_tts_mp3(
            text=locale.story_text,
            out_path=out_path,
            voice_id=voice_id,
            overwrite=True,
            play=play,
            settings=settings,
            model_id=model_id,
            language=language,
            timeout=(10.0, 300.0),
        )

        data = out_path.read_bytes()
        upload_bytes(bucket=bucket, key=key, data=data, content_type="audio/mpeg")

    locale.tts_bucket = bucket
    locale.tts_key = key
    locale.duration_seconds = estimate_duration_seconds(locale.story_text)
    locale.updated_at = datetime.now(UTC)

    session.add(locale)
    session.commit()

    print("Saved Music Docuseries MP3.")
    print(f"Bucket: {bucket}")
    print(f"Key:    {key}")
    print(f"Estimated duration: {locale.duration_seconds} seconds")
    print()

    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", default=None, help="Music Docuseries slug")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--language", default="en")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()

    if not args.slug and not args.all:
        raise SystemExit('Use --slug "british_invasion" or --all')

    if args.slug and args.all:
        raise SystemExit("Use either --slug or --all, not both")

    language = normalize_language(args.language)

    if language not in TTS_PROFILES:
        raise SystemExit(f"Unsupported language: {language}")

    if "artist_story" not in TTS_PROFILES[language]:
        raise SystemExit(f"No artist_story TTS profile configured for {language}")

    bucket = BUCKET_BY_LANG.get(language)
    if not bucket:
        raise SystemExit(f"No storage bucket configured for language: {language}")

    profile = TTS_PROFILES[language]["artist_story"]
    voice_id = profile["voice_id"]
    settings = profile.get("settings")
    model_id = MODEL_BY_LANG.get(language)

    generated = 0
    skipped = 0

    with Session(engine) as session:
        if args.all:
            rows = session.exec(
                select(MusicDocuseriesLocale, MusicDocuseries)
                .join(MusicDocuseries, MusicDocuseries.id == MusicDocuseriesLocale.docuseries_id)
                .where(MusicDocuseriesLocale.language_code == language)
                .order_by(MusicDocuseriesLocale.id)
            ).all()

            if not rows:
                raise SystemExit(f"No music docuseries stories found for language={language}")

            for locale, item in rows:
                did_generate = generate_one(
                    session=session,
                    item=item,
                    locale=locale,
                    language=language,
                    bucket=bucket,
                    voice_id=voice_id,
                    settings=settings,
                    model_id=model_id,
                    overwrite=args.overwrite,
                    play=args.play,
                )

                if did_generate:
                    generated += 1
                else:
                    skipped += 1

            print("=" * 80)
            print("Done.")
            print(f"Generated: {generated}")
            print(f"Skipped:   {skipped}")
            return

        item = session.exec(
            select(MusicDocuseries).where(MusicDocuseries.slug == args.slug)
        ).first()

        if not item:
            raise SystemExit(f"Music Docuseries item not found: {args.slug}")

        locale = session.exec(
            select(MusicDocuseriesLocale)
            .where(MusicDocuseriesLocale.docuseries_id == item.id)
            .where(MusicDocuseriesLocale.language_code == language)
        ).first()

        if not locale:
            raise SystemExit(
                f"Music Docuseries story not found: slug={item.slug}, language={language}"
            )

        did_generate = generate_one(
            session=session,
            item=item,
            locale=locale,
            language=language,
            bucket=bucket,
            voice_id=voice_id,
            settings=settings,
            model_id=model_id,
            overwrite=args.overwrite,
            play=args.play,
        )

        print("=" * 80)
        print("Done.")
        print(f"Generated: {1 if did_generate else 0}")
        print(f"Skipped:   {0 if did_generate else 1}")


if __name__ == "__main__":
    main()