"""TopSpot40 stage 1: read-only full Nostalgia narration audit.

Run from topspot-backend-api:
    python -u topspot_intro_volume_audit_batch.py
Resume by running the SAME command. No Supabase uploads or audio changes.
Requires the existing database environment, ffmpeg, and historical Git tools.
The proposed later preparation policy is lower-only: target -22 LUFS,
leave -21 LUFS or quieter alone; exclude previously adjusted intro assets.
This script DOES NOT implement normalization or upload. Review tools first.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REVISION = "93a4180"
SCRIPT = "backend/scripts/audit_narration_loudness.py"
GENRES = {"country", "pop", "rock", "rnb_soul", "latin_global", "blues_jazz", "folk_acoustic", "tv_themes"}
DECADES = {f"{year}s" for year in range(1950, 2030, 10)}
RUNNER = '''import sys
from pathlib import Path
script, slug, language, output = sys.argv[1:5]
source = sys.stdin.read()
sys.argv = [script, '--slug', slug, '--language', language, '--limit', '0', '--output-root', output]
__file__ = str(Path(script).resolve())
exec(compile(source, script, 'exec'), globals())
'''

def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)

def git_source(name):
    return subprocess.check_output(["git", "show", f"{REVISION}:backend/scripts/{name}"], text=True, encoding="utf-8")

def discover_programs():
    from sqlalchemy import text
    from backend.database import engine
    with engine.connect() as connection:
        slugs = connection.execute(text("SELECT slug FROM decade_genre ORDER BY slug")).scalars().all()
    return sorted({slug for slug in slugs if isinstance(slug, str)
                   and "-" in slug and slug.split("-", 1)[0] in DECADES
                   and slug.split("-", 1)[1] in GENRES})

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-root", type=Path, default=Path("backend/studio/work/intro-volume-full-audit-20261005"))
    parser.add_argument("--slug", help="Optional single program for a pilot, e.g. 1950s-pop")
    parser.add_argument("--language", choices=("en", "es", "pt-BR"), help="Optional single language")
    parser.add_argument("--retry-failed", action="store_true", help="Retry failed jobs; completed audits stay untouched")
    args = parser.parse_args()
    if not Path("backend/database.py").is_file():
        raise SystemExit("Run from the topspot-backend-api repository root.")
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required; no work started.")
    source = git_source("audit_narration_loudness.py")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    slugs = discover_programs()
    expected = {f"{decade}-{genre}" for decade in DECADES for genre in GENRES}
    missing = sorted(expected - set(slugs))
    if args.slug:
        if args.slug not in slugs:
            raise SystemExit(f"Program not found: {args.slug}")
        slugs = [args.slug]
    if not slugs:
        raise SystemExit("No Nostalgia programs found; no work started.")
    languages = [args.language] if args.language else ["en", "es", "pt-BR"]
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    journal = root / "batch-progress.json"
    state = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else {
        "created_at": datetime.now(timezone.utc).isoformat(), "audit_source_sha256": digest, "jobs": {}}
    if state["audit_source_sha256"] != digest:
        raise SystemExit("Audit source changed. Use a new output folder; existing results preserved.")
    state["missing_programs"] = missing
    state["policy_for_later_review"] = {"target_lufs": -22, "leave_at_or_below_lufs": -21,
        "lower_only": True, "exclude_previously_adjusted": True, "normalization_enabled": False}
    save(journal, state)
    # Preserve source for review; never check out or alter existing repository tools.
    review = []
    for name in ("audit_narration_loudness.py", "prepare_intro_normalization_batch.py", "apply_intro_normalization_batch.py"):
        review.append(f"\n{'=' * 70}\n{name}\n{'=' * 70}\n" + git_source(name))
    (root / "tools-review.txt").write_text("\n".join(review), encoding="utf-8")
    print(f"READ-ONLY: {len(slugs)} programs x {len(languages)} languages. Supabase unchanged.", flush=True)
    print("Output:", root, flush=True)
    if missing:
        print("Missing program combinations:", ", ".join(missing), flush=True)
    for slug in slugs:
        for language in languages:
            key = f"{slug}|{language}"
            previous = state["jobs"].get(key, {})
            if previous.get("status") == "complete":
                print("SKIP completed:", key, flush=True)
                continue
            if previous.get("status") == "failed" and not args.retry_failed:
                print("HOLD failed:", key, "(use --retry-failed)", flush=True)
                continue
            # Keep interrupted/failed attempt files instead of overwriting them.
            attempt = int(previous.get("attempt", 0)) + 1
            output = root / "audits" / slug / language / f"attempt-{attempt:02}"
            output.mkdir(parents=True, exist_ok=True)
            job = {"status": "running", "attempt": attempt, "output": str(output)}
            state["jobs"][key] = job
            save(journal, state)
            print("AUDIT:", key, flush=True)
            try:
                with (output / "console.log").open("w", encoding="utf-8") as log:
                    result = subprocess.run([sys.executable, "-u", "-c", RUNNER, SCRIPT, slug, language, str(output)],
                        input=source, text=True, encoding="utf-8", stdout=log, stderr=subprocess.STDOUT)
                reports = list(output.rglob("loudness_report.csv"))
                if result.returncode != 0 or len(reports) != 1:
                    raise RuntimeError(f"Audit exit={result.returncode}; reports={len(reports)}. See console.log.")
                with reports[0].open(encoding="utf-8-sig", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                if not rows:
                    raise RuntimeError("Empty measurement report; held for review.")
                job.update(status="complete", report=str(reports[0]), rows=len(rows),
                    report_sha256=hashlib.sha256(reports[0].read_bytes()).hexdigest())
                print("MEASURED:", key, len(rows), "rows; inspect CSV for individual errors.", flush=True)
            except Exception as error:
                job.update(status="failed", error=str(error))
                print("HELD:", key, str(error), flush=True)
            finally:
                save(journal, state)
    counts = {}
    for job in state["jobs"].values():
        status = job["status"]
        counts[status] = counts.get(status, 0) + 1
    print("BATCH STATUS:", counts, flush=True)
    print("Completed means audit ran; individual missing/error rows still require review.", flush=True)
    print("Share batch-progress.json, tools-review.txt and measurement CSVs for the next stage.", flush=True)
    print("NO AUDIO MODIFIED. NO UPLOADS. NO DATABASE CHANGES.", flush=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped. Progress saved; rerun the same command to continue.", file=sys.stderr)
        sys.exit(130)
