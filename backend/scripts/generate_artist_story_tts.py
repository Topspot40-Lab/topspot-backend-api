from __future__ import annotations

import argparse
import tempfile
from datetime import datetime, UTC
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Artist, ArtistStory
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
    story: ArtistStory,
    artist: Artist,
    language: str,
    overwrite: bool,
    play: bool,
) -> bool:
    bucket = BUCKET_BY_LANG[language]
    profile = TTS_PROFILES[language]["artist_story"]

    voice_id = profile["voice_id"]
    settings = profile.get("settings")
    model_id = MODEL_BY_LANG.get(language)

    if story.tts_key and not overwrite:
        print(f"Skipping existing: {artist.artist_name} -> {story.tts_key}")
        return False

    key = f"artist-story/{story.id}.mp3"

    print("=" * 80)
    print("Generating Artist Story TTS")
    print(f"Artist:   {artist.artist_name}")
    print(f"Story ID: {story.id}")
    print(f"Language: {language}")
    print(f"Voice ID: {voice_id}")
    print(f"Model:    {model_id}")
    print(f"Bucket:   {bucket}")
    print(f"Key:      {key}")
    print(f"Chars:    {len(story.story_text)}")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / f"artist_story_{story.id}.mp3"

        generate_tts_mp3(
            text=story.story_text,
            out_path=out_path,
            voice_id=voice_id,
            overwrite=True,
            play=play,
            settings=settings,
            model_id=model_id,
            language=language,
            timeout=(10.0, 300.0),
        )

        upload_bytes(
            bucket=bucket,
            key=key,
            data=out_path.read_bytes(),
            content_type="audio/mpeg",
        )

    story.tts_bucket = bucket
    story.tts_key = key
    story.duration_seconds = estimate_duration_seconds(story.story_text)
    story.updated_at = datetime.now(UTC)

    session.add(story)
    session.commit()

    print("Saved Artist Story MP3.")
    print(f"Bucket: {bucket}")
    print(f"Key:    {key}")
    print(f"Estimated duration: {story.duration_seconds} seconds")
    print()

    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artist", default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--language", default="en")
    parser.add_argument("--story-type", default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()

    language = normalize_language(args.language)

    if not args.all and not args.artist:
        raise SystemExit('Use --artist "name" or --all')

    if args.all and args.artist:
        raise SystemExit("Use either --artist or --all, not both")

    if language not in TTS_PROFILES:
        raise SystemExit(f"Unsupported language: {language}")

    if "artist_story" not in TTS_PROFILES[language]:
        raise SystemExit(f"No artist_story TTS profile configured for {language}")

    if language not in BUCKET_BY_LANG:
        raise SystemExit(f"No storage bucket configured for language: {language}")

    generated = 0
    skipped = 0

    with Session(engine) as session:
        if args.all:
            query = (
                select(ArtistStory, Artist)
                .join(Artist, Artist.id == ArtistStory.artist_id)
                .where(ArtistStory.language_code == language)
                .order_by(Artist.artist_name)
            )

            if not args.overwrite:
                query = query.where(ArtistStory.tts_key.is_(None))

            if args.story_type:
                query = query.where(ArtistStory.story_type == args.story_type)

            rows = session.exec(query).all()

            print("Artist Story TTS batch")
            print(f"Language:  {language}")
            print(f"Overwrite: {args.overwrite}")
            print(f"Rows:      {len(rows)}")
            print()

            for story, artist in rows:
                did_generate = generate_one(
                    session=session,
                    story=story,
                    artist=artist,
                    language=language,
                    overwrite=args.overwrite,
                    play=args.play,
                )

                if did_generate:
                    generated += 1
                else:
                    skipped += 1

        else:
            artist = session.exec(
                select(Artist).where(Artist.artist_name.ilike(args.artist))
            ).first()

            if not artist:
                raise SystemExit(f"Artist not found: {args.artist}")

            query = select(ArtistStory).where(
                ArtistStory.artist_id == artist.id,
                ArtistStory.language_code == language,
            )

            if args.story_type:
                query = query.where(ArtistStory.story_type == args.story_type)

            story = session.exec(query).first()

            if not story:
                raise SystemExit(
                    f"Artist story not found: artist={artist.artist_name}, language={language}"
                )

            did_generate = generate_one(
                session=session,
                story=story,
                artist=artist,
                language=language,
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


if __name__ == "__main__":
    main()
