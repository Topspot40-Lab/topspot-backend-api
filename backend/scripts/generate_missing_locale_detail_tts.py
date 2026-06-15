import asyncio
import tempfile
from pathlib import Path

from sqlmodel import Session, select
from supabase import create_client

from backend.database import engine
from backend.models.dbmodels import Track, TrackLocale
from backend.config import (
    BUCKETS,
    AUDIO_PREFIXES,
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
)
from backend.services.tts.elevenlabs_tts import generate_tts_mp3
from backend.services.supabase_storage import upload_bytes
from backend.config.tts_config import TTS_PROFILES

LANGUAGES = ("es", "pt-BR")
KIND = "detail"

LIMIT_PER_LANGUAGE = None
OVERWRITE = False


def bucket_for(language: str) -> str:
    return BUCKETS[language][KIND]


def key_for(spotify_track_id: str) -> str:
    return f"{AUDIO_PREFIXES[KIND]}/{spotify_track_id}.mp3"


def filename_for(spotify_track_id: str) -> str:
    return f"{spotify_track_id}.mp3"


async def generate_for_language(language: str) -> None:
    bucket = bucket_for(language)
    voice_id = TTS_PROFILES[language][KIND]["voice_id"]

    generated = 0
    skipped_existing_db = 0
    skipped_existing_storage = 0
    skipped_missing_data = 0

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    print()
    print("=" * 80)
    print(f"Language: {language}")
    print(f"Bucket: {bucket}")
    print("=" * 80)

    print("Loading existing detail MP3 list from Supabase...")

    existing_files: set[str] = set()
    page_size = 1000
    offset = 0
    prefix = AUDIO_PREFIXES[KIND]

    while True:
        result = supabase.storage.from_(bucket).list(
            path=prefix,
            options={"limit": page_size, "offset": offset},
        )

        if not result:
            break

        for item in result:
            name = item.get("name")
            if name:
                existing_files.add(name)

        if len(result) < page_size:
            break

        offset += page_size

    print(f"Found {len(existing_files)} existing detail MP3 files")

    with Session(engine) as session:
        rows = session.exec(
            select(TrackLocale, Track)
            .join(Track, Track.id == TrackLocale.track_id)
            .where(TrackLocale.language_code == language)
            .where(TrackLocale.detail_text != None)
            .where(Track.spotify_track_id != None)
            .order_by(TrackLocale.track_id)
        ).all()

        print(f"Found {len(rows)} locale rows with detail text")

        for locale, track in rows:
            spotify_id = track.spotify_track_id
            text = (locale.detail_text or "").strip()

            if not spotify_id or not text:
                skipped_missing_data += 1
                continue

            filename = filename_for(spotify_id)
            key = key_for(spotify_id)

            if not OVERWRITE and locale.tts_key:
                skipped_existing_db += 1
                continue

            if not OVERWRITE and filename in existing_files:
                locale.tts_bucket = bucket
                locale.tts_key = key
                session.add(locale)
                session.commit()
                skipped_existing_storage += 1
                continue

            print(f"Generating {language} detail: {track.track_name} — {spotify_id}")

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                generate_tts_mp3(
                    text=text,
                    out_path=tmp_path,
                    voice_id=voice_id,
                    overwrite=True,
                    play=False,
                )

                upload_bytes(
                    bucket,
                    key,
                    tmp_path.read_bytes(),
                    "audio/mpeg",
                )

                locale.tts_bucket = bucket
                locale.tts_key = key
                session.add(locale)
                session.commit()

                generated += 1
                existing_files.add(filename)

                print(f"Uploaded: {bucket}/{key}")

                if LIMIT_PER_LANGUAGE is not None and generated >= LIMIT_PER_LANGUAGE:
                    break

            finally:
                tmp_path.unlink(missing_ok=True)

    print()
    print(f"Done: {language}")
    print(f"Generated: {generated}")
    print(f"Skipped existing in DB: {skipped_existing_db}")
    print(f"Found existing in storage and updated DB: {skipped_existing_storage}")
    print(f"Skipped missing data: {skipped_missing_data}")


async def main() -> None:
    for language in LANGUAGES:
        await generate_for_language(language)


if __name__ == "__main__":
    asyncio.run(main())