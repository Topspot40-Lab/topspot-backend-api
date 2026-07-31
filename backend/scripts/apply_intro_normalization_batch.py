from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.services.supabase_client import supabase
from backend.services.supabase_storage import upload_bytes


BACKUP_PREFIX = "normalization-backups"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Apply or roll back a verified intro-normalization manifest. "
            "Apply performs a complete read-only preflight, creates and "
            "verifies remote backups, uploads candidates, and verifies them."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("manifest", type=Path)
    apply_parser.add_argument(
        "--expected-current-manifest",
        type=Path,
        help="Manifest whose candidates are currently in production.",
    )
    apply_parser.add_argument("--confirm", required=True)

    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("report", type=Path)
    rollback_parser.add_argument("--confirm", required=True)
    return parser.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def download(bucket: str, key: str) -> bytes:
    data = supabase.storage.from_(bucket).download(key)
    if not data:
        raise RuntimeError(f"Empty download: {bucket}/{key}")
    return data


def verify_remote(
    bucket: str,
    key: str,
    expected_sha256: str,
    *,
    attempts: int = 1,
) -> bool:
    for attempt in range(attempts):
        if sha256_bytes(download(bucket, key)) == expected_sha256:
            return True
        if attempt + 1 < attempts:
            time.sleep(min(8, 2 ** attempt))
    return False


def validated_manifest(path: Path) -> dict[str, Any]:
    manifest = read_json(path)
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("Manifest has no files")

    errors = [row for row in files if row.get("status") == "error"]
    if errors:
        raise RuntimeError("Manifest contains preparation errors")

    candidates = [
        row for row in files if row.get("status") == "candidate_verified"
    ]
    if len(candidates) != len(files):
        raise RuntimeError(
            "Apply requires every manifest row to be candidate_verified"
        )

    for row in candidates:
        original = Path(row["original_path"])
        candidate = Path(row["candidate_path"])
        if not original.exists() or not candidate.exists():
            raise FileNotFoundError(
                f"Missing local original or candidate for {row.get('key')}"
            )
        if sha256_file(original) != row["original_sha256"]:
            raise RuntimeError(
                f"Local original checksum mismatch: {row.get('key')}"
            )
        if sha256_file(candidate) != row["candidate_sha256"]:
            raise RuntimeError(
                f"Local candidate checksum mismatch: {row.get('key')}"
            )

    return manifest


def confirmation(
    action: str,
    count: int,
    language: str,
    slug: str,
) -> str:
    return f"{action} {count} {language} {slug}"


def expected_current_checksums(
    path: Path | None,
    slug: str,
    language: str,
) -> dict[tuple[str, str], str]:
    if path is None:
        return {}
    manifest = read_json(path)
    if str(manifest.get("slug")) != slug:
        raise RuntimeError("Expected-current manifest slug does not match")
    if str(manifest.get("language")) != language:
        raise RuntimeError(
            "Expected-current manifest language does not match"
        )
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("Expected-current manifest has no files")
    result: dict[tuple[str, str], str] = {}
    for row in files:
        checksum = str(row.get("candidate_sha256") or "")
        if not checksum:
            raise RuntimeError(
                "Expected-current candidate checksum missing: "
                f"{row.get('bucket')}/{row.get('key')}"
            )
        result[(str(row["bucket"]), str(row["key"]))] = checksum
    return result


def apply(
    manifest_path: Path,
    supplied_confirmation: str,
    expected_current_manifest_path: Path | None,
) -> None:
    manifest = validated_manifest(manifest_path)
    files = manifest["files"]
    slug = str(manifest["slug"])
    language = str(manifest["language"])
    current_checksums = expected_current_checksums(
        expected_current_manifest_path,
        slug,
        language,
    )
    expected_confirmation = confirmation(
        "UPLOAD",
        len(files),
        language,
        slug,
    )
    if supplied_confirmation != expected_confirmation:
        raise SystemExit(
            "Confirmation did not match. Required exactly: "
            f"{expected_confirmation}"
        )

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = (
        manifest_path.parent
        / "upload_runs"
        / f"{run_id}.json"
    )
    report: dict[str, Any] = {
        "operation": "apply",
        "status": "preflight",
        "run_id": run_id,
        "slug": slug,
        "language": language,
        "manifest_path": str(manifest_path),
        "expected_current_manifest_path": (
            str(expected_current_manifest_path)
            if expected_current_manifest_path
            else None
        ),
        "file_count": len(files),
        "files": [],
    }

    for row in files:
        report["files"].append(
            {
                "ranking": row["ranking"],
                "bucket": row["bucket"],
                "key": row["key"],
                "source_original_sha256": row["original_sha256"],
                "original_sha256": current_checksums.get(
                    (row["bucket"], row["key"]),
                    row["original_sha256"],
                ),
                "candidate_sha256": row["candidate_sha256"],
                "candidate_path": row["candidate_path"],
                "backup_key": (
                    f"{BACKUP_PREFIX}/{run_id}/{row['key']}"
                ),
                "preflight_verified": False,
                "backup_verified": False,
                "uploaded": False,
                "production_verified": False,
                "error": "",
            }
        )
    write_json_atomic(report_path, report)

    print(f"Preflight: verifying {len(files)} current remote files")
    current_data_by_key: dict[tuple[str, str], bytes] = {}
    for index, item in enumerate(report["files"], start=1):
        current_data = download(item["bucket"], item["key"])
        if sha256_bytes(current_data) != item["original_sha256"]:
            item["error"] = "Current remote checksum mismatch"
            report["status"] = "preflight_failed"
            write_json_atomic(report_path, report)
            raise RuntimeError(
                f"Current remote file changed: "
                f"{item['bucket']}/{item['key']}"
            )
        current_data_by_key[(item["bucket"], item["key"])] = current_data
        item["preflight_verified"] = True
        print(f"  [{index:>2}/{len(files)}] verified {item['key']}")
    report["status"] = "preflight_verified"
    write_json_atomic(report_path, report)

    print("Backup: creating and verifying remote original copies")
    for index, item in enumerate(report["files"], start=1):
        original_data = current_data_by_key[
            (item["bucket"], item["key"])
        ]
        upload_bytes(
            item["bucket"],
            item["backup_key"],
            original_data,
            "audio/mpeg",
        )
        if not verify_remote(
            item["bucket"],
            item["backup_key"],
            item["original_sha256"],
            attempts=3,
        ):
            item["error"] = "Remote backup checksum mismatch"
            report["status"] = "backup_failed"
            write_json_atomic(report_path, report)
            raise RuntimeError(
                f"Remote backup verification failed: "
                f"{item['bucket']}/{item['backup_key']}"
            )
        item["backup_verified"] = True
        print(f"  [{index:>2}/{len(files)}] backed up {item['key']}")
        write_json_atomic(report_path, report)
    report["status"] = "backups_verified"
    write_json_atomic(report_path, report)

    print("Upload: replacing production intros")
    for index, item in enumerate(report["files"], start=1):
        candidate_data = Path(item["candidate_path"]).read_bytes()
        upload_bytes(
            item["bucket"],
            item["key"],
            candidate_data,
            "audio/mpeg",
        )
        item["uploaded"] = True
        print(f"  [{index:>2}/{len(files)}] uploaded {item['key']}")
        write_json_atomic(report_path, report)
    report["status"] = "uploaded"
    write_json_atomic(report_path, report)

    print("Verify: checking production replacements")
    verification_failures = 0
    for index, item in enumerate(report["files"], start=1):
        verified = verify_remote(
            item["bucket"],
            item["key"],
            item["candidate_sha256"],
            attempts=5,
        )
        item["production_verified"] = verified
        if not verified:
            item["error"] = (
                "Production checksum verification failed; "
                "CDN caching may be involved"
            )
            verification_failures += 1
        print(
            f"  [{index:>2}/{len(files)}] "
            f"{'verified' if verified else 'NOT VERIFIED'} "
            f"{item['key']}"
        )
        write_json_atomic(report_path, report)

    report["status"] = (
        "completed"
        if verification_failures == 0
        else "verification_failed"
    )
    write_json_atomic(report_path, report)

    print()
    print(f"Upload report: {report_path}")
    print(f"Verified replacements: {len(files) - verification_failures}")
    print(f"Verification failures: {verification_failures}")
    print(
        "Rollback confirmation phrase: "
        f"{confirmation('ROLLBACK', len(files), language, slug)}"
    )
    if verification_failures:
        raise SystemExit(1)


def rollback(report_path: Path, supplied_confirmation: str) -> None:
    report = read_json(report_path)
    files = report.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("Upload report has no files")

    slug = str(report["slug"])
    language = str(report["language"])
    expected_confirmation = confirmation(
        "ROLLBACK",
        len(files),
        language,
        slug,
    )
    if supplied_confirmation != expected_confirmation:
        raise SystemExit(
            "Confirmation did not match. Required exactly: "
            f"{expected_confirmation}"
        )

    print("Rollback preflight: verifying every remote backup")
    backup_data: list[bytes] = []
    for index, item in enumerate(files, start=1):
        data = download(item["bucket"], item["backup_key"])
        if sha256_bytes(data) != item["original_sha256"]:
            raise RuntimeError(
                f"Backup checksum mismatch: "
                f"{item['bucket']}/{item['backup_key']}"
            )
        backup_data.append(data)
        print(f"  [{index:>2}/{len(files)}] verified {item['backup_key']}")

    print("Rollback: restoring production originals")
    for index, (item, data) in enumerate(
        zip(files, backup_data, strict=True),
        start=1,
    ):
        upload_bytes(
            item["bucket"],
            item["key"],
            data,
            "audio/mpeg",
        )
        print(f"  [{index:>2}/{len(files)}] restored {item['key']}")

    print("Rollback verify: checking restored production files")
    failures = 0
    for index, item in enumerate(files, start=1):
        verified = verify_remote(
            item["bucket"],
            item["key"],
            item["original_sha256"],
            attempts=5,
        )
        if not verified:
            failures += 1
        print(
            f"  [{index:>2}/{len(files)}] "
            f"{'verified' if verified else 'NOT VERIFIED'} "
            f"{item['key']}"
        )

    rollback_report = report_path.with_name(
        report_path.stem + "_rollback.json"
    )
    write_json_atomic(
        rollback_report,
        {
            "operation": "rollback",
            "source_upload_report": str(report_path),
            "slug": slug,
            "language": language,
            "file_count": len(files),
            "verification_failures": failures,
            "status": "completed" if failures == 0 else "verification_failed",
        },
    )
    print()
    print(f"Rollback report: {rollback_report}")
    print(f"Verification failures: {failures}")
    if failures:
        raise SystemExit(1)


def main() -> None:
    args = parse_args()
    if args.command == "apply":
        apply(
            args.manifest,
            args.confirm,
            args.expected_current_manifest,
        )
    else:
        rollback(args.report, args.confirm)


if __name__ == "__main__":
    main()
