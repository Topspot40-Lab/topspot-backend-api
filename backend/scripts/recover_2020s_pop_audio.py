"""Inspect and safely finish the audio rollback from the failed 2020s Pop apply.

Dry run first. Add --restore only after inspecting the summary. Does not write
to the database. Requires the original backup directory and staged MP3s.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from backend.scripts import apply_2020s_pop_additions as app
from backend.scripts.stage_2020s_pop_audio import digest, read_plan, verified_recordings


def download(storage, key):
    for attempt in range(6):
        try:
            return storage.download(key)
        except Exception as exc:
            if app.missing_object(exc):
                return None
            message = str(exc).lower()
            if attempt == 5 or not any(word in message for word in (
                "ssl", "timeout", "timed out", "connection", "bad record mac", "temporar"
            )):
                raise
            print(f"Retrying network read for {key}: {type(exc).__name__}", flush=True)
            time.sleep(2 * (attempt + 1))
    raise AssertionError("Unreachable")


def snapshot(recordings, inventory, touched):
    from backend.services.supabase_client import supabase
    results = []
    for name in touched:
        item = recordings[name]
        bucket,key = item["bucket"],item["key"]
        data = download(supabase.storage.from_(bucket),key)
        current = digest(data) if data is not None else None
        original = inventory["objects"][name]["sha256"]
        if current == original:
            status = "original"
        elif current == item["sha256"]:
            status = "uploaded"
        else:
            status = "conflict"
        results.append({"bucket":bucket,"key":key,"status":status,
                        "sha256":current})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--audio-dir",type=Path,required=True)
    parser.add_argument("--backup-dir",type=Path,required=True)
    parser.add_argument("--restore",action="store_true")
    args = parser.parse_args()
    plan = read_plan(args.plan)
    from backend.database import engine
    with engine.connect() as connection:
        app.require_database(connection,plan)
    specs = verified_recordings(args.plan,args.audio_dir)
    recordings = {f"{r['bucket']}/{r['key']}":r for r in specs}
    journal_path = args.backup_dir / "upload-journal.json"
    inventory_path = args.backup_dir / "original-audio-inventory.json"
    if not inventory_path.is_file() or not journal_path.is_file():
        raise ValueError("Missing original inventory or incomplete-apply journal; do not retry apply")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    touched = json.loads(journal_path.read_text(encoding="utf-8"))
    if inventory["plan_sha256"] != digest(args.plan.read_bytes()) or set(inventory["objects"]) != set(recordings):
        raise ValueError("Backup inventory does not match the exact 60 staged recordings")
    if not isinstance(touched,list) or len(touched) != len(set(touched)) or not set(touched).issubset(recordings):
        raise ValueError("Upload journal is incomplete or contains unexpected destinations")
    for name,item in inventory["objects"].items():
        if item["existed"]:
            backup = args.backup_dir / name
            if not backup.is_file() or digest(backup.read_bytes()) != item["sha256"]:
                raise ValueError(f"Original audio backup is missing or changed: {name}")
        elif item["sha256"] is not None:
            raise ValueError(f"Unexpected backup inventory for {name}")
    statuses = snapshot(recordings,inventory,touched)
    counts = {s:sum(item["status"] == s for item in statuses) for s in ("uploaded","original","conflict")}
    print(f"DB unchanged; {len(touched)} upload attempts: {counts['uploaded']} still uploaded, {counts['original']} already restored, {counts['conflict']} unexpected",flush=True)
    app.atomic_json(args.backup_dir / "recovery-inspection.json", {"counts":counts,"objects":statuses})
    if counts["conflict"]:
        raise ValueError("A destination differs from both expected versions; stopping before changes")
    if not args.restore:
        print("READ-ONLY CHECK. Run again with --restore to finish audio rollback.",flush=True)
        return

    from backend.services.supabase_client import supabase
    from backend.services.supabase_storage import upload_bytes
    to_delete = defaultdict(list)
    to_restore = []
    for item in statuses:
        if item["status"] != "uploaded":
            continue
        name = f"{item['bucket']}/{item['key']}"
        if inventory["objects"][name]["existed"]:
            to_restore.append(item)
        else:
            to_delete[item["bucket"]].append(item)

    # Recheck every object immediately before changing it. Batch deletions let
    # eventual-consistency delays settle for all new objects at once.
    for bucket,items in to_delete.items():
        storage = supabase.storage.from_(bucket)
        for item in items:
            data = download(storage,item["key"])
            if data is None:
                continue
            if digest(data) != recordings[f"{bucket}/{item['key']}"]["sha256"]:
                raise ValueError(f"Destination changed during recovery: {bucket}/{item['key']}")
        for offset in range(0,len(items),20):
            keys = [x["key"] for x in items[offset:offset+20]]
            storage.remove(keys)
            print(f"Removed {len(keys)} new objects from {bucket}",flush=True)

    for item in to_restore:
        bucket,key = item["bucket"],item["key"]
        name = f"{bucket}/{key}"
        storage = supabase.storage.from_(bucket)
        current = download(storage,key)
        original = inventory["objects"][name]["sha256"]
        if (digest(current) if current is not None else None) == original:
            continue
        if current is None or digest(current) != recordings[name]["sha256"]:
            raise ValueError(f"Destination changed during recovery: {name}")
        upload_bytes(bucket,key,(args.backup_dir/name).read_bytes(),content_type="audio/mpeg")
        print(f"Restored previous audio at {name}",flush=True)

    # Check deletion/restore results together after all mutations, so each
    # storage cache has time to settle. Keep the journal if verification fails.
    pending = list(touched)
    for attempt in range(46):
        unresolved=[]
        for name in pending:
            spec=recordings[name]
            current=download(supabase.storage.from_(spec["bucket"]),spec["key"])
            if (digest(current) if current is not None else None) != inventory["objects"][name]["sha256"]:
                unresolved.append(name)
        if not unresolved:
            break
        pending=unresolved
        if attempt == 45:
            raise ValueError(f"Audio rollback not yet verified for {len(unresolved)} objects; journal retained")
        if attempt in (0,5,15,30):
            print(f"Waiting for {len(unresolved)} restored destinations to become visible",flush=True)
        time.sleep(2)
    app.atomic_json(args.backup_dir / "recovery-report.json",
                    {"status":"restored","objects_checked":len(touched),
                     "objects_removed":sum(map(len,to_delete.values())),
                     "previous_objects_restored":len(to_restore)})
    journal_path.unlink()
    print(f"Audio rollback complete and verified for {len(touched)} destinations; DB remains unchanged",flush=True)


if __name__ == "__main__":
    main()
