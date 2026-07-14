from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ArtistJob:
    artist_id: int
    name: str


ARTISTS = [
    ArtistJob(777, "Luis Miguel"),
    ArtistJob(1952, "Juan Gabriel"),
    ArtistJob(507, "Pedro Infante"),
    ArtistJob(155, "Merle Haggard"),
    ArtistJob(145, "Buck Owens"),
]


def format_elapsed(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}h {minutes}m {secs}s"

    return f"{minutes}m {secs}s"


def run_artist(
    job: ArtistJob,
    *,
    log_dir: Path,
) -> tuple[bool, float, Path]:
    started = time.monotonic()

    safe_name = (
        job.name.lower()
        .replace(" ", "_")
        .replace("-", "_")
    )
    log_path = log_dir / f"{safe_name}.log"

    command = [
        sys.executable,
        "-m",
        "backend.studio.build_review_package",
        "--artist-id",
        str(job.artist_id),
        "--language",
        "en",
    ]

    print()
    print("=" * 80)
    print(f"Starting: {job.name} (artist ID {job.artist_id})")
    print(f"Log:      {log_path}")
    print("=" * 80)

    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"Artist: {job.name}\n")
        log_file.write(f"Artist ID: {job.artist_id}\n")
        log_file.write(f"Started: {datetime.now().isoformat()}\n\n")
        log_file.flush()

        result = subprocess.run(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

    elapsed = time.monotonic() - started
    success = result.returncode == 0

    symbol = "✓" if success else "✗"
    status = "COMPLETE" if success else "FAILED"

    print(
        f"{symbol} {job.name}: {status} "
        f"({format_elapsed(elapsed)})"
    )

    return success, elapsed, log_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a sequential TopSpot Studio premium-artist night shift."
        )
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop the shift after the first failed artist.",
    )
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("backend/studio/logs") / f"night_shift_{timestamp}"
    log_dir.mkdir(parents=True, exist_ok=True)

    shift_started = time.monotonic()
    results: list[tuple[ArtistJob, bool, float, Path]] = []

    print()
    print("#" * 80)
    print("TOPSPOT STUDIO — NIGHT SHIFT")
    print("#" * 80)
    print(f"Artists: {len(ARTISTS)}")
    print(f"Logs:    {log_dir}")

    for job in ARTISTS:
        success, elapsed, log_path = run_artist(
            job,
            log_dir=log_dir,
        )
        results.append((job, success, elapsed, log_path))

        if not success and args.stop_on_error:
            print("Stopping because --stop-on-error was supplied.")
            break

    total_elapsed = time.monotonic() - shift_started
    completed = sum(1 for _, success, _, _ in results if success)
    failed = len(results) - completed

    report_path = log_dir / "shift_report.txt"

    lines = [
        "TOPSPOT STUDIO NIGHT SHIFT REPORT",
        "=" * 50,
        "",
    ]

    for job, success, elapsed, log_path in results:
        symbol = "COMPLETE" if success else "FAILED"
        lines.append(
            f"{symbol:8}  {job.name:20}  "
            f"{format_elapsed(elapsed):>12}  {log_path}"
        )

    lines.extend(
        [
            "",
            f"Completed: {completed}",
            f"Failed:    {failed}",
            f"Elapsed:   {format_elapsed(total_elapsed)}",
            "",
        ]
    )

    report_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print()
    print("#" * 80)
    print("NIGHT SHIFT COMPLETE")
    print("#" * 80)
    print(f"Completed: {completed}")
    print(f"Failed:    {failed}")
    print(f"Elapsed:   {format_elapsed(total_elapsed)}")
    print(f"Report:    {report_path}")


if __name__ == "__main__":
    main()
