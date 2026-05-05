from __future__ import annotations

import random


BED_BUCKET = "audio-en"


def get_genre_bed_key(genre: str | None) -> str:
    genre_slug = (genre or "").strip().lower()

    if not genre_slug:
        genre_slug = "default"

    choices = [
        f"bed-tracks/genres/{genre_slug}/bed_{i:02d}.mp3"
        for i in range(1, 6)
    ]

    return random.choice(choices)


def get_collection_group_bed_key(collection_group_slug: str | None) -> str:
    collection_slug = (collection_group_slug or "").strip().lower()

    if not collection_slug:
        collection_slug = "default"

    choices = [
        f"bed-tracks/collection-groups/{collection_slug}/bed_{i:02d}.mp3"
        for i in range(1, 6)
    ]

    return random.choice(choices)