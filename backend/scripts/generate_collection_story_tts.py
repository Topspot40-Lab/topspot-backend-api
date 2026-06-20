from __future__ import annotations

import argparse
import tempfile
from datetime import datetime, UTC
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Collection, CollectionStory
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
    story: CollectionStory,
    collection: Collection,
    language: str,
    bucket: str,
    voice_id: str,
    settings: dict | None,
    model_id: str | None,
    overwrite: bool,
    play: bool,
) -> bool:
    if story.tts_key and not overwrite:
        print(f"Skipping existing Collection Story MP3: {collection.slug}")
        print(f"Bucket: {story.tts_bucket}")
        print(f"Key:    {story.tts_key}")
        return False

    key = f"collection-story/{story.id}.mp3"

    print("=" * 80)
    print("Generating Collection Story TTS")
    print(f"Collection: {collection.slug}")
    print(f"Story ID:   {story.id}")
    print(f"Language:   {language}")
    print(f"Voice ID:   {voice_id}")
    print(f"Model:      {model_id}")
    print(f"Bucket:     {bucket}")
    print(f"Key:        {key}")
    print(f"Chars:      {len(story.story_text)}")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / f"collection_story_{story.id}.mp3"

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

        data = out_path.read_bytes()
        upload_bytes(bucket=bucket, key=key, data=data, content_type="audio/mpeg")

    story.tts_bucket = bucket
    story.tts_key = key
    story.duration_seconds = estimate_duration_seconds(story.story_text)
    story.updated_at = datetime.now(UTC)

    session.add(story)
    session.commit()

    print("Saved Collection Story MP3.")
    print(f"Bucket: {bucket}")
    print(f"Key:    {key}")
    print(f"Estimated duration: {story.duration_seconds} seconds")
    print()

    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default=None, help="Collection slug")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--language", default="en")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()

    if not args.collection and not args.all:
        raise SystemExit('Use --collection "slug" or --all')

    if args.collection and args.all:
        raise SystemExit("Use either --collection or --all, not both")

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
            stories = session.exec(
                select(CollectionStory)
                .where(CollectionStory.language_code == language)
                .order_by(CollectionStory.id)
            ).all()

            if not stories:
                raise SystemExit(f"No collection stories found for language={language}")

            for story in stories:
                collection = session.get(Collection, story.collection_id)

                if not collection:
                    print(f"Skipping story {story.id}: collection not found")
                    skipped += 1
                    continue

                did_generate = generate_one(
                    session=session,
                    story=story,
                    collection=collection,
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

        collection = session.exec(
            select(Collection).where(Collection.slug == args.collection)
        ).first()

        if not collection:
            raise SystemExit(f"Collection not found: {args.collection}")

        story = session.exec(
            select(CollectionStory)
            .where(CollectionStory.collection_id == collection.id)
            .where(CollectionStory.language_code == language)
        ).first()

        if not story:
            raise SystemExit(
                f"Collection story not found: collection={collection.slug}, language={language}"
            )

        did_generate = generate_one(
            session=session,
            story=story,
            collection=collection,
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