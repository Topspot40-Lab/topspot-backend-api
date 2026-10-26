"""Prepare quieter Nostalgia intros locally. No uploads or database writes.
Rerun the same command to resume. Keep the review and output folder together.
"""
from __future__ import annotations
import argparse
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
    p = run(['ffmpeg', '-hide_banner', '-nostdin', '-i', str(path), '-af',
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
                 '-i', str(original), '-map', '0:a:0', '-af', f'volume={gain:.6f}dB',
                 '-c:a', 'libmp3lame', '-b:a', '128k', '-map_metadata', '0', str(partial)])
            stats = measure(partial)
            if abs(stats['input_i'] + 22.0) <= 0.5:
                break
            if attempt < 2:
                gain += -22.0 - stats['input_i']
        length = duration(partial)
        original_length = duration(original)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, default=Path('intro-lowering-review.json'))
    parser.add_argument('--output', type=Path, default=Path('backend/studio/work/intro-lowering-minus22-20261005'))
    parser.add_argument('--workers', type=int, choices=range(1,5), default=2)
    args = parser.parse_args()
    data = json.loads(args.review.read_text(encoding='utf-8'))
    rows = [r for r in data['files'] if r['action'] == 'lower_to_minus_22']
    seen = set()
    for r in rows:
        key = PurePosixPath(r['key'])
        if r['category'] != 'intro' or r['status'] != 'ok' or r['bucket'] not in {'audio-en','audio-es','audio-ptbr'} or key.is_absolute() or '..' in key.parts or not str(key).startswith('intro/') or '\\' in r['key']:
            raise RuntimeError('Unexpected asset identity')
        identity = (r['bucket'],r['key'])
        if identity in seen:
            raise RuntimeError('Duplicate asset')
        seen.add(identity)
        if not math.isfinite(float(r['integrated_lufs'])) or float(r['integrated_lufs']) <= -21 or not r.get('source_sha256'):
            raise RuntimeError('Ineligible source')
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    fingerprint = sha(args.review)
    identity_path = root / 'review-identity.json'
    lock = root / 'prepare.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        if identity_path.exists():
            if json.loads(identity_path.read_text())['review_sha256'] != fingerprint:
                raise RuntimeError('Review changed; use another output folder')
        else:
            save(identity_path, {'review_sha256': fingerprint, 'target_lufs': -22, 'leave_at_or_below_lufs': -21})
        shutil.copyfile(args.review, root / 'review.json')
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
        return 1 if any(r['status'] != 'candidate_verified' for r in results) else 0
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Stopped. Rerun the same command to resume completed assets.')
        sys.exit(130)
