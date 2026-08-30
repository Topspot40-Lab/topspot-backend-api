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
DEFAULT_LEDGER = Path("backend/studio/work/youtube_caption_repair_ledger.json")
RepairMain = Callable[[list[str] | None], int]
_HTTP_ERROR_CATEGORIES = {
    "quotaExceeded": "youtube_quota_exceeded",
    "rateLimitExceeded": "youtube_rate_limit_exceeded",
    "userRateLimitExceeded": "youtube_rate_limit_exceeded",
    "authError": "youtube_auth_error",
    "invalidCredentials": "youtube_auth_error",
    "forbidden": "youtube_permission_denied",
    "insufficientPermissions": "youtube_permission_denied",
    "invalidValue": "youtube_invalid_request",
    "invalidParameter": "youtube_invalid_request",
    "required": "youtube_invalid_request",
}
_SAFE_HTTP_REASONS = frozenset(_HTTP_ERROR_CATEGORIES)


@dataclass(frozen=True)
class UploadedItem:
    slug: str
    language: str
    video_id: str


# This is deliberately an allowlist, not an inference from a previous report.
# Bootstrap is an operator attestation for precisely the tracks confirmed in
# this run; it is never evidence from ``captions_uploaded``.
BOOTSTRAP_APPLIED = frozenset({
    (slug, language)
    for slug in (
        "music_in_the_new_millennium", "ahmet_ertegun", "alan_freed",
        "banda_sinaloense", "beatles_vs_stones", "berry_gordy",
    )
    for language in LANGUAGES
} | {("birth_of_bossa_nova", "en"), ("birth_of_bossa_nova", "pt-BR")})


def main(
    argv: list[str] | None = None,
    *,
    repair_main: RepairMain = repair.main,
    binding_for_item: Callable[[UploadedItem, argparse.Namespace], str] | None = None,
) -> int:
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

    if args.bootstrap_applied:
        return _bootstrap(items, args, binding_for_item or _bootstrap_binding_for_item)

    ledger = _load_ledger(args.ledger)
    results: list[dict[str, str]] = []
    updates = 0
    for item in items:
        fingerprint: str | None = None
        if not args.align and not args.apply:
            # A cache-only audit can prove that an existing bootstrap entry is
            # still the exact local repair without invoking legacy recovery or
            # any remote service.  If local validation cannot prove it, retain
            # the normal repair CLI diagnostic path below.
            try:
                fingerprint = (binding_for_item or _audit_binding_for_item)(item, args)
            except Exception:
                fingerprint = None
            if fingerprint is not None and _ledger_matches(ledger, item, fingerprint):
                result = _result(item, "already_applied")
                results.append(result)
                print(f"ALREADY_APPLIED {item.slug}/{item.language}")
                continue
        if args.apply:
            try:
                fingerprint = (binding_for_item or _binding_for_item)(item, args)
            except Exception as exc:
                result = _failed_item(item, exc)
                results.append(result)
                print(f"FAILED {item.slug}/{item.language} ({result['error_category']}: {result['error_message']})")
                continue
            if _ledger_matches(ledger, item, fingerprint):
                result = _result(item, "already_applied")
                results.append(result)
                print(f"ALREADY_APPLIED {item.slug}/{item.language}")
                continue
            if args.max_updates is not None and updates >= args.max_updates:
                result = _result(item, "ready")
                results.append(result)
                print(f"READY {item.slug}/{item.language} (max updates reached)")
                continue
        result = _run_item(item, args, repair_main)
        quota_exceeded = args.apply and result.get("error_category") == "youtube_quota_exceeded"
        if quota_exceeded:
            result["status"] = "quota_exceeded"
        results.append(result)
        detail = f" ({result['error_category']}: {result['error_message']})" if "error_category" in result else ""
        print(f"{result['status'].upper()} {item.slug}/{item.language}{detail}")
        if args.apply and result["status"] == "applied":
            # The only success record is written immediately after the
            # narrow YouTube update returned successfully.
            assert fingerprint is not None
            _record_success_atomic(args.ledger, ledger, item, fingerprint)
            updates += 1
        if quota_exceeded:
            break

    _write_report_atomic(args.report, mode=_mode(args), items=results)
    summary = _summary(results)
    print("SUMMARY " + " ".join(f"{key}={value}" for key, value in sorted(summary.items())))
    print(f"REPORT: {args.report}")
    return 1 if summary.get("failed", 0) or summary.get("quota_exceeded", 0) else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    factory = parser.add_mutually_exclusive_group(required=True)
    factory.add_argument(
        "--factory-work-root", type=Path,
        help="root containing <slug>/factory directories",
    )
    factory.add_argument(
        "--factory-root", type=Path,
        help="exact external <slug>/factory directory (single selected slug)",
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--legacy-env-file", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--client-secrets", type=Path)
    parser.add_argument("--slug", action="append", default=[])
    parser.add_argument("--language", action="append", choices=LANGUAGES, default=[])
    parser.add_argument("--max-items", type=_positive_int)
    parser.add_argument("--max-updates", type=_positive_int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--align", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--bootstrap-applied", action="store_true", help="offline-record the explicitly confirmed completed repairs")
    parser.add_argument("--confirm-apply-existing-captions", action="store_true")
    parser.add_argument("--confirm-bootstrap-applied", action="store_true")
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
    if args.bootstrap_applied and (args.apply or args.align):
        parser.error("--bootstrap-applied cannot be combined with --align or --apply")
    if args.bootstrap_applied and not args.confirm_bootstrap_applied:
        parser.error("--bootstrap-applied requires --confirm-bootstrap-applied")
    if args.confirm_bootstrap_applied and not args.bootstrap_applied:
        parser.error("--confirm-bootstrap-applied is valid only with --bootstrap-applied")
    if args.max_updates is not None and not args.apply:
        parser.error("--max-updates is valid only with --apply")


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
        f"--factory-root={_factory_for_item(item, args)}",
    ]
    uses_v2 = _uses_v2_sidecar(item, args)
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
    return _result(item, "applied" if args.apply else "aligned" if args.align else "ready")


def _result(item: UploadedItem, status: str) -> dict[str, str]:
    return {"slug": item.slug, "language": item.language, "video_id": item.video_id, "status": status}


def _binding_for_item(item: UploadedItem, args: argparse.Namespace) -> str:
    """Validate the local VTT/cache/audio/transcript binding without YouTube."""
    factory = _factory_for_item(item, args)
    return repair.validated_repair_fingerprint(
        factory=factory, slug=item.slug, language=item.language,
        legacy_env_file=args.legacy_env_file,
    )


def _offline_binding_for_item(item: UploadedItem, args: argparse.Namespace) -> str:
    return repair.offline_validated_repair_fingerprint(
        factory=_factory_for_item(item, args), language=item.language
    )


def _bootstrap_binding_for_item(item: UploadedItem, args: argparse.Namespace) -> str:
    """Use recovered v2 source text when the operator authorized it.

    A v2 VTT is a rendering, not the original alignment input: rebuilding text
    from its cue wrapping can change the cache key.  The database-backed
    binding is therefore required whenever it is explicitly available.
    """
    return _binding_for_item(item, args) if _uses_v2_sidecar(item, args) else _offline_binding_for_item(item, args)


def _audit_binding_for_item(item: UploadedItem, args: argparse.Namespace) -> str:
    """Match a v2 bootstrap with the same authorized source recovery."""
    return _bootstrap_binding_for_item(item, args)


def _load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "applied": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Caption repair ledger cannot be read") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("applied"), dict):
        raise RuntimeError("Caption repair ledger has an unsupported schema")
    return payload


def _ledger_key(item: UploadedItem) -> str:
    return f"{item.slug}|{item.language}"


def _ledger_matches(ledger: dict[str, Any], item: UploadedItem, fingerprint: str) -> bool:
    entry = ledger["applied"].get(_ledger_key(item))
    return isinstance(entry, dict) and entry.get("video_id") == item.video_id and entry.get("fingerprint") == fingerprint


def _record_success_atomic(path: Path, ledger: dict[str, Any], item: UploadedItem, fingerprint: str) -> None:
    ledger["applied"][_ledger_key(item)] = {
        "slug": item.slug, "language": item.language, "video_id": item.video_id,
        "fingerprint": fingerprint, "status": "applied",
    }
    _write_json_atomic(path, ledger)


def _bootstrap(items: list[UploadedItem], args: argparse.Namespace, binding_for_item: Callable[[UploadedItem, argparse.Namespace], str]) -> int:
    ledger = _load_ledger(args.ledger)
    results: list[dict[str, str]] = []
    for item in items:
        if (item.slug, item.language) not in BOOTSTRAP_APPLIED:
            result = _failed_item(item, RuntimeError("Track is not in the explicit offline bootstrap allowlist"))
        else:
            try:
                fingerprint = binding_for_item(item, args)
                if _ledger_matches(ledger, item, fingerprint):
                    result = _result(item, "already_applied")
                else:
                    # The binding is computed exactly once, then immediately
                    # persisted with an atomic replacement before reporting
                    # this locally attested repair as bootstrapped.
                    _record_success_atomic(args.ledger, ledger, item, fingerprint)
                    result = _result(item, "bootstrapped")
            except Exception as exc:
                result = _failed_item(item, exc)
        results.append(result)
        detail = f" ({result['error_category']}: {result['error_message']})" if "error_category" in result else ""
        print(f"{result['status'].upper()} {item.slug}/{item.language}{detail}")
    _write_report_atomic(args.report, mode="bootstrap", items=results)
    summary = _summary(results)
    print("SUMMARY " + " ".join(f"{key}={value}" for key, value in sorted(summary.items())))
    print(f"REPORT: {args.report}")
    return 1 if summary.get("failed", 0) else 0


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


def _factory_for_item(item: UploadedItem, args: argparse.Namespace) -> Path:
    if args.factory_root is not None:
        return args.factory_root
    assert args.factory_work_root is not None
    return args.factory_work_root / item.slug / "factory"


def _uses_v2_sidecar(item: UploadedItem, args: argparse.Namespace) -> bool:
    sidecar = _factory_for_item(item, args) / "delivery" / item.language / "narration.inputs.json"
    try:
        return json.loads(sidecar.read_text(encoding="utf-8")).get("version") == 2
    except (OSError, json.JSONDecodeError, AttributeError):
        # The repair engine is authoritative for missing/invalid factories.
        return False


def _mode(args: argparse.Namespace) -> str:
    return "apply" if args.apply else "align" if args.align else "audit"


def _safe_error(exc: Exception) -> tuple[str, str]:
    """Keep operational diagnostics useful without exposing sensitive inputs."""
    if diagnostic := _google_http_diagnostic(exc):
        return diagnostic
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
    if message.startswith("A validated alignment cache"):
        return "alignment_cache_missing", message[:500]
    if message.startswith("Cached alignment") or message.startswith("Quarantined alignment"):
        return "alignment_cache_invalid", message[:500]
    if message.startswith("Final documentary duration") or message.startswith("Legacy-v2 reconstructed duration"):
        return "timing_validation_failed", message[:500]
    return type(exc).__name__, message[:500]


def _google_http_diagnostic(exc: Exception) -> tuple[str, str] | None:
    """Return an allowlisted Google HTTP diagnostic without exposing API data.

    ``HttpError`` may contain the request URL, response headers, and a response
    body with user-supplied data.  This helper reads only its numeric status and
    the documented JSON ``reason`` field, then formats a fixed message.
    """
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if _is_google_http_error(current):
            status = _http_status(current)
            reason = _google_error_reason(getattr(current, "content", None))
            category = _HTTP_ERROR_CATEGORIES.get(reason or "", "youtube_http_failure")
            detail = f"HTTP {status}" if status is not None else "an HTTP error"
            if reason is not None:
                detail += f" ({reason})"
            return category, f"YouTube captions API request failed with {detail}."
        current = current.__cause__ or current.__context__
    return None


def _is_google_http_error(exc: BaseException) -> bool:
    """Recognize googleapiclient's exception without importing it at runtime."""
    return type(exc).__name__ == "HttpError" and type(exc).__module__.startswith("googleapiclient")


def _http_status(exc: BaseException) -> int | None:
    status = getattr(getattr(exc, "resp", None), "status", None)
    # Never stringify an arbitrary response object: it can expose headers or a URL.
    return status if isinstance(status, int) and 100 <= status <= 599 else None


def _google_error_reason(content: object) -> str | None:
    """Extract only an explicitly allowlisted Google error reason from JSON."""
    if not isinstance(content, (bytes, bytearray, str)):
        return None
    try:
        raw = content[:65536]
        payload = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    errors = error.get("errors")
    if not isinstance(errors, list):
        return None
    for entry in errors:
        reason = entry.get("reason") if isinstance(entry, dict) else None
        if isinstance(reason, str) and reason in _SAFE_HTTP_REASONS:
            return reason
    return None


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
    _write_json_atomic(path, payload)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    raise SystemExit(main())
