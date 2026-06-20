import asyncio
import tempfile
from pathlib import Path

from sqlmodel import Session, select
from supabase import create_client

from backend.database import engine
from backend.models.dbmodels import Track
from backend.config import (
    BUCKETS,
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
)
from backend.services.tts.elevenlabs_tts import generate_tts_mp3
from backend.services.supabase_storage import upload_bytes
from backend.config.tts_config import TTS_PROFILES

LANGUAGE = "en"
KIND = "detail"

LIMIT = None          # start small for testing
OVERWRITE = False

VOICE_ID = TTS_PROFILES[LANGUAGE][KIND]["voice_id"]
SHORT_DETAIL_PREFIX = "short-detail"


def bucket_for_short_detail() -> str:
    return BUCKETS[LANGUAGE][KIND]


def short_detail_key(spotify_track_id: str) -> str:
    return f"{SHORT_DETAIL_PREFIX}/{spotify_track_id}.mp3"


def filename_for(spotify_track_id: str) -> str:
    return f"{spotify_track_id}.mp3"


async def main() -> None:
    bucket = bucket_for_short_detail()

    generated = 0
    skipped_existing_storage = 0
    skipped_existing_db = 0
    skipped_missing_data = 0

    supabase = create_client(
        SUPABASE_URL,
        SUPABASE_SERVICE_ROLE_KEY,
    )

    print("Loading existing short-detail MP3 list from Supabase...")

    existing_files: set[str] = set()
    page_size = 1000
    offset = 0

    while True:
        result = supabase.storage.from_(bucket).list(
            path=SHORT_DETAIL_PREFIX,
            options={
                "limit": page_size,
                "offset": offset,
            },
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

    print(f"Found {len(existing_files)} existing short-detail MP3 files")

    with Session(engine) as session:
        tracks = session.exec(
            select(Track)
            .where(Track.short_detail != None)
            .where(Track.spotify_track_id != None)
            .order_by(Track.id)
        ).all()

        print(f"Found {len(tracks)} tracks with English short-detail text")

        for track in tracks:
            spotify_id = track.spotify_track_id
            detail_text = (track.short_detail or "").strip()

            if not spotify_id or not detail_text:
                skipped_missing_data += 1
                continue

            filename = filename_for(spotify_id)
            key = short_detail_key(spotify_id)

            if not OVERWRITE and track.short_detail_tts_key:
                skipped_existing_db += 1
                continue

            if not OVERWRITE and filename in existing_files:
                track.short_detail_tts_key = key
                session.add(track)
                session.commit()
                skipped_existing_storage += 1
                continue

            print(f"Generating short detail: {track.track_name} — {spotify_id}")

            with tempfile.NamedTemporaryFile(
                suffix=".mp3",
                delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)

            try:
                generate_tts_mp3(
                    text=detail_text,
                    out_path=tmp_path,
                    voice_id=VOICE_ID,
                    overwrite=True,
                    play=False,
                )

                upload_bytes(
                    bucket,
                    key,
                    tmp_path.read_bytes(),
                    "audio/mpeg",
                )

                track.short_detail_tts_key = key
                session.add(track)
                session.commit()

                generated += 1
                existing_files.add(filename)

                print(f"Uploaded: {bucket}/{key}")

                if LIMIT is not None and generated >= LIMIT:
                    break

            finally:
                tmp_path.unlink(missing_ok=True)

    print()
    print("Done.")
    print(f"Generated: {generated}")
    print(f"Skipped existing in DB: {skipped_existing_db}")
    print(f"Found existing in storage and updated DB: {skipped_existing_storage}")
    print(f"Skipped missing data: {skipped_missing_data}")


if __name__ == "__main__":
    asyncio.run(main())
