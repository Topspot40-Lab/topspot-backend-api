"""Read-only Collections ranked-intro loudness audit (EN/ES/PT-BR).

Run from topspot-backend-api. Use --pilot to measure the first collection.
Rerun without --pilot for all collections; completed audits are retained.
Uses the existing Collections playback filename builder and the same
FFmpeg measurements as the Nostalgia audit. No normalization or uploads.
Scope: ranked track intros (ranks 1-100), not collection stories/set intros.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from pathlib import Path

REVISION = "93a4180"
SCRIPT = "backend/scripts/audit_narration_loudness.py"
DEFAULT_ROOT = Path("backend/studio/work/collections-intro-volume-audit-20261007")
RUNNER = r'''
import sys, types
from pathlib import Path
script, slug, language, output = sys.argv[1:5]
source = sys.stdin.read()
module = types.ModuleType("_topspot_collection_intro_audit")
module.__file__ = str(Path(script).resolve())
sys.modules[module.__name__] = module
exec(compile(source, script, "exec"), module.__dict__)
from sqlalchemy import text
from backend.database import engine
from backend.services.radio_runtime import collection_intro_jobs

def collection_assets(slug, limit, language):
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT ctr.ranking, t.track_name, a.artist_name
            FROM collection c
            JOIN collection_track_ranking ctr ON ctr.collection_id=c.id
            JOIN track t ON t.id=ctr.track_id
            JOIN artist a ON a.id=t.artist_id
            WHERE c.slug=:slug AND ctr.ranking BETWEEN 1 AND 100
            ORDER BY ctr.ranking
        """), {"slug": slug}).mappings().all()
    if limit > 0:
        rows = rows[:limit]
    assets, missing = [], {"intro": 0}
    for row in rows:
        rank = int(row["ranking"])
        jobs = collection_intro_jobs(lang=language, collection_slug=slug, rank=rank)
        if not jobs:
            missing["intro"] += 1
            continue
        for bucket, key, *_ in jobs:
            if not bucket or not key:
                missing["intro"] += 1
                continue
            assets.append(module.AudioAsset(category="intro", ranking=rank,
                track_name=row["track_name"] or "", artist_name=row["artist_name"] or "",
                bucket=bucket, key=key))
    return assets, missing

module.load_assets = collection_assets
sys.argv = [script, "--slug", slug, "--language", language, "--limit", "0", "--output-root", output]
module.main()
'''



def save(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def discover_programs():
    from sqlalchemy import text
    from backend.database import engine
    with engine.connect() as connection:
        slugs = connection.execute(text("""
            SELECT DISTINCT c.slug FROM collection c
            JOIN collection_track_ranking ctr ON ctr.collection_id=c.id
            WHERE ctr.ranking BETWEEN 1 AND 100
            ORDER BY c.slug
        """)).scalars().all()
    return [slug for slug in slugs if isinstance(slug, str) and slug.strip()]


def run_audit(source, slug, language, output, stop, processes, process_lock):
    try:
        with (output / "console.log").open("w", encoding="utf-8") as log:
            with process_lock:
                if stop.is_set():
                    return {"status": "interrupted"}
                options = {}
                if os.name == "nt":
                    options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    options["start_new_session"] = True
                process = subprocess.Popen(
                    [sys.executable, "-u", "-c", RUNNER, SCRIPT, slug, language, str(output)],
                    stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", **options)
                processes.add(process)
            try:
                process.communicate(source)
            finally:
                with process_lock:
                    processes.discard(process)
        if stop.is_set():
            return {"status": "interrupted"}
        reports = list(output.rglob("loudness_report.csv"))
        if process.returncode != 0 or len(reports) != 1:
            raise RuntimeError(f"Audit exit={process.returncode}; reports={len(reports)}. See console.log.")
        with reports[0].open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows or any(row.get("category") != "intro" for row in rows):
            raise RuntimeError("Expected a nonempty intro-only report; held for review.")
        return {"status": "complete", "report": str(reports[0]), "rows": len(rows), "errors": sum(row.get("status") != "ok" for row in rows),
                "report_sha256": hashlib.sha256(reports[0].read_bytes()).hexdigest(),
                "audit_scope": "collections_ranked_intro_only"}
    except Exception as error:
        return {"status": "interrupted" if stop.is_set() else "failed", "error": str(error)}


def stop_children(processes, process_lock):
    with process_lock:
        active = list(processes)
    for process in active:
        if process.poll() is not None:
            continue
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def write_combined_report(root, state):
    rows = []
    for key, job in sorted(state["jobs"].items()):
        if job.get("status") != "complete":
            continue
        slug, language = key.rsplit("|", 1)
        report = Path(job["report"])
        if hashlib.sha256(report.read_bytes()).hexdigest() != job["report_sha256"]:
            raise RuntimeError(f"Saved report changed: {key}")
        with report.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                measured = row.get("integrated_lufs", "")
                try:
                    value = float(measured)
                    import math
                    valid = math.isfinite(value) and row.get("status") == "ok"
                except (ValueError, TypeError):
                    valid = False
                rows.append({"collection_slug": slug, "language": language, **row,
                    "later_review": "lower_candidate" if valid and value > -21 else "leave_unchanged" if valid else "measurement_error"})
    if rows:
        destination = root / "collections-loudness-report.csv"
        temporary = destination.with_suffix(".csv.tmp")
        with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=2)
    parser.add_argument("--retry-failed", action="store_true", help="Retry failed jobs and reports containing individual errors")
    parser.add_argument("--pilot", action="store_true", help="Audit the first collection in all selected languages")
    parser.add_argument("--slug", help="Audit one specific collection slug")
    parser.add_argument("--language", choices=("en", "es", "pt-BR"))
    args = parser.parse_args()
    if not Path("backend/database.py").is_file():
        raise SystemExit("Run from the topspot-backend-api repository root.")
    if not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")):
        raise SystemExit("ffmpeg and ffprobe are required.")
    source = subprocess.check_output(["git", "show", f"{REVISION}:{SCRIPT}"], text=True, encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "collections-audit.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"Collections runner lock exists: {lock}. Check for a running process before removing it.")
    os.close(descriptor)
    try:
        execute(args, root, source, digest)
    finally:
        lock.unlink()


def execute(args, root, source, digest):
    journal = root / "batch-progress.json"
    state = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else {
        "created_at": datetime.now(timezone.utc).isoformat(), "audit_source_sha256": digest, "jobs": {}}
    if state.get("audit_source_sha256") != digest:
        raise SystemExit("Audit source changed; existing results preserved. Do not resume with a different source.")
    runner_digest = hashlib.sha256(RUNNER.encode("utf-8")).hexdigest()
    if state.get("collections_runner_sha256", runner_digest) != runner_digest:
        raise SystemExit("Collections asset lookup changed; use a new output folder.")
    state["collections_runner_sha256"] = runner_digest
    (root / "measurement-source.py").write_text(source, encoding="utf-8")
    slugs = discover_programs()
    if not slugs:
        raise SystemExit("No Collections with ranked tracks found.")
    if args.slug:
        if args.slug not in slugs:
            raise SystemExit(f"Collection not found: {args.slug}")
        slugs = [args.slug]
    elif args.pilot:
        slugs = slugs[:1]
    if state.get("scope", "collections_ranked_intro_only") != "collections_ranked_intro_only":
        raise SystemExit("Output folder belongs to another audit. Use a separate folder.")
    state["scope"] = "collections_ranked_intro_only"
    languages = [args.language] if args.language else ["en", "es", "pt-BR"]
    state["policy_for_later_review"] = {"target_lufs": -22, "leave_at_or_below_lufs": -21,
        "lower_only": True, "exclude_previously_adjusted": True, "normalization_enabled": False}
    pending = []
    skipped = held = 0
    for slug in slugs:
        for language in languages:
            key = f"{slug}|{language}"
            previous = state["jobs"].get(key, {})
            if previous.get("status") == "complete" and not (args.retry_failed and previous.get("errors", 0)):
                if not Path(previous.get("report", "")).is_file():
                    raise SystemExit(f"Completed report missing: {key}; nothing overwritten.")
                skipped += 1
            elif previous.get("status") == "failed" and not args.retry_failed:
                held += 1
            else:
                pending.append((slug, language, key))
    state["runner"] = "collections_intro_parallel_v1"
    save(journal, state)
    print(f"READ-ONLY, INTROS ONLY: {len(slugs)} collections x {len(languages)} languages; {args.workers} workers.", flush=True)
    print(f"Retained completed audits: {skipped}; pending: {len(pending)}; held failed: {held}", flush=True)
    print("Output:", root, flush=True)
    stop = threading.Event()
    processes, process_lock = set(), threading.Lock()
    pool = ThreadPoolExecutor(max_workers=args.workers)
    futures = {}
    iterator = iter(pending)
    def start_next():
        try:
            slug, language, key = next(iterator)
        except StopIteration:
            return False
        attempt = int(state["jobs"].get(key, {}).get("attempt", 0)) + 1
        output = root / "audits" / slug / language / f"attempt-{attempt:02}"
        output.mkdir(parents=True, exist_ok=False)
        state["jobs"][key] = {"status": "running", "attempt": attempt,
                               "output": str(output), "audit_scope": "collections_ranked_intro_only"}
        save(journal, state)
        print("AUDIT:", key, flush=True)
        futures[pool.submit(run_audit, source, slug, language, output, stop, processes, process_lock)] = key
        return True
    try:
        for _ in range(args.workers):
            start_next()
        while futures:
            done, _ = wait(futures, timeout=0.5, return_when=FIRST_COMPLETED)
            for future in done:
                key = futures.pop(future)
                result = future.result()
                state["jobs"][key].update(result)
                save(journal, state)
                print("MEASURED:" if result["status"] == "complete" else "HELD:", key,
                      result.get("rows", result.get("error", "")), flush=True)
                start_next()
    finally:
        stop.set()
        stop_children(processes, process_lock)
        pool.shutdown(wait=True)
        for future, key in futures.items():
            if future.done() and not future.cancelled():
                state["jobs"][key].update(future.result())
        save(journal, state)
    write_combined_report(root, state)
    from collections import Counter
    print("BATCH STATUS:", dict(Counter(job["status"] for job in state["jobs"].values())), flush=True)
    print("Combined report:", root / "collections-loudness-report.csv", flush=True)
    print("Individual audio errors:", sum(job.get("errors", 0) for job in state["jobs"].values() if job["status"] == "complete"), flush=True)
    print("NO AUDIO MODIFIED. NO UPLOADS. NO DATABASE CHANGES.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped. Progress saved; rerun the same Collections command to continue.", file=sys.stderr)
        sys.exit(130)
