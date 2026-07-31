from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import (
    Artist,
    DecadeGenre,
    Track,
    TrackRanking,
    TrackRankingLocale,
)
from backend.services.supabase_client import supabase


DEFAULT_OUTPUT_ROOT = Path(
    "backend/studio/work/narration_normalization_batches"
)
DEFAULT_BUCKETS = {
    "en": "audio-en",
    "es": "audio-es",
    "pt-BR": "audio-ptbr",
}


@dataclass(frozen=True)
class IntroAsset:
    ranking: int
    track_name: str
    artist_name: str
    bucket: str
    key: str


@dataclass
class ManifestRow:
    ranking: int
    track_name: str
    artist_name: str
    bucket: str
    key: str
    status: str
    original_path: str = ""
    original_size_bytes: int | None = None
    original_sha256: str = ""
    original_lufs: float | None = None
    adjustment_db: float | None = None
    candidate_path: str = ""
    candidate_size_bytes: int | None = None
    candidate_sha256: str = ""
    candidate_lufs: float | None = None
    candidate_true_peak_dbtp: float | None = None
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare and verify local normalized intro candidates for one "
            "Nostalgia program. This tool downloads originals but cannot "
            "upload, delete, or modify Supabase or the database."
        )
    )
    parser.add_argument("--slug", required=True)
    parser.add_argument(
        "--language",
        required=True,
        choices=tuple(DEFAULT_BUCKETS),
    )
    parser.add_argument("--target-lufs", type=float, default=-23.5)
    parser.add_argument("--tolerance-lu", type=float, default=1.0)
    parser.add_argument(
        "--verification-tolerance-lu",
        type=float,
        default=0.75,
    )
    parser.add_argument("--true-peak", type=float, default=-1.5)
    parser.add_argument("--lra", type=float, default=11.0)
    parser.add_argument("--bitrate-kbps", type=int, default=128)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--source-manifest",
        type=Path,
        help=(
            "Reuse checksum-verified originals from an earlier batch "
            "instead of downloading current production objects."
        ),
    )
    return parser.parse_args()


def intro_key(slug: str, ranking: int) -> str:
    return f"intro/{slug.replace('-', '_')}_{ranking:02d}.mp3"


def load_assets(slug: str, language: str) -> list[IntroAsset]:
    with Session(engine) as session:
        decade_genre = session.exec(
            select(DecadeGenre).where(DecadeGenre.slug == slug)
        ).first()
        if not decade_genre:
            raise SystemExit(f"DecadeGenre not found: {slug}")

        rows = list(
            session.exec(
                select(TrackRanking, Track, Artist)
                .join(Track, TrackRanking.track_id == Track.id)
                .join(Artist, Track.artist_id == Artist.id)
                .where(TrackRanking.decade_genre_id == decade_genre.id)
                .order_by(TrackRanking.ranking)
            ).all()
        )

        locales = (
            list(
                session.exec(
                    select(TrackRankingLocale).where(
                        TrackRankingLocale.track_ranking_id.in_(
                            [ranking.id for ranking, _, _ in rows]
                        ),
                        TrackRankingLocale.language_code == language,
                    )
                ).all()
            )
            if language != "en"
            else []
        )

    locale_by_ranking = {
        locale.track_ranking_id: locale for locale in locales
    }
    default_bucket = DEFAULT_BUCKETS[language]
    assets: list[IntroAsset] = []

    for ranking, track, artist in rows:
        if language == "en":
            bucket = default_bucket
            key = intro_key(slug, int(ranking.ranking))
        else:
            locale = locale_by_ranking.get(ranking.id)
            bucket = getattr(locale, "tts_bucket", None) or default_bucket
            key = getattr(locale, "tts_key", None)
            if not key:
                raise RuntimeError(
                    f"Missing {language} intro key for ranking "
                    f"{ranking.ranking}"
                )

        assets.append(
            IntroAsset(
                ranking=int(ranking.ranking),
                track_name=track.track_name or "",
                artist_name=(
                    artist.artist_name
                    or track.artist_display_name
                    or ""
                ),
                bucket=bucket,
                key=key,
            )
        )

    return assets


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_descendant(path: Path, parent: Path) -> None:
    resolved_path = path.resolve()
    resolved_parent = parent.resolve()
    if (
        resolved_path != resolved_parent
        and resolved_parent not in resolved_path.parents
    ):
        raise RuntimeError(f"Unsafe path outside batch directory: {path}")


def source_originals(
    manifest_path: Path | None,
) -> dict[tuple[str, str], dict[str, Any]]:
    if manifest_path is None:
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("Source manifest has no files")
    return {
        (str(row["bucket"]), str(row["key"])): row
        for row in files
    }


def download_original(
    asset: IntroAsset,
    original_root: Path,
    source_by_key: dict[tuple[str, str], dict[str, Any]],
) -> Path:
    destination = original_root / asset.bucket / asset.key
    ensure_descendant(destination, original_root)
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    source_row = source_by_key.get((asset.bucket, asset.key))
    if source_by_key:
        if source_row is None:
            raise RuntimeError(
                f"Missing source-manifest original: "
                f"{asset.bucket}/{asset.key}"
            )
        source = Path(str(source_row["original_path"]))
        expected_sha256 = str(source_row["original_sha256"])
        if not source.exists():
            raise FileNotFoundError(
                f"Source-manifest original is missing: {source}"
            )
        if sha256(source) != expected_sha256:
            raise RuntimeError(
                f"Source-manifest checksum mismatch: {source}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if sha256(destination) != expected_sha256:
            raise RuntimeError(
                f"Copied-original checksum mismatch: {destination}"
            )
        return destination

    data = supabase.storage.from_(asset.bucket).download(asset.key)
    if not data:
        raise RuntimeError(f"Empty download: {asset.bucket}/{asset.key}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination


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
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-1000:] or "FFmpeg failed")
    return loudnorm_payload(f"{result.stdout}\n{result.stderr}")


def normalize_two_pass(
    source: Path,
    destination: Path,
    *,
    target_lufs: float,
    true_peak: float,
    lra: float,
    bitrate_kbps: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    before = measure(
        source,
        target_lufs=target_lufs,
        true_peak=true_peak,
        lra=lra,
    )
    if destination.exists() and destination.stat().st_size > 0:
        after = measure(
            destination,
            target_lufs=target_lufs,
            true_peak=true_peak,
            lra=lra,
        )
        return before, after

    destination.parent.mkdir(parents=True, exist_ok=True)
    filter_value = (
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:"
        f"measured_I={finite_number(before, 'input_i')}:"
        f"measured_TP={finite_number(before, 'input_tp')}:"
        f"measured_LRA={finite_number(before, 'input_lra')}:"
        f"measured_thresh={finite_number(before, 'input_thresh')}:"
        f"offset={finite_number(before, 'target_offset')}:"
        "linear=true:print_format=json"
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


def target_name(value: float) -> str:
    return f"{value:.1f}".replace("-", "minus_").replace(".", "_")


def write_manifests(
    rows: list[ManifestRow],
    json_path: Path,
    csv_path: Path,
    metadata: dict[str, Any],
) -> None:
    payload = dict(metadata)
    payload["files"] = [asdict(row) for row in rows]
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(asdict(rows[0]).keys()),
        )
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


def main() -> None:
    args = parse_args()
    if not (-30.0 <= args.target_lufs <= -12.0):
        raise SystemExit("--target-lufs must be between -30 and -12")
    if not (0.0 <= args.tolerance_lu <= 3.0):
        raise SystemExit("--tolerance-lu must be between 0 and 3")
    if not (0.0 <= args.verification_tolerance_lu <= 2.0):
        raise SystemExit(
            "--verification-tolerance-lu must be between 0 and 2"
        )
    if not (64 <= args.bitrate_kbps <= 320):
        raise SystemExit("--bitrate-kbps must be between 64 and 320")

    batch_root = (
        args.output_root
        / args.slug
        / args.language
        / f"target_{target_name(args.target_lufs)}_lufs"
        / f"bitrate_{args.bitrate_kbps}k"
    )
    original_root = batch_root / "originals"
    candidate_root = batch_root / "candidates"
    json_path = batch_root / "manifest.json"
    csv_path = batch_root / "manifest.csv"
    batch_root.mkdir(parents=True, exist_ok=True)

    assets = load_assets(args.slug, args.language)
    source_by_key = source_originals(args.source_manifest)
    print(
        f"Preparing {len(assets)} {args.language} intros for {args.slug}. "
        f"Target={args.target_lufs:.1f} LUFS, "
        f"tolerance=±{args.tolerance_lu:.1f}, "
        f"bitrate={args.bitrate_kbps} kbps."
    )
    print("This tool cannot upload, delete, or modify remote data.")

    rows: list[ManifestRow] = []
    for index, asset in enumerate(assets, start=1):
        print(
            f"[{index:>2}/{len(assets)}] "
            f"#{asset.ranking:02d} {asset.artist_name} — "
            f"{asset.track_name}"
        )
        row = ManifestRow(
            ranking=asset.ranking,
            track_name=asset.track_name,
            artist_name=asset.artist_name,
            bucket=asset.bucket,
            key=asset.key,
            status="pending",
        )
        try:
            original = download_original(
                asset,
                original_root,
                source_by_key,
            )
            before = measure(
                original,
                target_lufs=args.target_lufs,
                true_peak=args.true_peak,
                lra=args.lra,
            )
            original_lufs = finite_number(before, "input_i")
            adjustment = args.target_lufs - original_lufs

            row.original_path = str(original)
            row.original_size_bytes = original.stat().st_size
            row.original_sha256 = sha256(original)
            row.original_lufs = original_lufs
            row.adjustment_db = adjustment

            if abs(adjustment) <= args.tolerance_lu:
                row.status = "within_tolerance"
            else:
                candidate = candidate_root / asset.bucket / asset.key
                ensure_descendant(candidate, candidate_root)
                _, after = normalize_two_pass(
                    original,
                    candidate,
                    target_lufs=args.target_lufs,
                    true_peak=args.true_peak,
                    lra=args.lra,
                    bitrate_kbps=args.bitrate_kbps,
                )
                candidate_lufs = finite_number(after, "input_i")
                if (
                    abs(candidate_lufs - args.target_lufs)
                    > args.verification_tolerance_lu
                ):
                    raise RuntimeError(
                        f"Candidate verification failed: "
                        f"{candidate_lufs:.2f} LUFS"
                    )

                row.status = "candidate_verified"
                row.candidate_path = str(candidate)
                row.candidate_size_bytes = candidate.stat().st_size
                row.candidate_sha256 = sha256(candidate)
                row.candidate_lufs = candidate_lufs
                row.candidate_true_peak_dbtp = finite_number(
                    after,
                    "input_tp",
                )
        except Exception as exc:
            row.status = "error"
            row.error = str(exc).replace("\r", " ").replace("\n", " ")[:1000]
            print(f"      ERROR: {row.error}")
        rows.append(row)

    metadata = {
        "slug": args.slug,
        "language": args.language,
        "target_lufs": args.target_lufs,
        "tolerance_lu": args.tolerance_lu,
        "verification_tolerance_lu": args.verification_tolerance_lu,
        "true_peak_dbtp": args.true_peak,
        "loudness_range_lu": args.lra,
        "bitrate_kbps": args.bitrate_kbps,
        "remote_write_capability": False,
        "source_manifest": (
            str(args.source_manifest) if args.source_manifest else None
        ),
    }
    write_manifests(rows, json_path, csv_path, metadata)

    verified = sum(row.status == "candidate_verified" for row in rows)
    unchanged = sum(row.status == "within_tolerance" for row in rows)
    errors = sum(row.status == "error" for row in rows)
    print()
    print("Batch preparation summary")
    print("=" * 40)
    print(f"Verified candidates: {verified}")
    print(f"Within tolerance:    {unchanged}")
    print(f"Errors:              {errors}")
    print(f"Manifest:            {json_path}")
    print(f"Original backups:    {original_root}")
    print(f"Candidates:          {candidate_root}")
    print("No remote file or database row was changed.")

    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
