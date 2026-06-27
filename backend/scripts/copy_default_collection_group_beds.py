from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load the project's .env file
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from backend.services.supabase_storage import supabase

BUCKET = "audio-en"
SOURCE_GROUP = "default"

TARGET_GROUPS = [
    "american_heritage_favorites",
    "traditional_favorites",
    "world_heritage_favorites",
]

BED_FILES = [
    "bed_01.mp3",
    "bed_02.mp3",
    "bed_03.mp3",
    "bed_04.mp3",
    "bed_05.mp3",
]


def main() -> None:
    bucket = supabase.storage.from_(BUCKET)

    for group in TARGET_GROUPS:
        print(f"\n📁 Creating/filling group: {group}")

        for filename in BED_FILES:
            src = f"bed-tracks/collection-groups/{SOURCE_GROUP}/{filename}"
            dst = f"bed-tracks/collection-groups/{group}/{filename}"

            print(f"  Copying {src} -> {dst}")

            data = bucket.download(src)

            bucket.upload(
                dst,
                data,
                {
                    "content-type": "audio/mpeg",
                    "upsert": "true",
                },
            )

    print("\n✅ Done.")


if __name__ == "__main__":
    main()
