from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_LANGUAGES = frozenset({"en", "es", "pt-BR"})
PRIVACY_VALUES = frozenset({"private", "unlisted", "public"})
YOUTUBE_TITLE_LIMIT = 100
YOUTUBE_THUMBNAIL_SIZE_LIMIT = 2_097_152
THUMBNAIL_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})
REQUIRED_FIELDS = (
    "slug",
    "language_code",
    "video_path",
    "thumbnail_path",
    "title",
    "description",
    "tags",
    "category_id",
    "made_for_kids",
)


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class UploadManifestEntry:
    slug: str
    language_code: str
    video_path: Path
    thumbnail_path: Path
    title: str
    description: str
    tags: tuple[str, ...]
    category_id: str
    made_for_kids: bool
    privacy_status: str = "private"
    artist: str | None = None


def load_manifest(path: str | Path) -> list[UploadManifestEntry]:
    manifest_path = Path(path).expanduser().resolve()
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"Manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Invalid JSON in {manifest_path}: {exc}") from exc

    records = document.get("uploads") if isinstance(document, dict) else document
    if not isinstance(records, list):
        raise ManifestError("Manifest must be a JSON list or contain an uploads list")

    entries: list[UploadManifestEntry] = []
    seen: set[tuple[str, str]] = set()
    for index, record in enumerate(records, start=1):
        entry = _parse_entry(record, index, manifest_path.parent)
        key = (entry.slug, entry.language_code)
        if key in seen:
            raise ManifestError(
                "Duplicate slug/language pair: "
                f"{entry.slug}/{entry.language_code}"
            )
        seen.add(key)
        entries.append(entry)

    return entries


def _parse_entry(
    record: Any,
    index: int,
    manifest_dir: Path,
) -> UploadManifestEntry:
    prefix = f"Entry {index}"
    if not isinstance(record, dict):
        raise ManifestError(f"{prefix} must be a JSON object")

    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        fields = ", ".join(missing)
        raise ManifestError(f"{prefix} is missing required fields: {fields}")

    slug = _required_string(record, "slug", prefix)
    language = _required_string(record, "language_code", prefix)
    if language not in SUPPORTED_LANGUAGES:
        raise ManifestError(f"{prefix} has unsupported language: {language}")

    title = _required_string(record, "title", prefix)
    if len(title) > YOUTUBE_TITLE_LIMIT:
        raise ManifestError(
            f"{prefix} title exceeds YouTube's "
            f"{YOUTUBE_TITLE_LIMIT}-character limit"
        )

    description = _required_string(record, "description", prefix)
    category_id = _required_string(record, "category_id", prefix)
    tags_value = record["tags"]
    if not isinstance(tags_value, list) or not all(
        isinstance(tag, str) and tag.strip() for tag in tags_value
    ):
        raise ManifestError(f"{prefix} tags must be a list of non-empty strings")

    made_for_kids = record["made_for_kids"]
    if not isinstance(made_for_kids, bool):
        raise ManifestError(f"{prefix} made_for_kids must be a boolean")

    privacy = record.get("privacy_status", record.get("privacy", "private"))
    if not isinstance(privacy, str) or privacy not in PRIVACY_VALUES:
        raise ManifestError(f"{prefix} has invalid privacy value: {privacy}")

    raw_video_path = Path(str(record["video_path"])).expanduser()
    if _is_forbidden_video(raw_video_path):
        raise ManifestError(
            f"{prefix} uses forbidden video file: {raw_video_path.name}"
        )
    if raw_video_path.suffix.lower() != ".mp4":
        raise ManifestError(f"{prefix} video must be an MP4 file")
    video_path = _resolve_file(record["video_path"], manifest_dir, prefix)
    if _is_forbidden_video(video_path):
        raise ManifestError(f"{prefix} uses forbidden video file: {video_path.name}")
    if video_path.suffix.lower() != ".mp4":
        raise ManifestError(f"{prefix} video must be an MP4 file")
    if video_path.stat().st_size == 0:
        raise ManifestError(f"{prefix} video file must not be empty")

    raw_thumbnail_path = Path(str(record["thumbnail_path"])).expanduser()
    if raw_thumbnail_path.suffix.lower() not in THUMBNAIL_EXTENSIONS:
        raise ManifestError(f"{prefix} thumbnail must be PNG, JPG, or JPEG")
    thumbnail_path = _resolve_file(
        record["thumbnail_path"],
        manifest_dir,
        prefix,
    )
    if thumbnail_path.suffix.lower() not in THUMBNAIL_EXTENSIONS:
        raise ManifestError(f"{prefix} thumbnail must be PNG, JPG, or JPEG")
    if thumbnail_path.stat().st_size > YOUTUBE_THUMBNAIL_SIZE_LIMIT:
        raise ManifestError(
            f"{prefix} thumbnail exceeds the "
            f"{YOUTUBE_THUMBNAIL_SIZE_LIMIT}-byte limit"
        )

    artist_value = record.get("artist")
    if artist_value is not None and (
        not isinstance(artist_value, str) or not artist_value.strip()
    ):
        raise ManifestError(f"{prefix} artist must be a non-empty string")

    return UploadManifestEntry(
        slug=slug,
        language_code=language,
        video_path=video_path,
        thumbnail_path=thumbnail_path,
        title=title,
        description=description,
        tags=tuple(tag.strip() for tag in tags_value),
        category_id=category_id,
        made_for_kids=made_for_kids,
        privacy_status=privacy,
        artist=artist_value.strip() if artist_value else None,
    )


def _required_string(record: dict[str, Any], field: str, prefix: str) -> str:
    value = record[field]
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{prefix} {field} must be a non-empty string")
    return value.strip()


def _resolve_file(value: Any, manifest_dir: Path, prefix: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{prefix} file paths must be non-empty strings")

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = manifest_dir / path
    path = path.resolve()
    if not path.is_file():
        raise ManifestError(f"{prefix} file not found: {path}")
    return path


def _is_forbidden_video(path: Path) -> bool:
    name = path.name.lower()
    return name in {"image_sequence.mp4", "opening.mp4"} or name.endswith(
        "_review.mp4"
    )
