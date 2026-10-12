"""Prepare quieter Collections intros locally from the completed audit. No uploads or database writes.
Rerun the same command to resume. Keep the review and output folder together.
"""
from __future__ import annotations
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import threading

STOP = threading.Event()


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, data):
    tmp = path.with_suffix('.tmp.json')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def run(args):
    p = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    if p.returncode:
        raise RuntimeError(p.stderr[-1800:])
    return p


def measure(path):
    p = run(['ffmpeg', '-hide_banner', '-nostdin', '-threads', '1', '-filter_threads', '1', '-i', str(path), '-af',
             'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'])
    start = p.stderr.rfind('{')
    data = json.loads(p.stderr[start:p.stderr.rfind('}')+1])
    result = {key: float(data[key]) for key in ('input_i', 'input_tp')}
    if not all(math.isfinite(v) for v in result.values()):
        raise RuntimeError('Nonfinite candidate measurements')
    return result


def duration(path):
    value = float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                      '-of', 'default=noprint_wrappers=1:nokey=1', str(path)]).stdout)
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError('Invalid audio duration')
    return value


def prepare(row, root):
    if STOP.is_set():
        return dict(row, status='interrupted')
    folder = root / 'assets' / row['bucket'] / row['key']
    folder.mkdir(parents=True, exist_ok=True)
    record = folder / 'record.json'
    source = Path(row['source'])
    original = folder / 'original.mp3'
    candidate = folder / 'candidate.mp3'
    try:
        if record.exists():
            old = json.loads(record.read_text(encoding='utf-8'))
            if old.get('status') == 'candidate_verified':
                if old['source_sha256'] != row['source_sha256'] or sha(original) != old['source_sha256'] or sha(candidate) != old['candidate_sha256']:
                    raise RuntimeError('Completed asset checksum changed; held for review')
                return old
        if sha(source) != row['source_sha256']:
            raise RuntimeError('Audited source changed; held for review')
        if not original.exists():
            tmp = folder / 'original.partial.mp3'
            shutil.copyfile(source, tmp)
            if sha(tmp) != row['source_sha256']:
                raise RuntimeError('Original copy checksum mismatch')
            tmp.replace(original)
        if sha(original) != row['source_sha256']:
            raise RuntimeError('Preserved original checksum mismatch')
        before = float(row['integrated_lufs'])
        gain = -22.0 - before
        partial = folder / 'candidate.partial.mp3'
        # MP3 encoding and loudness gating can shift the measured result.
        # Correct the gain using the result, always encoding from the original.
        for attempt in range(3):
            if not math.isfinite(gain) or gain >= 0:
                raise RuntimeError('Correction would raise original volume; held')
            run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                 '-threads', '1', '-filter_threads', '1', '-i', str(original), '-map', '0:a:0', '-af', f'volume={gain:.6f}dB',
                 '-c:a', 'libmp3lame', '-b:a', '128k', '-map_metadata', '0', str(partial)])
            stats = measure(partial)
            if abs(stats['input_i'] + 22.0) <= 0.5:
                break
            if attempt < 2:
                gain += -22.0 - stats['input_i']
        length = duration(partial)
        original_length = float(row['duration_seconds'])
        if not math.isfinite(original_length) or original_length <= 0:
            raise RuntimeError('Invalid audited original duration')
        if abs(stats['input_i'] + 22.0) > 0.5 or stats['input_i'] >= before:
            raise RuntimeError(f"Candidate loudness verification failed: {stats['input_i']} LUFS")
        if stats['input_tp'] > -1.0 or stats['input_tp'] > float(row['true_peak_dbtp']) + 0.3:
            raise RuntimeError('Candidate true peak verification failed')
        if abs(length - original_length) > 0.15:
            raise RuntimeError('Candidate duration verification failed')
        partial.replace(candidate)
        result = dict(row, status='candidate_verified', gain_db=gain,
                      original_path=str(original.resolve()), candidate_path=str(candidate.resolve()),
                      candidate_sha256=sha(candidate), candidate_lufs=stats['input_i'],
                      candidate_true_peak_dbtp=stats['input_tp'], candidate_duration_seconds=length)
        save(record, result)
        return result
    except Exception as error:
        return dict(row, status='failed', error=str(error))



AUDIT_ROOT = Path('backend/studio/work/collections-intro-volume-audit-20261007')
OUTPUT_ROOT = Path('backend/studio/work/collections-intro-minus22-20261007')
EXPECTED_REPORT_SHA = '35615ab0a54e64fec24d36166ff2448902d69303dcc9134a007f49bf194c2a90'
EXPECTED_COUNTS = {'audio-en': 2300, 'audio-es': 2300, 'audio-ptbr': 2300}


def build_review(audit_root):
    report = audit_root / 'collections-loudness-report.csv'
    if sha(report) != EXPECTED_REPORT_SHA:
        raise RuntimeError('Audit report differs from the reviewed 6,900-file report; nothing prepared')
    state = json.loads((audit_root / 'batch-progress.json').read_text(encoding='utf-8'))
    jobs = state['jobs']
    if len(jobs) != 156 or any(j.get('status') != 'complete' or j.get('errors') != 0 for j in jobs.values()):
        raise RuntimeError('Expected 156 completed audit jobs with zero audio errors')
    # Check the saved per-job reports and require every combined row to match.
    originals = {}
    for name, job in jobs.items():
        job_report = Path(job['report']).resolve()
        if not job_report.is_relative_to(audit_root.resolve()) or sha(job_report) != job['report_sha256']:
            raise RuntimeError('Audit job report path/checksum changed: ' + name)
        with job_report.open(encoding='utf-8-sig', newline='') as stream:
            entries = list(csv.DictReader(stream))
        if len(entries) != job['rows']:
            raise RuntimeError('Audit job row count changed: ' + name)
        for entry in entries:
            identity = (name, entry['bucket'], entry['key'])
            if identity in originals:
                raise RuntimeError('Duplicate audit asset')
            originals[identity] = (entry, job_report.parent / 'downloads')
    with report.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    counts = Counter()
    seen = set()
    reviewed = []
    for row in rows:
        key = PurePosixPath(row['key'])
        bucket = row['bucket']
        language = row['language']
        if (row['category'] != 'intro' or row['status'] != 'ok' or
            bucket != {'en':'audio-en','es':'audio-es','pt-BR':'audio-ptbr'}.get(language) or
            key.is_absolute() or '..' in key.parts or len(key.parts) != 2 or
            key.parts[0] != 'collections-intros' or not key.name.endswith('.mp3') or '\\' in row['key']):
            raise RuntimeError('Unexpected Collections asset identity')
        identity = (bucket, row['key'])
        if identity in seen:
            raise RuntimeError('Duplicate combined-report asset')
        seen.add(identity)
        name = row['collection_slug'] + '|' + language
        original_row, download_root = originals.pop((name, bucket, row['key']))
        if any(row.get(k) != value for k, value in original_row.items()):
            raise RuntimeError('Combined row differs from the saved audit job: ' + name)
        before = float(row['integrated_lufs'])
        peak = float(row['true_peak_dbtp'])
        if not math.isfinite(before) or not math.isfinite(peak):
            raise RuntimeError('Nonfinite audit measurement')
        lower = before > -21
        if lower != (bucket in {'audio-en', 'audio-es'}):
            raise RuntimeError('Report no longer matches the reviewed English/Spanish-only plan')
        source = (download_root / bucket / row['key']).resolve()
        if not source.is_relative_to(download_root.resolve()) or not source.is_file():
            raise RuntimeError('Audited original missing: ' + str(source))
        reviewed.append(dict(row, job=name, action='lower_to_minus_22' if lower else 'leave_unchanged',
                             source=str(source), source_sha256=sha(source)))
        counts[bucket] += 1
    if dict(counts) != EXPECTED_COUNTS or originals:
        raise RuntimeError('Unexpected audit scope; expected 2,300 intros in each language')
    return {'report_sha256': EXPECTED_REPORT_SHA, 'target_lufs': -22,
            'leave_at_or_below_lufs': -21, 'files': reviewed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-root', type=Path, default=AUDIT_ROOT)
    parser.add_argument('--output', type=Path, default=OUTPUT_ROOT)
    parser.add_argument('--workers', type=int, choices=range(1,33), default=min(12, max(1, os.cpu_count() or 2)),
                        help='Parallel files; default uses CPU count, capped at 12 (maximum 32)')
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    identity_path = root / 'review-identity.json'
    lock = root / 'prepare.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        print('Checking the reviewed audit and local source checksums...', flush=True)
        data = build_review(args.audit_root.resolve())
        review_path = root / 'review.json'
        if review_path.exists():
            if json.loads(review_path.read_text(encoding='utf-8')) != data:
                raise RuntimeError('Reviewed source identity changed; held for review')
        else:
            save(review_path, data)
        fingerprint = sha(review_path)
        rows = [r for r in data['files'] if r['action'] == 'lower_to_minus_22']
        if identity_path.exists():
            if json.loads(identity_path.read_text())['review_sha256'] != fingerprint:
                raise RuntimeError('Review changed; use another output folder')
        else:
            save(identity_path, {'review_sha256': fingerprint, 'target_lufs': -22, 'leave_at_or_below_lufs': -21})
        print('REVIEW SHA256:', fingerprint, flush=True)
        print('Portuguese intros left unchanged: 2300.', flush=True)
        print(f'LOCAL PREPARATION ONLY: {len(rows)} intros; {args.workers} workers.', flush=True)
        print('Originals preserved. No uploads or database changes.', flush=True)
        results = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(prepare, r, root) for r in rows]
            try:
                for f in as_completed(futures):
                    result = f.result()
                    results.append(result)
                    print(f"{len(results)}/{len(rows)} {result['bucket']}/{result['key']} {result['status']}" + (': '+result['error'] if result.get('error') else ''), flush=True)
            except KeyboardInterrupt:
                STOP.set()
                for future in futures:
                    future.cancel()
                print('Stopping after active files finish; progress is saved per file.', flush=True)
                raise
        save(root / 'prepared-manifest.json', {'review_sha256': fingerprint, 'target_lufs': -22, 'files': results})
        print('RESULTS:', dict(Counter(r['status'] for r in results)))
        print('MANIFEST:', root / 'prepared-manifest.json')
        print('REVIEW SHA256:', fingerprint)
        print('NO AUDIO UPLOADED. NO DATABASE CHANGES.')
        return 1 if any(r['status'] != 'candidate_verified' for r in results) else 0
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Stopped. Rerun the same command to resume completed assets.')
        sys.exit(130)
