from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from backend.services.supabase_storage import (
    object_exists,
    upload_bytes,
)
from backend.studio.historical_assets import (
    artist_letter,
)


HISTORICAL_IMAGES_BUCKET = "historical-images"


def artist_photo_storage_key(
    *,
    artist_slug: str,
    filename: str,
) -> str:
    letter = artist_letter(artist_slug)

    return (
        f"artists/{letter}/{artist_slug}/"
        f"photos/{filename}"
    )


def upload_artist_photo(
    *,
    artist_slug: str,
    photo_path: Path,
) -> dict[str, Any]:
    if not photo_path.exists():
        raise FileNotFoundError(
            f"Historical photo not found: {photo_path}"
        )

    content_type = (
        mimetypes.guess_type(photo_path.name)[0]
        or "application/octet-stream"
    )

    storage_key = artist_photo_storage_key(
        artist_slug=artist_slug,
        filename=photo_path.name,
    )
    content = photo_path.read_bytes()

    upload_bytes(
        HISTORICAL_IMAGES_BUCKET,
        storage_key,
        content,
        content_type,
    )

    if not object_exists(
        HISTORICAL_IMAGES_BUCKET,
        storage_key,
    ):
        raise RuntimeError(
            "Historical photo upload could not be verified: "
            f"{storage_key}"
        )

    return {
        "storage_bucket": HISTORICAL_IMAGES_BUCKET,
        "storage_key": storage_key,
        "storage_bytes": len(content),
        "storage_content_type": content_type,
    }