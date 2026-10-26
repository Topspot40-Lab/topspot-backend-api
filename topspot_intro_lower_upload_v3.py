"""Upload verified quieter intros with backups and durable per-file recovery.
Run after topspot_intro_lower_prepare.py finishes. No database writes.
Commands: status, apply, rollback. Rerun apply to resume after interruption.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

APPROVED_REVIEW_SHA = '0e3383ac754039b39d8fccc5e98ccf9714e50638ffbf8547e144df530d5acaa3'
DEFAULT_ROOT = Path('backend/studio/work/intro-lowering-minus22-20261005')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise RuntimeError('Invalid local JSON: '+str(path)) from error


def save(path, data):
    temporary = path.with_suffix('.tmp.json')
    with temporary.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)


def validate(root):
    if (root / 'prepare.lock').exists():
        raise RuntimeError('Preparation is still running; wait for it to finish')
    if file_sha(root / 'review.json') != APPROVED_REVIEW_SHA:
        raise RuntimeError('Review checksum does not match the approved review')
    review = read(root / 'review.json')
    approved = {(r['bucket'],r['key']):r for r in review['files'] if r['action']=='lower_to_minus_22'}
    manifest = read(root / 'prepared-manifest.json')
    rows = manifest['files']
    if manifest['review_sha256'] != APPROVED_REVIEW_SHA or manifest['target_lufs'] != -22 or len(rows) != 4344 or len(approved) != 4344:
        raise RuntimeError('Unexpected preparation manifest')
    seen = set()
    for r in rows:
        identity = (r['bucket'],r['key'])
        source = approved.get(identity)
        if identity in seen or source is None or r['category']!='intro' or r['status']!='candidate_verified' or r['source_sha256']!=source['source_sha256']:
            raise RuntimeError('Unexpected, duplicate, excluded, or unverified intro')
        seen.add(identity)
        original = Path(r['original_path']).resolve()
        candidate = Path(r['candidate_path']).resolve()
        expected_folder = (root / 'assets' / r['bucket'] / r['key']).resolve()
        if original != expected_folder / 'original.mp3' or candidate != expected_folder / 'candidate.mp3':
            raise RuntimeError('Unexpected local asset path')
        if file_sha(original)!=r['source_sha256'] or file_sha(candidate)!=r['candidate_sha256']:
            raise RuntimeError('Local audio checksum mismatch: '+r['key'])
        before = float(source['integrated_lufs'])
        after = float(r['candidate_lufs'])
        peak = float(r['candidate_true_peak_dbtp'])
        if not all(math.isfinite(v) for v in (before,after,peak)) or before<=-21 or abs(after+22)>.5 or after>=before or peak>-1:
            raise RuntimeError('Invalid lowering verification')
    return sorted(rows,key=lambda r:(r['job'],int(r['ranking'])))


def transient(error):
    from httpx import TransportError
    pending = [error]
    seen = set()
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, (TransportError, TimeoutError, ConnectionError)):
            return True
        status = getattr(getattr(item, 'response', None), 'status_code', None)
        if status in (408, 429) or isinstance(status, int) and 500 <= status <= 599:
            return True
        pending.extend(e for e in (item.__cause__, item.__context__) if e is not None)
    return False


class Remote:
    def __init__(self):
        from backend.services.supabase_client import supabase
        from backend.services.supabase_storage import upload_bytes
        self.client = supabase
        self.writer = upload_bytes

    def download(self,bucket,key):
        for attempt in range(6):
            try:
                data = self.client.storage.from_(bucket).download(
                    key, query_params={'intro_verify': uuid.uuid4().hex})
                if not data:
                    raise RuntimeError('Empty remote audio: '+bucket+'/'+key)
                return data
            except Exception as error:
                if not transient(error) or attempt == 5:
                    raise
                print('Retrying fresh storage read: '+bucket+'/'+key, flush=True)
                time.sleep(min(20, 2 ** (attempt+1)))

    def upload(self,bucket,key,data):
        self.writer(bucket,key,data,'audio/mpeg')


def verify(remote,bucket,key,expected):
    for attempt in range(6):
        if digest(remote.download(bucket,key))==expected:
            return
        if attempt == 0:
            print('Retrying fresh checksum verification: '+bucket+'/'+key, flush=True)
        if attempt<5:
            time.sleep(min(8,2**(attempt+1)))
    raise RuntimeError('Remote checksum not verified: '+bucket+'/'+key+'; stopped, rerun to reconcile')


def item_path(row):
    return Path(row['original_path']).parent / 'upload.json'


def load_item(row,run_id):
    path = item_path(row)
    if path.exists():
        item = read(path)
        if any(item.get(k)!=v for k,v in {'run_id':run_id,'bucket':row['bucket'],'key':row['key'],'source_sha256':row['source_sha256'],'candidate_sha256':row['candidate_sha256'],'backup_key':f"normalization-backups/{run_id}/{row['key']}"}.items()):
            raise RuntimeError('Upload record identity mismatch')
    else:
        item = dict(run_id=run_id,bucket=row['bucket'],key=row['key'],
                    source_sha256=row['source_sha256'],candidate_sha256=row['candidate_sha256'],
                    backup_key=f"normalization-backups/{run_id}/{row['key']}",
                    backup_verified=False,upload_intent=False,production_verified=False,
                    rollback_intent=False,rolled_back=False,status='pending')
    return path,item


def apply_one(row,run_id,remote):
    path,item = load_item(row,run_id)
    try:
        if item['rollback_intent']:
            raise RuntimeError('This run has been rolled back; apply is disabled')
        current = remote.download(row['bucket'],row['key'])
        current_sha = digest(current)
        if current_sha==row['candidate_sha256']:
            if not item['upload_intent'] or not item['backup_verified']:
                raise RuntimeError('Unexpected candidate already in production without this run\'s backup/intent')
            verify(remote,row['bucket'],item['backup_key'],row['source_sha256'])
        elif current_sha==row['source_sha256']:
            if not item['backup_verified']:
                item['status']='backup_intent'
                save(path,item)
                remote.upload(row['bucket'],item['backup_key'],current)
                verify(remote,row['bucket'],item['backup_key'],row['source_sha256'])
                item['backup_verified']=True
                item['status']='backup_verified'
                save(path,item)
            else:
                verify(remote,row['bucket'],item['backup_key'],row['source_sha256'])
            # Check production again after backup, immediately before replacement.
            if digest(remote.download(row['bucket'],row['key']))!=row['source_sha256']:
                raise RuntimeError('Production changed while backup was being made; stopped')
            candidate = Path(row['candidate_path']).read_bytes()
            if digest(candidate)!=row['candidate_sha256']:
                raise RuntimeError('Candidate changed before upload')
            item['upload_intent']=True
            item['status']='upload_intent'
            save(path,item)
            remote.upload(row['bucket'],row['key'],candidate)
            verify(remote,row['bucket'],row['key'],row['candidate_sha256'])
        else:
            raise RuntimeError('Production differs from both approved original and candidate; held for review')
        item['production_verified']=True
        item['status']='production_verified'
        item.pop('error',None)
        save(path,item)
        return item
    except Exception as error:
        item['status']='held'
        item['error']=str(error)
        save(path,item)
        raise


def rollback_one(row,run_id,remote):
    path,item = load_item(row,run_id)
    if not item['upload_intent']:
        return item
    if not item['backup_verified']:
        raise RuntimeError('Cannot roll back without a verified backup')
    original = remote.download(row['bucket'],item['backup_key'])
    if digest(original)!=row['source_sha256']:
        raise RuntimeError('Backup changed; rollback stopped')
    current = digest(remote.download(row['bucket'],row['key']))
    if current not in {row['source_sha256'],row['candidate_sha256']}:
        raise RuntimeError('Unexpected production change; rollback stopped')
    item['rollback_intent']=True
    item['status']='rollback_intent'
    save(path,item)
    if current!=row['source_sha256']:
        remote.upload(row['bucket'],row['key'],original)
    verify(remote,row['bucket'],row['key'],row['source_sha256'])
    item.update(status='rolled_back',rolled_back=True,production_verified=False)
    item.pop('error',None)
    save(path,item)
    return item


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['status','apply','rollback'])
    parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--limit',type=int,default=0,help='0 means all; otherwise process the first N intros')
    args=parser.parse_args()
    if args.limit<0:
        raise RuntimeError('Limit must be nonnegative')
    root=args.root.resolve()
    if args.command=='status':
        states=Counter(read(p)['status'] for p in (root/'assets').rglob('upload.json'))
        print('LOCAL UPLOAD RECORDS:',dict(states))
        print('These are saved results from the last remote verification.')
        return
    rows=validate(root)
    if args.limit:
        rows=rows[:args.limit]
    lock=root/'upload.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.close(fd)
    try:
        metadata=root/'upload-run.json'
        if metadata.exists():
            run=read(metadata)
            if run['review_sha256']!=APPROVED_REVIEW_SHA:
                raise RuntimeError('Upload run review mismatch')
        elif args.command=='rollback':
            raise RuntimeError('No upload run to roll back')
        else:
            run=dict(run_id='intro-minus22-'+uuid.uuid4().hex,review_sha256=APPROVED_REVIEW_SHA,
                     created_at=datetime.now(timezone.utc).isoformat(),rollback_started=False)
            save(metadata,run)
        if args.command=='apply' and run['rollback_started']:
            raise RuntimeError('Rollback has started; apply disabled')
        if args.command=='rollback':
            run['rollback_started']=True
            save(metadata,run)
        remote=Remote()
        print(f"{args.command.upper()} V3: {len(rows)} intros; fresh storage reads, verified backups, resumable uploads.",flush=True)
        for index,row in enumerate(rows,1):
            for attempt in range(6):
                try:
                    result=(apply_one if args.command=='apply' else rollback_one)(row,run['run_id'],remote)
                    break
                except Exception as error:
                    if not transient(error) or attempt == 5:
                        raise
                    # Reconcile production and backups before any further write.
                    print('Transient storage error; reconciling '+row['bucket']+'/'+row['key'],flush=True)
                    time.sleep(min(30,2**(attempt+1)))
            print(f"{index}/{len(rows)} {row['bucket']}/{row['key']} {result['status']}",flush=True)
        print('PASS FINISHED. Run status for saved totals.',flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Stopped. Per-file intent and backup records are saved; rerun to reconcile.')
        sys.exit(130)
    except Exception as error:
        print('STOPPED:',str(error),file=sys.stderr)
        sys.exit(1)
