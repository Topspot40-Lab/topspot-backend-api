# backend/services/supabase_storage.py
import logging
from typing import Iterable, List, Dict, Any
from pathlib import PurePosixPath

from backend.services.supabase_client import supabase
from backend.utils.tts_diagnostics import normalize_for_filename

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Upload helpers (unchanged)
# ─────────────────────────────────────────────────────────────────────────────
def upload_bytes(bucket: str, key: str, data: bytes, content_type: str = "audio/mpeg"):
    supabase.storage.from_(bucket).upload(
        path=key,
        file=data,
        file_options={"content-type": content_type, "upsert": "true"},
    )


def object_exists(bucket: str, key: str) -> bool:
    """Lightweight existence check by listing the parent folder."""
    parent = key.rsplit("/", 1)[0] if "/" in key else ""
    name = key.split("/")[-1]
    try:
        objs = supabase.storage.from_(bucket).list(
            path=parent,
            limit=1000,
            sort_by={"column": "name", "order": "asc"},
            search=name,  # newer clients
        )
    except TypeError:
        # older client signature
        opts = {"limit": 1000, "sortBy": {"column": "name", "order": "asc"}}
        objs = supabase.storage.from_(bucket).list(parent, opts)
        if name:
            objs = [o for o in (objs or []) if name.lower() in (o.get("name", "").lower())]
    return any(o.get("name") == name for o in (objs or []))


# ─────────────────────────────────────────────────────────────────────────────
# Recursive storage walk + prefix filter (FIX)
# ─────────────────────────────────────────────────────────────────────────────
def _list_dir(bucket: str, path: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """
    List a single 'directory' in Supabase Storage with pagination.
    Returns raw item dicts (files and 'folders').
    """
    try:
        return supabase.storage.from_(bucket).list(
            path=path,
            limit=limit,
            offset=offset,
            sort_by={"column": "name", "order": "asc"},
        ) or []
    except TypeError:
        # older client signature
        return supabase.storage.from_(bucket).list(
            path or "",
            {"limit": limit, "offset": offset, "sortBy": {"column": "name", "order": "asc"}},
        ) or []


def _is_folder(item: Dict[str, Any]) -> bool:
    """
    Heuristic: SDK returns pseudo-folder entries without file metadata.
    We treat anything lacking typical file fields as a folder.
    """
    name = item.get("name")
    # files usually have metadata like size, updated_at, etc.
    has_meta = any(k in item for k in ("metadata", "id", "updated_at", "created_at", "last_accessed_at", "size"))
    # If there's no extension, it might be a folder placeholder; SDKs vary.
    looks_like_file = isinstance(name, str) and "." in name
    return not (has_meta and looks_like_file)


def _walk(bucket: str, root: str = "") -> List[str]:
    """
    Recursively collect FULL object paths under `root`.
    """
    stack = [root.strip("/")]
    files: List[str] = []

    while stack:
        current = stack.pop()
        offset = 0
        while True:
            items = _list_dir(bucket, current, limit=100, offset=offset)
            if not items:
                break

            for it in items:
                name = it.get("name")
                if not name:
                    continue
                full = (PurePosixPath(current) / name).as_posix() if current else name
                if _is_folder(it):
                    stack.append(full)
                else:
                    files.append(full)

            if len(items) < 100:
                break
            offset += 100

    return files


def _list_paths_with_prefix_recursive(bucket: str, basename_prefix: str) -> List[str]:
    """
    Returns FULL object paths whose BASENAME startswith(basename_prefix) and end with .mp3,
    searching the entire bucket recursively.
    """
    all_files = _walk(bucket, root="")
    matches = []
    lp = basename_prefix.lower()
    for path in all_files:
        base = path.split("/")[-1]
        if base.lower().startswith(lp) and base.lower().endswith(".mp3"):
            matches.append(path)
    return sorted(set(matches))


def bucket_for(kind: str, lang: str) -> str:
    if lang == "es":
        return "audio-es"
    if lang in {"pt-BR", "ptbr"}:
        return "audio-ptbr"
    return "audio-en"


# ─────────────────────────────────────────────────────────────────────────────
# Public delete helpers (FIXED to use recursive listing + full paths)
# ─────────────────────────────────────────────────────────────────────────────
def delete_mp3s_by_prefix(
        kind: str,  # "intro" | "detail" | "artist"
        decade: str,
        genre: str,
        languages: Iterable[str],
        dry_run: bool = True
) -> Dict[str, Dict[str, Any]]:
    """
    Deletes all objects whose BASENAME starts with '<decade>_<genre>_' from the
    language-specific bucket for the given `kind`. Recurses through all folders.
    """
    basename_prefix = f"{normalize_for_filename(decade)}_{normalize_for_filename(genre)}_"
    report: Dict[str, Dict[str, Any]] = {}

    for lang in languages:
        bucket = bucket_for(kind, lang)  # maps locales to the right bucket
        matches = _list_paths_with_prefix_recursive(bucket, basename_prefix)

        logger.info(f"🧹 {kind.upper()} | lang={lang} bucket={bucket} prefix='{basename_prefix}' matches={len(matches)}")
        if dry_run or not matches:
            report[lang] = {
                "bucket": bucket,
                "prefix": basename_prefix,
                "matched": len(matches),
                "deleted": 0,
                "dry_run": dry_run,
                "samples": matches[:10],
            }
            continue

        # IMPORTANT: remove() expects object KEYS (full paths relative to bucket root)
        resp = supabase.storage.from_(bucket).remove(matches)
        # supabase-py usually returns a list of {'name': '...'} on success
        deleted_count = len(matches) if resp is None else (len(resp) if isinstance(resp, list) else len(matches))

        report[lang] = {
            "bucket": bucket,
            "prefix": basename_prefix,
            "matched": len(matches),
            "deleted": deleted_count,
            "dry_run": False,
            "samples": matches[:10],
        }

    return report


# --- Convenience wrappers (unchanged signature for your router) ---
def delete_intro_mp3_files_for_combo(
        decade: str,
        genre: str,
        languages: Iterable[str] = ("en",),  # or ("en","es","pt-BR")
        dry_run: bool = False
) -> Dict[str, Dict[str, Any]]:
    return delete_mp3s_by_prefix("intro", decade, genre, languages, dry_run)


def delete_detail_mp3_files_for_combo(
        decade: str,
        genre: str,
        languages: Iterable[str] = ("en",),
        dry_run: bool = False
) -> Dict[str, Dict[str, Any]]:
    return delete_mp3s_by_prefix("detail", decade, genre, languages, dry_run)


def delete_artist_mp3_files_for_combo(
        decade: str,
        genre: str,
        languages: Iterable[str] = ("en",),
        dry_run: bool = False
) -> Dict[str, Dict[str, Any]]:
    return delete_mp3s_by_prefix("artist", decade, genre, languages, dry_run)
