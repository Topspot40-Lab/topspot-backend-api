"""Read-only, intro-only audit; reuse the original batch journal.

Run from topspot-backend-api: python -u topspot_intro_volume_audit_fast.py
Stop the original runner first. Completed full audits are retained.
No normalization, uploads, or database writes are performed.
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
DEFAULT_ROOT = Path("backend/studio/work/intro-volume-full-audit-20261005")
GENRES = {"country", "pop", "rock", "rnb_soul", "latin_global", "blues_jazz", "folk_acoustic", "tv_themes"}
DECADES = {f"{year}s" for year in range(1950, 2030, 10)}
RUNNER = r'''
import sys, types
from pathlib import Path
script, slug, language, output = sys.argv[1:5]
source = sys.stdin.read()
module = types.ModuleType("_topspot_intro_audit")
module.__file__ = str(Path(script).resolve())
sys.modules[module.__name__] = module
exec(compile(source, script, "exec"), module.__dict__)
original_load = module.load_assets
def intros_only(*args, **kwargs):
    assets, missing = original_load(*args, **kwargs)
    return [asset for asset in assets if asset.category == "intro"], {"intro": missing.get("intro", 0)}
module.load_assets = intros_only
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
        slugs = connection.execute(text("SELECT slug FROM decade_genre ORDER BY slug")).scalars().all()
    return sorted({slug for slug in slugs if isinstance(slug, str) and "-" in slug
                   and slug.split("-", 1)[0] in DECADES and slug.split("-", 1)[1] in GENRES})


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
        return {"status": "complete", "report": str(reports[0]), "rows": len(rows),
                "report_sha256": hashlib.sha256(reports[0].read_bytes()).hexdigest(),
                "audit_scope": "intro_only"}
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=2)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    if not Path("backend/database.py").is_file():
        raise SystemExit("Run from the topspot-backend-api repository root.")
    if not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")):
        raise SystemExit("ffmpeg and ffprobe are required.")
    source = subprocess.check_output(["git", "show", f"{REVISION}:{SCRIPT}"], text=True, encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "fast-audit.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"Fast runner lock exists: {lock}. Check for a running process before removing it.")
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
    slugs = discover_programs()
    if not slugs:
        raise SystemExit("No Nostalgia programs found.")
    state["missing_programs"] = sorted({f"{decade}-{genre}" for decade in DECADES for genre in GENRES} - set(slugs))
    state["policy_for_later_review"] = {"target_lufs": -22, "leave_at_or_below_lufs": -21,
        "lower_only": True, "exclude_previously_adjusted": True, "normalization_enabled": False}
    pending = []
    skipped = held = 0
    for slug in slugs:
        for language in ("en", "es", "pt-BR"):
            key = f"{slug}|{language}"
            previous = state["jobs"].get(key, {})
            if previous.get("status") == "complete":
                if not Path(previous.get("report", "")).is_file():
                    raise SystemExit(f"Completed report missing: {key}; nothing overwritten.")
                skipped += 1
            elif previous.get("status") == "failed" and not args.retry_failed:
                held += 1
            else:
                pending.append((slug, language, key))
    state["runner"] = "intro_only_parallel_v1"
    save(journal, state)
    print(f"READ-ONLY, INTROS ONLY: {len(slugs)} programs x 3 languages; {args.workers} workers.", flush=True)
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
                               "output": str(output), "audit_scope": "intro_only"}
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
    from collections import Counter
    print("BATCH STATUS:", dict(Counter(job["status"] for job in state["jobs"].values())), flush=True)
    print("Review individual CSV errors. NO AUDIO MODIFIED. NO UPLOADS. NO DATABASE CHANGES.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped. Progress saved; rerun the FAST command to continue.", file=sys.stderr)
        sys.exit(130)
