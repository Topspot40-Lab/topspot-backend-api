"""Validated input contract for explicit YouTube publishing runs."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


LANGUAGES = frozenset({"en", "es", "pt-BR"})
PLAYLIST_PRIVACY = frozenset({"public", "private", "unlisted"})
THUMBNAIL_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})
THUMBNAIL_LIMIT = 2_097_152


class ManifestError(ValueError):
    """The batch cannot be published safely."""


@dataclass(frozen=True, slots=True)
class PlaylistSpec:
    key: str
    title: str
    description: str
    privacy_status: str = "public"
    existing_playlist_id: str | None = None


@dataclass(frozen=True, slots=True)
class UploadSpec:
    slug: str
    collection_key: str
    language_code: str
    video_path: Path
    thumbnail_path: Path
    captions_path: Path | None
    title: str
    description: str
    tags: tuple[str, ...]
    scheduled_publish_at: datetime
    playlist_keys: tuple[str, ...]
    visual_approval: str
    approved_video_sha256: str
    category_id: str = "10"
    made_for_kids: bool = False
    contains_synthetic_media: bool = True
    notify_subscribers: bool = True
    end_screen_required: bool = True


@dataclass(frozen=True, slots=True)
class UploadManifest:
    playlists: tuple[PlaylistSpec, ...]
    uploads: tuple[UploadSpec, ...]


def load_manifest(path: str | Path) -> UploadManifest:
    manifest_path = Path(path).expanduser().resolve()
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"Manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Invalid manifest JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError("Manifest must be a JSON object")

    playlist_values = value.get("playlists")
    upload_values = value.get("uploads")
    if not isinstance(playlist_values, list) or not isinstance(upload_values, list):
        raise ManifestError("Manifest requires playlists and uploads lists")

    playlists = tuple(_playlist(item, index) for index, item in enumerate(playlist_values, 1))
    keys = [item.key for item in playlists]
    if len(set(keys)) != len(keys):
        raise ManifestError("Playlist keys must be unique")
    uploads = tuple(
        _upload(item, index, manifest_path.parent, frozenset(keys))
        for index, item in enumerate(upload_values, 1)
    )
    identities = [(item.slug, item.language_code) for item in uploads]
    if len(set(identities)) != len(identities):
        raise ManifestError("Slug/language pairs must be unique")
    return UploadManifest(playlists=playlists, uploads=uploads)


def _playlist(value: Any, index: int) -> PlaylistSpec:
    prefix = f"Playlist {index}"
    if not isinstance(value, dict):
        raise ManifestError(f"{prefix} must be an object")
    privacy = value.get("privacy_status", "public")
    if privacy not in PLAYLIST_PRIVACY:
        raise ManifestError(f"{prefix} has invalid privacy_status")
    existing = value.get("existing_playlist_id")
    if existing is not None and not _text(existing):
        raise ManifestError(f"{prefix} existing_playlist_id must be non-empty")
    return PlaylistSpec(
        key=_required(value, "key", prefix),
        title=_required(value, "title", prefix),
        description=_required(value, "description", prefix),
        privacy_status=privacy,
        existing_playlist_id=existing.strip() if existing else None,
    )


def _upload(value: Any, index: int, base: Path, playlist_keys: frozenset[str]) -> UploadSpec:
    prefix = f"Upload {index}"
    if not isinstance(value, dict):
        raise ManifestError(f"{prefix} must be an object")
    language = _required(value, "language_code", prefix)
    if language not in LANGUAGES:
        raise ManifestError(f"{prefix} has unsupported language {language!r}")
    title = _required(value, "title", prefix)
    if len(title) > 100:
        raise ManifestError(f"{prefix} title exceeds 100 characters")
    tags = value.get("tags")
    if not isinstance(tags, list) or not tags or not all(_text(tag) for tag in tags):
        raise ManifestError(f"{prefix} tags must be non-empty strings")
    requested_playlists = value.get("playlist_keys")
    if not isinstance(requested_playlists, list) or not requested_playlists:
        raise ManifestError(f"{prefix} requires playlist_keys")
    unknown = sorted(set(requested_playlists) - playlist_keys)
    if unknown:
        raise ManifestError(f"{prefix} references unknown playlists: {', '.join(unknown)}")
    try:
        publish_at = datetime.fromisoformat(_required(value, "scheduled_publish_at", prefix))
    except ValueError as exc:
        raise ManifestError(f"{prefix} has invalid scheduled_publish_at") from exc
    if publish_at.tzinfo is None or publish_at.utcoffset() is None:
        raise ManifestError(f"{prefix} scheduled_publish_at must include an offset")

    video = _file(value.get("video_path"), base, prefix, {".mp4"})
    approval = _required(value, "visual_approval", prefix)
    approved_digest = _required(value, "approved_video_sha256", prefix).lower()
    if len(approved_digest) != 64 or any(character not in "0123456789abcdef" for character in approved_digest):
        raise ManifestError(f"{prefix} approved_video_sha256 must be a SHA-256 digest")
    if _sha256(video) != approved_digest:
        raise ManifestError(f"{prefix} video changed after visual approval: {video}")
    thumbnail = _file(value.get("thumbnail_path"), base, prefix, THUMBNAIL_SUFFIXES)
    if thumbnail.stat().st_size > THUMBNAIL_LIMIT:
        raise ManifestError(f"{prefix} thumbnail exceeds 2 MiB")
    captions_value = value.get("captions_path")
    captions = None if captions_value is None else _file(captions_value, base, prefix, {".vtt", ".srt"})
    return UploadSpec(
        slug=_required(value, "slug", prefix),
        collection_key=_required(value, "collection_key", prefix),
        language_code=language,
        video_path=video,
        thumbnail_path=thumbnail,
        captions_path=captions,
        title=title,
        description=_required(value, "description", prefix),
        tags=tuple(tag.strip() for tag in tags),
        scheduled_publish_at=publish_at,
        playlist_keys=tuple(requested_playlists),
        visual_approval=approval,
        approved_video_sha256=approved_digest,
        category_id=str(value.get("category_id", "10")),
        made_for_kids=_required_bool(value, "made_for_kids", False, prefix),
        contains_synthetic_media=_required_bool(value, "contains_synthetic_media", True, prefix),
        notify_subscribers=_required_bool(value, "notify_subscribers", True, prefix),
        end_screen_required=_required_bool(value, "end_screen_required", True, prefix),
    )


def _file(value: Any, base: Path, prefix: str, suffixes: frozenset[str] | set[str]) -> Path:
    if not _text(value):
        raise ManifestError(f"{prefix} has an invalid file path")
    path = Path(value).expanduser()
    path = (base / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise ManifestError(f"{prefix} file is missing or empty: {path}")
    if path.suffix.lower() not in suffixes:
        raise ManifestError(f"{prefix} has unsupported file type: {path.name}")
    return path


def _required(value: dict[str, Any], key: str, prefix: str) -> str:
    item = value.get(key)
    if not _text(item):
        raise ManifestError(f"{prefix} requires {key}")
    return item.strip()


def _required_bool(value: dict[str, Any], key: str, default: bool, prefix: str) -> bool:
    item = value.get(key, default)
    if not isinstance(item, bool):
        raise ManifestError(f"{prefix} {key} must be boolean")
    return item


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
