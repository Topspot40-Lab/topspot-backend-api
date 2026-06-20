from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from sqlmodel import Session, select
from supabase import create_client

from backend.database import engine
from backend.models.dbmodels import Artist, ArtistLocale
from backend.config import BUCKETS, AUDIO_PREFIXES, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
from backend.config.tts_config import TTS_PROFILES
from backend.services.tts.elevenlabs_tts import generate_tts_mp3
from backend.services.supabase_storage import upload_bytes


def artist_key(spotify_artist_id: str) -> str:
    return f"{AUDIO_PREFIXES['artist']}/{spotify_artist_id}.mp3"


def filename_for(spotify_artist_id: str) -> str:
    return f"{spotify_artist_id}.mp3"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=["en", "es", "pt-BR"], default="en")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    bucket = BUCKETS[args.language]["artist"]
    voice_id = TTS_PROFILES[args.language]["artist"]["voice_id"]

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    existing_files: set[str] = set()
    offset = 0
    page_size = 1000

    while True:
        result = supabase.storage.from_(bucket).list(
            path=AUDIO_PREFIXES["artist"],
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

    generated = 0
    skipped_existing = 0
    skipped_missing_text = 0

    with Session(engine) as session:
        if args.language == "en":
            rows = session.exec(
                select(Artist)
                .where(Artist.artist_description != None)
                .where(Artist.spotify_artist_id != None)
                .order_by(Artist.id)
            ).all()

            items = [
                (
                    artist.id,
                    artist.artist_name,
                    artist.spotify_artist_id,
                    artist.artist_description,
                )
                for artist in rows
            ]
        else:
            rows = session.exec(
                select(ArtistLocale, Artist)
                .join(Artist, Artist.id == ArtistLocale.artist_id)
                .where(ArtistLocale.language_code == args.language)
                .where(ArtistLocale.artist_description_text != None)
                .where(Artist.spotify_artist_id != None)
                .order_by(Artist.id)
            ).all()

            items = [
                (artist.id, artist.artist_name, artist.spotify_artist_id, locale.artist_description_text)
                for locale, artist in rows
            ]

    print("=" * 80)
    print("Generate Missing Artist TTS")
    print(f"Language: {args.language}")
    print(f"Bucket:   {bucket}")
    print(f"Voice:    {voice_id}")
    print(f"Rows:     {len(items)}")
    print(f"Limit:    {args.limit}")
    print(f"Overwrite:{args.overwrite}")
    print(f"Existing: {len(existing_files)}")
    print("=" * 80)

    for artist_id, artist_name, spotify_artist_id, text in items:
        if not spotify_artist_id or not text:
            skipped_missing_text += 1
            continue

        filename = filename_for(spotify_artist_id)

        if not args.overwrite and filename in existing_files:
            skipped_existing += 1
            continue

        key = artist_key(spotify_artist_id)

        print(f"Generating: {artist_id} | {artist_name} | {spotify_artist_id}")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            generate_tts_mp3(
                text=text.strip(),
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

            generated += 1
            print(f"Uploaded: {bucket}/{key}")

            if args.limit is not None and generated >= args.limit:
                break

        finally:
            tmp_path.unlink(missing_ok=True)

    print("=" * 80)
    print(f"Generated:            {generated}")
    print(f"Skipped existing:     {skipped_existing}")
    print(f"Skipped missing text: {skipped_missing_text}")
    print("=" * 80)


if __name__ == "__main__":
    main()
