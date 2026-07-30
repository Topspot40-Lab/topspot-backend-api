from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_AUDIT_ROOT = Path("backend/studio/work/narration_loudness_audit")
CATEGORIES = ("intro", "detail_long", "detail_short", "artist")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create verified local normalization candidates from narration "
            "files already downloaded by audit_narration_loudness.py. "
            "This script has no database or Supabase access."
        )
    )
    parser.add_argument("--slug", default="1960s-pop")
    parser.add_argument(
        "--language",
        choices=("en", "es", "pt-BR"),
        default="en",
    )
    parser.add_argument("--ranking", type=int, default=8)
    parser.add_argument("--target-lufs", type=float, default=-23.5)
    parser.add_argument("--true-peak", type=float, default=-1.5)
    parser.add_argument("--lra", type=float, default=11.0)
    parser.add_argument(
        "--bitrate-kbps",
        type=int,
        default=128,
        help="MP3 candidate bitrate. Original ElevenLabs files are 128 kbps.",
    )
    parser.add_argument("--audit-root", type=Path, default=DEFAULT_AUDIT_ROOT)
    return parser.parse_args()


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def loudnorm_payload(output: str) -> dict[str, Any]:
    matches = re.findall(r"\{\s*\"input_i\".*?\}", output, flags=re.DOTALL)
    if not matches:
        raise RuntimeError("FFmpeg loudnorm JSON was not found")
    return json.loads(matches[-1])


def finite_number(payload: dict[str, Any], key: str) -> float:
    try:
        value = float(str(payload[key]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid loudnorm value for {key}") from exc
    if not math.isfinite(value):
        raise RuntimeError(f"Non-finite loudnorm value for {key}")
    return value


def measure(
    source: Path,
    *,
    target_lufs: float,
    true_peak: float,
    lra: float,
) -> dict[str, Any]:
    result = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(source),
            "-af",
            (
                f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:"
                "print_format=json"
            ),
            "-f",
            "null",
            "-",
        ]
    )
    combined = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-1000:] or "FFmpeg failed")
    return loudnorm_payload(combined)


def normalize_two_pass(
    source: Path,
    destination: Path,
    *,
    target_lufs: float,
    true_peak: float,
    lra: float,
    bitrate_kbps: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if destination.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing candidate: {destination}"
        )

    before = measure(
        source,
        target_lufs=target_lufs,
        true_peak=true_peak,
        lra=lra,
    )

    measured_i = finite_number(before, "input_i")
    measured_tp = finite_number(before, "input_tp")
    measured_lra = finite_number(before, "input_lra")
    measured_thresh = finite_number(before, "input_thresh")
    offset = finite_number(before, "target_offset")

    destination.parent.mkdir(parents=True, exist_ok=True)
    filter_value = (
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:"
        f"measured_I={measured_i}:measured_TP={measured_tp}:"
        f"measured_LRA={measured_lra}:"
        f"measured_thresh={measured_thresh}:"
        f"offset={offset}:linear=true:print_format=json"
    )
    result = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-n",
            "-i",
            str(source),
            "-map_metadata",
            "0",
            "-af",
            filter_value,
            "-codec:a",
            "libmp3lame",
            "-b:a",
            f"{bitrate_kbps}k",
            "-id3v2_version",
            "3",
            str(destination),
        ]
    )
    if result.returncode != 0:
        if destination.exists():
            destination.unlink()
        raise RuntimeError(result.stderr.strip()[-1000:] or "FFmpeg failed")

    after = measure(
        destination,
        target_lufs=target_lufs,
        true_peak=true_peak,
        lra=lra,
    )
    return before, after


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_target_name(target_lufs: float) -> str:
    return f"{target_lufs:.1f}".replace("-", "minus_").replace(".", "_")


def resolve_audit_directory(
    audit_root: Path,
    slug: str,
    language: str,
) -> Path:
    language_directory = audit_root / slug / language
    if (language_directory / "loudness_report.csv").exists():
        return language_directory

    legacy_english_directory = audit_root / slug
    if (
        language == "en"
        and (legacy_english_directory / "loudness_report.csv").exists()
    ):
        return legacy_english_directory

    raise FileNotFoundError(
        f"Audit report not found for {slug}/{language}. "
        "Run the read-only audit first."
    )


def selected_rows(report_path: Path, ranking: int) -> list[dict[str, str]]:
    with report_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    selected: list[dict[str, str]] = []
    for category in CATEGORIES:
        match = next(
            (
                row
                for row in rows
                if row.get("category") == category
                and row.get("ranking") == str(ranking)
                and row.get("status") == "ok"
            ),
            None,
        )
        if not match:
            raise RuntimeError(
                f"No successful {category} measurement for ranking {ranking}"
            )
        selected.append(match)
    return selected


def ensure_descendant(path: Path, parent: Path) -> None:
    resolved_path = path.resolve()
    resolved_parent = parent.resolve()
    if resolved_path != resolved_parent and resolved_parent not in resolved_path.parents:
        raise RuntimeError(f"Unsafe path outside expected directory: {path}")


def main() -> None:
    args = parse_args()
    if args.ranking <= 0:
        raise SystemExit("--ranking must be positive")
    if not (-30.0 <= args.target_lufs <= -12.0):
        raise SystemExit("--target-lufs must be between -30 and -12")
    if not (64 <= args.bitrate_kbps <= 320):
        raise SystemExit("--bitrate-kbps must be between 64 and 320")

    audit_directory = resolve_audit_directory(
        args.audit_root,
        args.slug,
        args.language,
    )
    report_path = audit_directory / "loudness_report.csv"
    download_root = audit_directory / "downloads"
    candidate_root = (
        audit_directory
        / "normalization_pilot"
        / f"target_{safe_target_name(args.target_lufs)}_lufs"
        / f"bitrate_{args.bitrate_kbps}k"
        / f"ranking_{args.ranking:02d}"
    )
    manifest_path = candidate_root / "manifest.json"

    if candidate_root.exists():
        raise SystemExit(
            f"Refusing to reuse existing pilot directory: {candidate_root}"
        )

    rows = selected_rows(report_path, args.ranking)
    candidate_root.mkdir(parents=True, exist_ok=False)

    print(
        f"Creating {len(rows)} local candidates for "
        f"{args.slug}/{args.language}, ranking {args.ranking}, "
        f"target {args.target_lufs:.1f} LUFS, "
        f"{args.bitrate_kbps} kbps."
    )
    print("Original downloads will not be modified.")
    print("This script has no database or Supabase access.")

    manifest: dict[str, Any] = {
        "slug": args.slug,
        "language": args.language,
        "ranking": args.ranking,
        "target_lufs": args.target_lufs,
        "true_peak_dbtp": args.true_peak,
        "loudness_range_lu": args.lra,
        "bitrate_kbps": args.bitrate_kbps,
        "files": [],
    }

    for row in rows:
        category = row["category"]
        bucket = row["bucket"]
        key = row["key"]
        source = download_root / bucket / key
        destination = candidate_root / category / Path(key).name

        ensure_descendant(source, download_root)
        ensure_descendant(destination, candidate_root)
        if not source.exists() or source.stat().st_size <= 0:
            raise FileNotFoundError(source)

        print(f"  {category:<13} {source.name}")
        before, after = normalize_two_pass(
            source,
            destination,
            target_lufs=args.target_lufs,
            true_peak=args.true_peak,
            lra=args.lra,
            bitrate_kbps=args.bitrate_kbps,
        )
        after_lufs = finite_number(after, "input_i")
        if abs(after_lufs - args.target_lufs) > 0.5:
            raise RuntimeError(
                f"Verification failed for {destination}: "
                f"{after_lufs:.2f} LUFS"
            )

        manifest["files"].append(
            {
                "category": category,
                "track_name": row["track_name"],
                "artist_name": row["artist_name"],
                "bucket": bucket,
                "key": key,
                "original_path": str(source),
                "original_size_bytes": source.stat().st_size,
                "original_sha256": sha256(source),
                "original_lufs": finite_number(before, "input_i"),
                "candidate_path": str(destination),
                "candidate_size_bytes": destination.stat().st_size,
                "candidate_sha256": sha256(destination),
                "candidate_lufs": after_lufs,
                "candidate_true_peak_dbtp": finite_number(
                    after,
                    "input_tp",
                ),
            }
        )

    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print()
    print(f"Verified local pilot: {candidate_root}")
    print(f"Manifest: {manifest_path}")
    print("No original, database, or Supabase file was changed.")


if __name__ == "__main__":
    main()
