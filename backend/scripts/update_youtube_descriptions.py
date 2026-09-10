"""Safely prepend localized TopSpot40 links to existing YouTube descriptions.

Preview is the default and operates only on a previously captured snapshot.
Remote reads and metadata writes require separate, explicit modes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from backend.scripts.upload_youtube_release import _is_quota_error


LANGUAGES = frozenset({"en", "es", "pt-BR"})
STATE = Path("backend/studio/work/youtube_release_state.json")
BACKUPS = Path("backend/studio/work/youtube_description_backups")
LEDGER = Path("backend/studio/work/youtube_description_ledger.json")
REMOTE_PARTS = "snippet,status,localizations,recordingDetails"
MAX_OPERATIONAL_BATCH = 50

INTRODUCTIONS = {
    "en": "🎵 Explore TopSpot40 free: {url}\n\nRediscover the music of your life through decades, genres, artists and the stories behind the songs.\n\n",
    "es": "🎵 Explora TopSpot40 gratis: {url}\n\nRedescubre la música de tu vida a través de décadas, géneros, artistas e historias.\n\n",
    "pt-BR": "🎵 Explore o TopSpot40 gratuitamente: {url}\n\nRedescubra a música da sua vida através de décadas, gêneros, artistas e histórias.\n\n",
}
OLD_INTRODUCTIONS = {language: introduction.removeprefix("🎵 ") for language, introduction in INTRODUCTIONS.items()}
ATOMIC_WRITE_REPLACE_ATTEMPTS = 3
ATOMIC_WRITE_RETRY_DELAY_SECONDS = 0.05

# These are operator-approved exceptions to the release-state source.  Keep this
# intentionally small and reviewed: a supplemental mapping is never inferred.
APPROVED_SUPPLEMENTAL_MAPPINGS = (
    {"slug": "adele", "language": "en", "video_id": "khdr3ZoFtCY", "source": "approved_supplemental"},
)


@dataclass(frozen=True)
class VideoBinding:
    slug: str
    language: str
    video_id: str
    source: str


def canonical_url(slug: str, language: str) -> str:
    return "https://topspot40.com/?utm_source=youtube&utm_medium=video&utm_campaign=docuseries&utm_content=" + f"{slug}_{language}"


def desired_description(binding: VideoBinding, description: str) -> tuple[str, bool]:
    """Return (desired, already_has_exact_canonical_marker)."""
    marker = canonical_url(binding.slug, binding.language)
    introduction = INTRODUCTIONS[binding.language].format(url=marker)
    if introduction in description:
        return description, True
    old_introduction = OLD_INTRODUCTIONS[binding.language].format(url=marker)
    if old_introduction in description:
        return description.replace(old_introduction, introduction, 1), False
    return introduction + description, False


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_resource_fingerprint(resource: dict[str, Any]) -> str:
    """Fingerprint operator-meaningful video metadata, excluding API churn.

    YouTube changes the top-level etag and can rotate snippet thumbnail URLs
    without anyone changing the video metadata this workflow protects.
    """
    snippet = resource.get("snippet")
    stable_snippet = (
        {key: value for key, value in snippet.items() if key != "thumbnails"}
        if isinstance(snippet, dict)
        else snippet
    )
    return sha256_json(
        {
            "id": resource.get("id"),
            "snippet": stable_snippet,
            "status": resource.get("status"),
            "localizations": resource.get("localizations"),
            "recordingDetails": resource.get("recordingDetails"),
        }
    )


def _valid_binding(value: Any, source: str) -> VideoBinding:
    if not isinstance(value, dict):
        raise ValueError(f"Invalid {source} mapping")
    slug, language, video_id = value.get("slug"), value.get("language"), value.get("video_id")
    if not isinstance(slug, str) or not slug.strip() or language not in LANGUAGES or not isinstance(video_id, str) or len(video_id.strip()) != 11:
        raise ValueError(f"Invalid {source} mapping")
    return VideoBinding(slug.strip(), language, video_id.strip(), source)


def load_inventory(state_path: Path, supplemental_path: Path | None = None) -> tuple[VideoBinding, ...]:
    """Current uploaded release state is authoritative; supplements are explicit."""
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Release-state file cannot be read") from exc
    uploads = state.get("uploads") if isinstance(state, dict) else None
    if not isinstance(uploads, dict):
        raise ValueError("Release-state file has no uploads mapping")
    bindings: list[VideoBinding] = []
    for key, record in uploads.items():
        if not isinstance(key, str) or not isinstance(record, dict) or record.get("status") != "uploaded":
            continue
        slug, separator, language = key.rpartition("|")
        if not separator:
            raise ValueError("Release-state file has an invalid upload identity")
        bindings.append(_valid_binding({"slug": slug, "language": language, "video_id": record.get("video_id")}, "release-state"))
    extras: list[Any] = list(APPROVED_SUPPLEMENTAL_MAPPINGS)
    if supplemental_path is not None:
        try:
            supplied = json.loads(supplemental_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Supplemental mapping file cannot be read") from exc
        if not isinstance(supplied, list):
            raise ValueError("Supplemental mapping file must be a JSON list")
        extras.extend(supplied)
    bindings.extend(_valid_binding(item, "supplemental") for item in extras)
    by_key: dict[tuple[str, str], VideoBinding] = {}
    by_id: dict[str, VideoBinding] = {}
    for binding in bindings:
        key = (binding.slug, binding.language)
        old_key, old_id = by_key.get(key), by_id.get(binding.video_id)
        if old_key and old_key.video_id != binding.video_id:
            # State may replace an old historical ID only because snapshots are
            # deliberately not an input source.  Two current sources conflict.
            raise ValueError(f"Conflicting video mappings for {binding.slug}|{binding.language}")
        if old_id and (old_id.slug, old_id.language) != key:
            raise ValueError(f"Ambiguous video ID mapping: {binding.video_id}")
        by_key[key] = binding
        by_id[binding.video_id] = binding
    return tuple(sorted(by_key.values(), key=lambda item: (item.slug, item.language)))


def select_bindings(inventory: Iterable[VideoBinding], slugs: set[str], languages: set[str]) -> list[VideoBinding]:
    return [item for item in inventory if (not slugs or item.slug in slugs) and (not languages or item.language in languages)]


def fetch_remote(youtube: Any, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    values = list(ids)
    result: dict[str, dict[str, Any]] = {}
    for index in range(0, len(values), MAX_OPERATIONAL_BATCH):
        response = youtube.videos().list(part=REMOTE_PARTS, id=",".join(values[index:index + MAX_OPERATIONAL_BATCH])).execute()
        for item in response.get("items", []):
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                result[item["id"]] = item
    missing = sorted(set(values) - set(result))
    if missing:
        raise RuntimeError("Remote snapshot is missing requested video IDs: " + ", ".join(missing))
    return result


def _snapshot_records(bindings: Iterable[VideoBinding], remote: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for binding in bindings:
        resource = remote[binding.video_id]
        snippet = resource.get("snippet")
        if not isinstance(snippet, dict) or not isinstance(snippet.get("description"), str):
            raise RuntimeError(f"Remote video lacks a description: {binding.video_id}")
        records.append({"slug": binding.slug, "language": binding.language, "video_id": binding.video_id, "source": binding.source, "resource": resource, "fingerprint": sha256_json(resource), "stable_fingerprint": stable_resource_fingerprint(resource)})
    return records


def write_snapshot(backup_dir: Path, records: list[dict[str, Any]]) -> Path:
    """Create a new immutable dated backup directory and its hash manifest."""
    try:
        date.fromisoformat(backup_dir.name)
    except ValueError as exc:
        raise RuntimeError("Backup directory name must be an ISO date (YYYY-MM-DD)") from exc
    if backup_dir.exists():
        raise RuntimeError(f"Backup directory already exists: {backup_dir}")
    backup_dir.mkdir(parents=True, exist_ok=False)
    videos = backup_dir / "videos"
    videos.mkdir()
    files: dict[str, str] = {}
    for record in records:
        path = videos / f"{record['video_id']}.json"
        _write_json(path, record["resource"])
        files[str(path.relative_to(backup_dir)).replace("\\", "/")] = sha256_text(path.read_text(encoding="utf-8"))
    snapshot = {"schema_version": 1, "created_at": datetime.now(UTC).isoformat(), "records": records}
    snapshot_path = backup_dir / "snapshot.json"
    _write_json(snapshot_path, snapshot)
    files["snapshot.json"] = sha256_text(snapshot_path.read_text(encoding="utf-8"))
    _write_json(backup_dir / "manifest.json", {"schema_version": 1, "files": files})
    return snapshot_path


def load_snapshot(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Snapshot cannot be read") from exc
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise ValueError("Snapshot has no records")
    return records


def _plan(binding: VideoBinding, record: dict[str, Any]) -> dict[str, Any]:
    resource = record.get("resource")
    if not isinstance(resource, dict) or record.get("video_id") != binding.video_id:
        raise ValueError(f"Snapshot binding mismatch for {binding.slug}|{binding.language}")
    snippet = resource.get("snippet")
    if not isinstance(snippet, dict) or not isinstance(snippet.get("description"), str):
        raise ValueError(f"Snapshot description is invalid for {binding.video_id}")
    desired, marker_present = desired_description(binding, snippet["description"])
    # Derive the planned value from the immutable raw resource.  This keeps
    # pre-stable-fingerprint snapshots (including 2026-09-10) compatible and
    # prevents a stored fingerprint field from drifting from the raw snapshot.
    snapshot_fingerprint = stable_resource_fingerprint(resource)
    return {"slug": binding.slug, "language": binding.language, "video_id": binding.video_id, "source": binding.source, "snapshot_fingerprint": snapshot_fingerprint, "description_sha256": sha256_text(desired), "original_description_sha256": sha256_text(snippet["description"]), "canonical_url": canonical_url(binding.slug, binding.language), "marker_present": marker_present, "status": "already_applied" if marker_present else "ready", "desired_description": desired, "resource": resource}


def _load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "applied": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Description ledger cannot be read") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("applied"), dict):
        raise ValueError("Description ledger has an unsupported schema")
    return payload


def _ledger_key(plan: dict[str, Any]) -> str:
    return f"{plan['video_id']}:{plan['description_sha256']}"


def _update_body(resource: dict[str, Any], description: str) -> dict[str, Any]:
    snippet = resource.get("snippet")
    if not isinstance(snippet, dict) or not isinstance(resource.get("id"), str):
        raise ValueError("Remote resource is missing snippet metadata")
    # Only snippet is passed to videos.update.  All mutable snippet fields are
    # copied from the re-fetched resource; status and every other part remain
    # untouched because they are intentionally absent from the update part.
    body: dict[str, Any] = {"id": resource["id"], "snippet": {"title": snippet.get("title"), "categoryId": snippet.get("categoryId"), "description": description}}
    if not isinstance(body["snippet"]["title"], str) or not isinstance(body["snippet"]["categoryId"], str):
        raise ValueError("Remote resource is missing title or category")
    if "tags" in snippet:
        if not isinstance(snippet["tags"], list) or not all(isinstance(tag, str) for tag in snippet["tags"]):
            raise ValueError("Remote resource has invalid tags")
        body["snippet"]["tags"] = list(snippet["tags"])
    if "defaultLanguage" in snippet:
        if not isinstance(snippet["defaultLanguage"], str):
            raise ValueError("Remote resource has invalid default language")
        body["snippet"]["defaultLanguage"] = snippet["defaultLanguage"]
    return body


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    _write_json(temporary, payload)
    for attempt in range(ATOMIC_WRITE_REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == ATOMIC_WRITE_REPLACE_ATTEMPTS - 1:
                # Leave the fully written temporary file available for manual
                # recovery rather than losing the only durable new payload.
                raise
            time.sleep(ATOMIC_WRITE_RETRY_DELAY_SECONDS)


def _positive_at_most_50(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= MAX_OPERATIONAL_BATCH:
        raise argparse.ArgumentTypeError("must be between 1 and 50")
    return parsed


def _service(client_secrets: Path) -> Any:
    from backend.studio.youtube.auth import get_credentials
    from backend.studio.youtube.uploader import build_youtube_service
    return build_youtube_service(get_credentials(client_secrets))


def main(argv: list[str] | None = None, *, service_factory: Callable[[Path], Any] = _service) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--snapshot-remote", action="store_true")
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--state", type=Path, default=STATE)
    parser.add_argument("--supplemental-mappings", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--client-secrets", type=Path)
    parser.add_argument("--slug", action="append", default=[])
    parser.add_argument("--language", choices=sorted(LANGUAGES), action="append", default=[])
    parser.add_argument("--max-updates", type=_positive_at_most_50)
    parser.add_argument("--confirm-read-remote", action="store_true")
    parser.add_argument("--confirm-apply-description-update", action="store_true")
    args = parser.parse_args(argv)
    selected_mode = "snapshot" if args.snapshot_remote else "apply" if args.apply else "preview"
    if selected_mode == "snapshot":
        if not args.client_secrets or not args.backup_dir or not args.confirm_read_remote:
            parser.error("--snapshot-remote requires --client-secrets, --backup-dir, and --confirm-read-remote")
    elif selected_mode == "apply":
        if not args.snapshot or not args.client_secrets or not args.confirm_apply_description_update or args.max_updates is None:
            parser.error("--apply requires --snapshot, --client-secrets, --max-updates, and --confirm-apply-description-update")
    elif not args.snapshot:
        parser.error("Preview is offline and requires --snapshot")
    if args.confirm_read_remote and selected_mode != "snapshot":
        parser.error("--confirm-read-remote is valid only with --snapshot-remote")

    inventory = select_bindings(load_inventory(args.state, args.supplemental_mappings), set(args.slug), set(args.language))
    if not inventory:
        raise RuntimeError("No inventory items matched the requested filters")
    if selected_mode == "snapshot":
        remote = fetch_remote(service_factory(args.client_secrets), [item.video_id for item in inventory])
        path = write_snapshot(args.backup_dir, _snapshot_records(inventory, remote))
        print(f"SNAPSHOT: {path}")
        return 0

    records = {(record.get("slug"), record.get("language")): record for record in load_snapshot(args.snapshot)}
    plans = [_plan(binding, records.get((binding.slug, binding.language), {})) for binding in inventory]
    ledger = _load_ledger(args.ledger) if selected_mode == "apply" else {"applied": {}}
    for plan in plans:
        if _ledger_key(plan) in ledger["applied"]:
            plan["status"] = "already_applied"
        plan.pop("resource") if selected_mode == "preview" else None
        plan.pop("desired_description") if selected_mode == "preview" else None
    if selected_mode == "preview":
        report = {"schema_version": 1, "mode": "preview", "items": plans}
        if args.report:
            _write_json_atomic(args.report, report)
        for plan in plans:
            print(f"{plan['status'].upper()} {plan['slug']}/{plan['language']} {plan['video_id']}")
        return 0

    updates = 0
    youtube = service_factory(args.client_secrets)
    remote = fetch_remote(youtube, [item.video_id for item in inventory])
    for plan in plans:
        if plan["status"] == "already_applied" or updates >= args.max_updates:
            continue
        current = remote[plan["video_id"]]
        if stable_resource_fingerprint(current) != plan["snapshot_fingerprint"]:
            plan["status"] = "fingerprint_conflict"
            continue
        try:
            youtube.videos().update(part="snippet", body=_update_body(current, plan["desired_description"])).execute()
        except Exception as exc:
            plan["status"] = "quota_exceeded" if _is_quota_error(exc) else "failed"
            if plan["status"] == "quota_exceeded":
                break
            continue
        ledger["applied"][_ledger_key(plan)] = {"video_id": plan["video_id"], "description_sha256": plan["description_sha256"], "slug": plan["slug"], "language": plan["language"], "applied_at": datetime.now(UTC).isoformat()}
        _write_json_atomic(args.ledger, ledger)
        plan["status"] = "applied"
        updates += 1
    for plan in plans:
        plan.pop("resource", None)
        plan.pop("desired_description", None)
    report = {"schema_version": 1, "mode": "apply", "items": plans}
    if args.report:
        _write_json_atomic(args.report, report)
    return 1 if any(item["status"] in {"failed", "quota_exceeded", "fingerprint_conflict"} for item in plans) else 0


if __name__ == "__main__":
    raise SystemExit(main())
