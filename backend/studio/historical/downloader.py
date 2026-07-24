from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from backend.studio.historical.models import (
    HistoricalImageCandidate,
)


USER_AGENT = (
    "TopSpot40-Studio/1.0 "
    "(historical documentary image downloader)"
)


def save_json_atomic(
    path: Path,
    payload: dict[str, Any],
    *,
    attempts: int = 5,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    last_error: OSError | None = None

    for attempt in range(1, attempts + 1):
        try:
            temporary_path.replace(path)
            return
        except PermissionError as exc:
            last_error = exc

            if attempt == attempts:
                break

            time.sleep(0.5 * attempt)

    raise RuntimeError(
        f"Could not replace {path}."
    ) from last_error


def determine_extension(
    candidate: HistoricalImageCandidate,
) -> str:
    if candidate.mime_type == "image/jpeg":
        return ".jpg"

    if candidate.mime_type == "image/png":
        return ".png"

    suffix = Path(
        urlparse(candidate.original_url).path
    ).suffix.lower()

    return suffix or ".img"


def download_candidate(
    candidate: HistoricalImageCandidate,
    destination_directory: Path,
) -> tuple[Path, Path]:
    destination_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    extension = determine_extension(candidate)

    image_path = (
        destination_directory
        / f"candidate{extension}"
    )
    metadata_path = (
        destination_directory
        / "candidate.json"
    )

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
        }
    )

    response = session.get(
        candidate.original_url,
        timeout=(10, 120),
    )
    response.raise_for_status()

    content = response.content

    if not content:
        raise RuntimeError(
            "Historical image download returned no data."
        )

    image_path.write_bytes(content)

    payload = candidate.to_dict()
    payload.update(
        {
            "downloaded_file": image_path.name,
            "downloaded_bytes": len(content),
        }
    )

    save_json_atomic(
        metadata_path,
        payload,
    )

    return image_path, metadata_path
