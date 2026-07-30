from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import (
    Artist,
    ArtistLocale,
    DecadeGenre,
    Track,
    TrackLocale,
    TrackRanking,
    TrackRankingLocale,
)
from backend.services.radio_runtime import (
    build_artist_filename,
    build_detail_filename,
    key_for,
)
from backend.services.supabase_client import supabase


DEFAULT_OUTPUT_ROOT = Path("backend/studio/work/narration_loudness_audit")
DEFAULT_BUCKETS = {
    "en": "audio-en",
    "es": "audio-es",
    "pt-BR": "audio-ptbr",
}


@dataclass(frozen=True)
class AudioAsset:
    category: str
    ranking: int | None
    track_name: str
    artist_name: str
    bucket: str
    key: str


@dataclass
class AuditResult:
    asset: AudioAsset
    duration_seconds: float | None = None
    integrated_lufs: float | None = None
    true_peak_dbtp: float | None = None
    loudness_range_lu: float | None = None
    threshold_lufs: float | None = None
    target_offset_db: float | None = None
    status: str = "ok"
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download English Nostalgia narration MP3s and measure their "
            "loudness. This command is read-only: it never uploads or changes "
            "Supabase or the database."
        )
    )
    parser.add_argument("--slug", default="1960s-pop")
    parser.add_argument(
        "--language",
        choices=tuple(DEFAULT_BUCKETS),
        default="en",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of ranked tracks to audit. Use 0 for the complete program.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    return parser.parse_args()


def decade_genre_intro_key(slug: str, ranking: int) -> str:
    return f"intro/{slug.replace('-', '_')}_{ranking:02d}.mp3"


def optional_key(category: str, filename: str | None) -> str | None:
    return key_for(category, filename) if filename else None


def load_assets(
    slug: str,
    limit: int,
    language: str,
) -> tuple[list[AudioAsset], dict[str, int]]:
    with Session(engine) as session:
        decade_genre = session.exec(
            select(DecadeGenre).where(DecadeGenre.slug == slug)
        ).first()
        if not decade_genre:
            raise SystemExit(f"DecadeGenre not found: {slug}")

        statement = (
            select(TrackRanking, Track, Artist)
            .join(Track, TrackRanking.track_id == Track.id)
            .join(Artist, Track.artist_id == Artist.id)
            .where(TrackRanking.decade_genre_id == decade_genre.id)
            .order_by(TrackRanking.ranking)
        )
        rows = list(session.exec(statement).all())
        if limit > 0:
            rows = rows[:limit]

        ranking_ids = [ranking.id for ranking, _, _ in rows]
        track_ids = [track.id for _, track, _ in rows]
        artist_ids = list({artist.id for _, _, artist in rows})

        intro_locales = (
            session.exec(
                select(TrackRankingLocale).where(
                    TrackRankingLocale.track_ranking_id.in_(ranking_ids),
                    TrackRankingLocale.language_code == language,
                )
            ).all()
            if language != "en" and ranking_ids
            else []
        )
        track_locales = (
            session.exec(
                select(TrackLocale).where(
                    TrackLocale.track_id.in_(track_ids),
                    TrackLocale.language_code == language,
                )
            ).all()
            if language != "en" and track_ids
            else []
        )
        artist_locales = (
            session.exec(
                select(ArtistLocale).where(
                    ArtistLocale.artist_id.in_(artist_ids),
                    ArtistLocale.language_code == language,
                )
            ).all()
            if language != "en" and artist_ids
            else []
        )

    intro_by_ranking = {
        locale.track_ranking_id: locale for locale in intro_locales
    }
    track_locale_by_track = {
        locale.track_id: locale for locale in track_locales
    }
    artist_locale_by_artist = {
        locale.artist_id: locale for locale in artist_locales
    }

    assets: list[AudioAsset] = []
    artist_assets: dict[str, AudioAsset] = {}
    missing = {
        "intro": 0,
        "detail_long": 0,
        "detail_short": 0,
        "artist": 0,
    }
    default_bucket = DEFAULT_BUCKETS[language]

    def add_asset(
        *,
        category: str,
        ranking: int,
        track_name: str,
        artist_name: str,
        bucket: str | None,
        key: str | None,
    ) -> None:
        if not key:
            missing[category] += 1
            return
        assets.append(
            AudioAsset(
                category=category,
                ranking=ranking,
                track_name=track_name,
                artist_name=artist_name,
                bucket=bucket or default_bucket,
                key=key,
            )
        )

    for ranking, track, artist in rows:
        rank = int(ranking.ranking)
        track_name = track.track_name or ""
        artist_name = artist.artist_name or track.artist_display_name or ""

        if language == "en":
            intro_bucket = default_bucket
            intro_key = decade_genre_intro_key(slug, rank)
            detail_bucket = default_bucket
            long_detail_key = optional_key(
                "detail",
                build_detail_filename(track.spotify_track_id),
            )
            short_detail_key = track.short_detail_tts_key
            artist_bucket = default_bucket
            artist_key = optional_key(
                "artist",
                build_artist_filename(artist.spotify_artist_id),
            )
        else:
            intro_locale = intro_by_ranking.get(ranking.id)
            track_locale = track_locale_by_track.get(track.id)
            artist_locale = artist_locale_by_artist.get(artist.id)

            intro_bucket = getattr(intro_locale, "tts_bucket", None)
            intro_key = getattr(intro_locale, "tts_key", None)
            detail_bucket = getattr(track_locale, "tts_bucket", None)
            long_detail_key = getattr(track_locale, "tts_key", None)
            short_detail_key = getattr(
                track_locale,
                "short_detail_tts_key",
                None,
            )
            artist_bucket = getattr(artist_locale, "tts_bucket", None)
            artist_key = getattr(artist_locale, "tts_key", None)

        add_asset(
            category="intro",
            ranking=rank,
            track_name=track_name,
            artist_name=artist_name,
            bucket=intro_bucket,
            key=intro_key,
        )
        add_asset(
            category="detail_long",
            ranking=rank,
            track_name=track_name,
            artist_name=artist_name,
            bucket=detail_bucket,
            key=long_detail_key,
        )
        add_asset(
            category="detail_short",
            ranking=rank,
            track_name=track_name,
            artist_name=artist_name,
            bucket=detail_bucket,
            key=short_detail_key,
        )

        if artist_key and artist_key not in artist_assets:
            artist_assets[artist_key] = AudioAsset(
                category="artist",
                ranking=rank,
                track_name=track_name,
                artist_name=artist_name,
                bucket=artist_bucket or default_bucket,
                key=artist_key,
            )
        elif not artist_key:
            missing["artist"] += 1

    assets.extend(artist_assets.values())
    return assets, missing


def download(asset: AudioAsset, download_root: Path) -> Path:
    destination = download_root / asset.bucket / asset.key
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    data = supabase.storage.from_(asset.bucket).download(asset.key)
    if not data:
        raise RuntimeError(f"Empty download: {asset.bucket}/{asset.key}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination


def run_process(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def duration_seconds(path: Path) -> float:
    result = run_process(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return float(result.stdout.strip())


def number(value: object) -> float | None:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def loudness(path: Path) -> dict[str, float | None]:
    result = run_process(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ]
    )
    combined = f"{result.stdout}\n{result.stderr}"
    matches = re.findall(r"\{\s*\"input_i\".*?\}", combined, flags=re.DOTALL)
    if not matches:
        raise RuntimeError(
            (result.stderr.strip() or "FFmpeg loudnorm output was not found")[-1000:]
        )

    payload = json.loads(matches[-1])
    return {
        "integrated_lufs": number(payload.get("input_i")),
        "true_peak_dbtp": number(payload.get("input_tp")),
        "loudness_range_lu": number(payload.get("input_lra")),
        "threshold_lufs": number(payload.get("input_thresh")),
        "target_offset_db": number(payload.get("target_offset")),
    }


def audit(asset: AudioAsset, download_root: Path) -> AuditResult:
    result = AuditResult(asset=asset)
    try:
        path = download(asset, download_root)
        result.duration_seconds = duration_seconds(path)
        measured = loudness(path)
        result.integrated_lufs = measured["integrated_lufs"]
        result.true_peak_dbtp = measured["true_peak_dbtp"]
        result.loudness_range_lu = measured["loudness_range_lu"]
        result.threshold_lufs = measured["threshold_lufs"]
        result.target_offset_db = measured["target_offset_db"]
    except Exception as exc:
        result.status = "error"
        result.error = str(exc).replace("\r", " ").replace("\n", " ")[:1000]
    return result


def write_csv(results: Iterable[AuditResult], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "category",
                "ranking",
                "track_name",
                "artist_name",
                "bucket",
                "key",
                "duration_seconds",
                "integrated_lufs",
                "true_peak_dbtp",
                "loudness_range_lu",
                "threshold_lufs",
                "target_offset_db",
                "status",
                "error",
            ],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "category": result.asset.category,
                    "ranking": result.asset.ranking,
                    "track_name": result.asset.track_name,
                    "artist_name": result.asset.artist_name,
                    "bucket": result.asset.bucket,
                    "key": result.asset.key,
                    "duration_seconds": result.duration_seconds,
                    "integrated_lufs": result.integrated_lufs,
                    "true_peak_dbtp": result.true_peak_dbtp,
                    "loudness_range_lu": result.loudness_range_lu,
                    "threshold_lufs": result.threshold_lufs,
                    "target_offset_db": result.target_offset_db,
                    "status": result.status,
                    "error": result.error,
                }
            )


def format_number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def print_summary(results: list[AuditResult]) -> None:
    categories = sorted({result.asset.category for result in results})
    print()
    print("Narration loudness summary (measurement only)")
    print("=" * 72)
    print(
        f"{'category':<15} {'ok':>4} {'errors':>6} "
        f"{'mean LUFS':>10} {'median':>9} {'min':>8} {'max':>8} {'spread':>8}"
    )
    print("-" * 72)

    for category in categories:
        category_results = [
            result for result in results if result.asset.category == category
        ]
        values = [
            result.integrated_lufs
            for result in category_results
            if result.status == "ok" and result.integrated_lufs is not None
        ]
        errors = sum(result.status != "ok" for result in category_results)

        if values:
            mean = statistics.fmean(values)
            median = statistics.median(values)
            minimum = min(values)
            maximum = max(values)
            spread = maximum - minimum
        else:
            mean = median = minimum = maximum = spread = None

        print(
            f"{category:<15} {len(values):>4} {errors:>6} "
            f"{format_number(mean):>10} {format_number(median):>9} "
            f"{format_number(minimum):>8} {format_number(maximum):>8} "
            f"{format_number(spread):>8}"
        )


def main() -> None:
    args = parse_args()
    if args.limit < 0:
        raise SystemExit("--limit must be 0 or greater")

    audit_root = args.output_root / args.slug / args.language
    download_root = audit_root / "downloads"
    report_path = audit_root / "loudness_report.csv"

    assets, missing = load_assets(args.slug, args.limit, args.language)
    if not assets:
        raise SystemExit(f"No audio assets found for {args.slug}")

    print(
        f"Auditing {len(assets)} {args.language} narration files for "
        f"{args.slug}. "
        "No Supabase or database data will be changed."
    )
    if any(missing.values()):
        missing_text = ", ".join(
            f"{category}={count}"
            for category, count in missing.items()
            if count
        )
        print(f"Missing keys excluded from measurement: {missing_text}")

    results: list[AuditResult] = []
    for index, asset in enumerate(assets, start=1):
        print(
            f"[{index:>3}/{len(assets)}] "
            f"{asset.category:<12} {asset.artist_name} — {asset.track_name}"
        )
        result = audit(asset, download_root)
        if result.status != "ok":
            print(f"      ERROR: {result.error}")
        results.append(result)

    write_csv(results, report_path)
    print_summary(results)
    print()
    print(f"CSV report: {report_path}")
    print(f"Downloaded copies: {download_root}")
    print("Completed read-only audit. Nothing was uploaded or replaced.")


if __name__ == "__main__":
    main()
