import asyncio
import tempfile
from pathlib import Path

from sqlmodel import Session, select
from supabase import create_client

from backend.database import engine
from backend.models.dbmodels import Track
from backend.config import (
    BUCKETS,
    AUDIO_PREFIXES,
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
)
from backend.services.tts.elevenlabs_tts import generate_tts_mp3
from backend.services.supabase_storage import upload_bytes
from backend.config.tts_config import TTS_PROFILES

LANGUAGE = "en"
KIND = "detail"

LIMIT = None          # use 5 for testing
OVERWRITE = False     # keep False to avoid wasting credits

VOICE_ID = TTS_PROFILES[LANGUAGE][KIND]["voice_id"]


def bucket_for_detail() -> str:
    return BUCKETS[LANGUAGE][KIND]


def detail_key(spotify_track_id: str) -> str:
    return f"{AUDIO_PREFIXES[KIND]}/{spotify_track_id}.mp3"


def filename_for(spotify_track_id: str) -> str:
    return f"{spotify_track_id}.mp3"


async def main() -> None:
    bucket = bucket_for_detail()

    generated = 0
    skipped_existing = 0
    skipped_missing_data = 0

    # ------------------------------------------------------------
    # Connect to Supabase
    # ------------------------------------------------------------
    supabase = create_client(
        SUPABASE_URL,
        SUPABASE_SERVICE_ROLE_KEY,
    )

    # ------------------------------------------------------------
    # Load existing filenames from bucket
    # ------------------------------------------------------------
    print("Loading existing MP3 list from Supabase...")

    existing_files: set[str] = set()

    page_size = 1000
    offset = 0

    while True:
        result = supabase.storage.from_(bucket).list(
            path=AUDIO_PREFIXES[KIND],
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

    print(f"Found {len(existing_files)} existing MP3 files")

    # ------------------------------------------------------------
    # Load tracks
    # ------------------------------------------------------------
    with Session(engine) as session:
        tracks = session.exec(
            select(Track)
            .where(Track.detail != None)
            .where(Track.spotify_track_id != None)
            .order_by(Track.id)
        ).all()

    print(f"Found {len(tracks)} tracks with detail text")

    # ------------------------------------------------------------
    # Generate only missing MP3s
    # ------------------------------------------------------------
    for track in tracks:
        spotify_id = track.spotify_track_id
        detail_text = (track.detail or "").strip()

        if not spotify_id or not detail_text:
            skipped_missing_data += 1
            continue

        filename = filename_for(spotify_id)

        # 🔥 skip existing
        if not OVERWRITE and filename in existing_files:
            skipped_existing += 1
            continue

        key = detail_key(spotify_id)

        print(f"Generating: {track.track_name} — {spotify_id}")

        with tempfile.NamedTemporaryFile(
            suffix=".mp3",
            delete=False
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

            generated += 1

            print(f"Uploaded: {bucket}/{key}")

            if LIMIT is not None and generated >= LIMIT:
                break

        finally:
            tmp_path.unlink(missing_ok=True)

    print()
    print("Done.")
    print(f"Generated: {generated}")
    print(f"Skipped existing: {skipped_existing}")
    print(f"Skipped missing data: {skipped_missing_data}")


if __name__ == "__main__":
    asyncio.run(main())