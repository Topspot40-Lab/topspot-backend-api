"""Safely audit, align, and repair captions for uploaded docuseries batches.

This is intentionally an orchestrator.  ``repair_youtube_captions`` remains
the sole implementation of caption recovery, timing, cache validation,
alignment, and the narrowly-scoped YouTube caption update.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.scripts import repair_youtube_captions as repair
from backend.studio.youtube.caption_alignment import AlignmentCacheMissing


LANGUAGES = ("en", "es", "pt-BR")
DEFAULT_STATE = Path("backend/studio/work/youtube_release_state.json")
DEFAULT_REPORT = Path("backend/studio/work/youtube_caption_repair_report.json")
RepairMain = Callable[[list[str] | None], int]
@dataclass(frozen=True)
class UploadedItem:
    slug: str
    language: str
    video_id: str


def main(argv: list[str] | None = None, *, repair_main: RepairMain = repair.main) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_options(parser, args)

    try:
        items = _selected_items(
            _load_state(args.state), slugs=set(args.slug), languages=set(args.language)
        )
    except Exception as exc:
        _write_report_atomic(args.report, mode=_mode(args), items=[], catalog_error=_safe_error(exc))
        print(f"CATALOG FAILED: {_safe_error(exc)[1]}")
        print(f"REPORT: {args.report}")
        return 2

    if args.max_items is not None:
        items = items[: args.max_items]

    results: list[dict[str, str]] = []
    for item in items:
        result = _run_item(item, args, repair_main)
        results.append(result)
        detail = f" ({result['error_category']}: {result['error_message']})" if "error_category" in result else ""
        print(f"{result['status'].upper()} {item.slug}/{item.language}{detail}")

    _write_report_atomic(args.report, mode=_mode(args), items=results)
    summary = _summary(results)
    print("SUMMARY " + " ".join(f"{key}={value}" for key, value in sorted(summary.items())))
    print(f"REPORT: {args.report}")
    return 1 if summary.get("failed", 0) else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factory-work-root", required=True, type=Path)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--legacy-env-file", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--client-secrets", type=Path)
    parser.add_argument("--slug", action="append", default=[])
    parser.add_argument("--language", action="append", choices=LANGUAGES, default=[])
    parser.add_argument("--max-items", type=_positive_int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--align", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-apply-existing-captions", action="store_true")
    return parser


def _validate_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.env_file and not args.align:
        parser.error("--env-file is permitted only with --align")
    if args.client_secrets and not args.apply:
        parser.error("--client-secrets is permitted only with --apply")
    if args.apply and not args.client_secrets:
        parser.error("--client-secrets is required with --apply")
    if args.apply and not args.confirm_apply_existing_captions:
        parser.error("--apply requires --confirm-apply-existing-captions")
    if args.confirm_apply_existing_captions and not args.apply:
        parser.error("--confirm-apply-existing-captions is valid only with --apply")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Release-state file cannot be read") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("uploads"), dict):
        raise RuntimeError("Release-state file has no uploads mapping")
    return payload


def _selected_items(
    state: dict[str, Any], *, slugs: set[str], languages: set[str]
) -> list[UploadedItem]:
    items: list[UploadedItem] = []
    for key, record in state["uploads"].items():
        if not isinstance(key, str) or not isinstance(record, dict):
            continue
        slug, separator, language = key.rpartition("|")
        video_id = record.get("video_id")
        if (
            not separator
            or not slug
            or language not in LANGUAGES
            or record.get("status") != "uploaded"
            or not isinstance(video_id, str)
            or not video_id.strip()
            or (slugs and slug not in slugs)
            or (languages and language not in languages)
        ):
            continue
        # captions_uploaded is intentionally not considered: it is not proof
        # that this binding has ever been repaired.
        items.append(UploadedItem(slug, language, video_id.strip()))
    return sorted(items, key=lambda item: (item.slug, item.language))


def _run_item(item: UploadedItem, args: argparse.Namespace, repair_main: RepairMain) -> dict[str, str]:
    command = [
        f"--slug={item.slug}",
        f"--language={item.language}",
        f"--video-id={item.video_id}",
        f"--factory-root={args.factory_work_root / item.slug / 'factory'}",
    ]
    uses_v2 = _uses_v2_sidecar(args.factory_work_root, item)
    if uses_v2 and not args.legacy_env_file:
        return _failed_item(
            item,
            RuntimeError(
                "Version-2 narration recovery requires --legacy-env-file; "
                "database access is disabled without it."
            ),
        )
    if args.legacy_env_file and uses_v2:
        command.append(f"--legacy-env-file={args.legacy_env_file}")
    if args.align:
        command.append("--align")
        if args.env_file:
            command.append(f"--env-file={args.env_file}")
    elif args.apply:
        command.extend(("--apply", f"--client-secrets={args.client_secrets}"))
    try:
        exit_code = repair_main(command)
        if exit_code:
            raise RuntimeError(f"Repair engine returned exit code {exit_code}")
    except SystemExit:
        # A delegated argparse failure is an item failure, never a batch failure.
        return _failed_item(item, RuntimeError("Repair engine exited with SystemExit"))
    except Exception as exc:
        if _is_alignment_required(args, exc):
            return _alignment_required_item(item, exc)
        return _failed_item(item, exc)
    return {
        "slug": item.slug,
        "language": item.language,
        "video_id": item.video_id,
        "status": "applied" if args.apply else "aligned" if args.align else "ready",
    }


def _is_alignment_required(args: argparse.Namespace, exc: Exception) -> bool:
    """Recognize only the cache-only miss emitted by the alignment layer."""
    if args.align or args.apply:
        return False
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, AlignmentCacheMissing):
            return True
        current = current.__cause__ or current.__context__
    return False


def _alignment_required_item(item: UploadedItem, exc: Exception) -> dict[str, str]:
    _, message = _safe_error(exc)
    return {
        "slug": item.slug,
        "language": item.language,
        "video_id": item.video_id,
        "status": "alignment_required",
        "error_category": "alignment_cache_missing",
        "error_message": message,
    }


def _failed_item(item: UploadedItem, exc: Exception) -> dict[str, str]:
    category, message = _safe_error(exc)
    return {
        "slug": item.slug,
        "language": item.language,
        "video_id": item.video_id,
        "status": "failed",
        "error_category": category,
        "error_message": message,
    }


def _uses_v2_sidecar(factory_work_root: Path, item: UploadedItem) -> bool:
    sidecar = factory_work_root / item.slug / "factory" / "delivery" / item.language / "narration.inputs.json"
    try:
        return json.loads(sidecar.read_text(encoding="utf-8")).get("version") == 2
    except (OSError, json.JSONDecodeError, AttributeError):
        # The repair engine is authoritative for missing/invalid factories.
        return False


def _mode(args: argparse.Namespace) -> str:
    return "apply" if args.apply else "align" if args.align else "audit"


def _safe_error(exc: Exception) -> tuple[str, str]:
    """Keep operational diagnostics useful without exposing sensitive inputs."""
    category = type(exc).__name__
    message = str(exc) or "Repair engine failed without a diagnostic"
    message = re.sub(r"\b(?:postgres(?:ql)?|mysql|https?)://\S+", "[redacted-url]", message, flags=re.IGNORECASE)
    message = re.sub(r"(?i)(api[_ -]?key|token|password|secret)\s*[=:]\s*\S+", r"\1=[redacted]", message)
    message = " ".join(message.split())
    safe_prefixes = (
        "Release-state file",
        "Factory root",
        "Version-2 narration recovery",
        "Authoritative narration",
        "Authoritative localized",
        "Missing publishing inputs",
        "Missing opening media",
        "Narration or final documentary",
        "Final documentary duration",
        "Legacy-v2 reconstructed duration",
        "Caption transcript",
        "Caption timeline",
        "Caption cues",
        "Cached alignment",
        "Quarantined alignment",
        "A validated alignment cache",
        "Alignment ",
        "ElevenLabs forced alignment",
        "Repair engine exited with SystemExit",
        "Repair engine returned exit code",
    )
    if not message.startswith(safe_prefixes):
        message = "Repair engine failed; inspect local command diagnostics."
    return category, message[:500]


def _summary(items: Iterable[dict[str, str]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        status = item["status"]
        result[status] = result.get(status, 0) + 1
    return result


def _write_report_atomic(
    path: Path,
    *,
    mode: str,
    items: list[dict[str, str]],
    catalog_error: tuple[str, str] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "mode": mode,
        "summary": _summary(items),
        "items": items,
    }
    if catalog_error:
        payload["catalog_error"] = {"category": catalog_error[0], "message": catalog_error[1]}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    raise SystemExit(main())
