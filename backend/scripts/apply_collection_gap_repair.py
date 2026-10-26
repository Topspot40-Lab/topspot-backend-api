"""Apply reviewed Collection rank changes after all 104 MP3s are staged.

Dry run (read-only):
    python -m backend.scripts.apply_collection_gap_repair \
      --plan collection-gap-reviewed.json --audio-dir collection-gap-audio \
      --corrections shared-track-corrections.json --correction-audio-dir shared-track-audio \
      --backup-dir collection-gap-backup

Add --apply to back up existing destination audio, upload and verify every
replacement, then commit the guarded DB changes in one transaction. Old source
MP3s remain available for rollback. Never run against an unexpected DB/project.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from backend.scripts.check_collection_gap_preflight import inspect
from backend.scripts.stage_collection_gap_intros import digest, read_plan
from backend.scripts.stage_shared_track_corrections import read_corrections, verified_recordings as verified_corrections
from backend.scripts.verify_collection_gap_audio import verified_recordings as verified_main


def require_rows(connection, plan, corrections):
    report = inspect(plan, connection)
    if report["problems"]:
        raise ValueError("Database changed after review: " + "; ".join(report["problems"]))
    if len(report["artist_checks"]) != 1:
        raise ValueError("Expected one artist correction")
    check = report["artist_checks"][0]
    if (check["ranking_id"], check["track_id"], check["database_artist"],
        len(check["collection_uses"]), check["nostalgia_use_count"]) != (
        2781, 2315, "Muddy Waters", 2, 1):
        raise ValueError("Shared track usages differ from review")
    if [r["id"] for r in check["candidate_artist_rows"]] != [corrections["new_artist_id"]]:
        raise ValueError("The Band artist record changed")

    collection = corrections["collection"]
    r = connection.execute(text("""
        SELECT ctr.ranking, ctr.intro, c.slug FROM collection_track_ranking ctr
        JOIN collection c ON c.id=ctr.collection_id WHERE ctr.id=:id
    """), {"id":collection["ranking_id"]}).mappings().one()
    if (r["ranking"],r["intro"],r["slug"]) != (41,collection["before"]["en"],collection["slug"]):
        raise ValueError("American Folk Heroes English intro changed")
    for lang in ("es","pt-BR"):
        row=connection.execute(text("""
            SELECT intro_text, tts_key FROM collection_track_ranking_locale
            WHERE collection_track_ranking_id=:id AND lang=:lang
        """), {"id":2298,"lang":lang}).mappings().one()
        if (row["intro_text"],row["tts_key"]) != (collection["before"][lang],collection["locale_keys_before"][lang]):
            raise ValueError(f"American Folk Heroes {lang} intro changed")

    nostalgia=corrections["nostalgia"]
    row=connection.execute(text("SELECT ranking, intro FROM track_ranking WHERE id=:id"),{"id":3095}).mappings().one()
    if (row["ranking"],row["intro"]) != (41,nostalgia["en_intro_unchanged"]):
        raise ValueError("1960s Folk Acoustic ranking or English intro changed")
    for lang in ("es","pt-BR"):
        row=connection.execute(text("""
            SELECT intro_text,tts_bucket,tts_key FROM track_ranking_locale
             WHERE track_ranking_id=3095 AND language_code=:lang
        """),{"lang":lang}).mappings().one()
        if (row["intro_text"],row["tts_bucket"],row["tts_key"]) != (
            nostalgia["before"][lang],nostalgia["locale_buckets_before"][lang],nostalgia["locale_keys_before"][lang]):
            raise ValueError(f"1960s Folk Acoustic {lang} intro changed")
    track=connection.execute(text("""
        SELECT artist_id,artist_display_name,spotify_track_id FROM track WHERE id=2315
    """)).mappings().one()
    if (track["artist_id"],track["artist_display_name"],track["spotify_track_id"]) != (
        corrections["old_artist_id"],corrections["artist_display_name_before"],corrections["spotify_track_id"]):
        raise ValueError("Shared track metadata changed")


def one_update(connection, statement, params, description):
    if connection.execute(text(statement), params).rowcount != 1:
        raise ValueError(f"Expected exactly one database row for {description}")


def wait_for_storage_hash(storage, key: str, expected: str, *, attempts: int = 45) -> bool:
    """Storage downloads can briefly return a previous object after an upsert."""
    for attempt in range(attempts):
        if digest(storage.download(key)) == expected:
            return True
        if attempt == 2:
            print(f"Waiting for storage to serve updated {key}", flush=True)
        if attempt < attempts - 1:
            time.sleep(2)
    return False


def write_database(connection, plan, corrections):
    # Lock ranking rows and the shared track so the snapshot guard stays valid.
    for program in plan["programs"]:
        connection.execute(text("""
            SELECT id FROM collection_track_ranking WHERE collection_id=:cid ORDER BY id FOR UPDATE
        """),{"cid":program["collection_id"]}).all()
    connection.execute(text("SELECT id FROM track WHERE id=2315 FOR UPDATE")).one()
    require_rows(connection,plan,corrections)

    for program in plan["programs"]:
        for move in program["moves"]:
            one_update(connection,"""
                UPDATE collection_track_ranking SET ranking=:new_rank,intro=:after
                 WHERE id=:id AND collection_id=:cid AND ranking=:old_rank AND intro=:before
            """,{"id":move["ranking_id"],"cid":program["collection_id"],
                   "old_rank":move["old_rank"],"new_rank":move["new_rank"],
                   "before":move["intros_before"]["en"],"after":move["intros_after"]["en"]},
                f"Collection ranking {move['ranking_id']}")
            for lang in ("es","pt-BR"):
                one_update(connection,"""
                    UPDATE collection_track_ranking_locale SET intro_text=:after,tts_key=:new_key
                     WHERE collection_track_ranking_id=:id AND lang=:lang
                       AND intro_text=:before AND tts_key=:old_key
                """,{"id":move["ranking_id"],"lang":lang,
                       "before":move["intros_before"][lang],"after":move["intros_after"][lang],
                       "old_key":move["audio_before"][lang],"new_key":move["audio_after"][lang]},
                    f"Collection locale {move['ranking_id']}/{lang}")

    collection=corrections["collection"]
    one_update(connection,"""
        UPDATE collection_track_ranking SET intro=:after WHERE id=2298 AND ranking=41 AND intro=:before
    """,{"before":collection["before"]["en"],"after":collection["after"]["en"]},
        "American Folk Heroes English intro")
    for lang in ("es","pt-BR"):
        one_update(connection,"""
            UPDATE collection_track_ranking_locale SET intro_text=:after
             WHERE collection_track_ranking_id=2298 AND lang=:lang AND intro_text=:before
               AND tts_key=:key
        """,{"lang":lang,"before":collection["before"][lang],
               "after":collection["after"][lang],"key":collection["locale_keys_before"][lang]},
            f"American Folk Heroes {lang} intro")
        nostalgia=corrections["nostalgia"]
        one_update(connection,"""
            UPDATE track_ranking_locale SET intro_text=:after
             WHERE track_ranking_id=3095 AND language_code=:lang AND intro_text=:before
               AND tts_key=:key AND tts_bucket=:bucket
        """,{"lang":lang,"before":nostalgia["before"][lang],
               "after":nostalgia["after"][lang],"key":nostalgia["locale_keys_before"][lang],
               "bucket":nostalgia["locale_buckets_before"][lang]},
            f"1960s Folk Acoustic {lang} intro")
    one_update(connection,"""
        UPDATE track SET artist_id=:new_artist WHERE id=2315 AND artist_id=:old_artist
         AND artist_display_name=:display AND spotify_track_id=:spotify_id
    """,{"new_artist":corrections["new_artist_id"],"old_artist":corrections["old_artist_id"],
           "display":corrections["artist_display_name_before"],
           "spotify_id":corrections["spotify_track_id"]},"shared track artist")
    for program in plan["programs"]:
        ranks=connection.execute(text("""
            SELECT ranking FROM collection_track_ranking WHERE collection_id=:cid ORDER BY ranking
        """),{"cid":program["collection_id"]}).scalars().all()
        if ranks!=list(range(1,program["track_count"]+1)):
            raise ValueError(f"Final ranks are not contiguous: {program['collection']}")


def upload_audio(recordings, backup_dir: Path):
    from backend.services.supabase_client import supabase
    from backend.services.supabase_storage import object_exists, upload_bytes
    backup_dir.mkdir(parents=True,exist_ok=True)
    inventory_path=backup_dir/"original-audio-inventory.json"
    if inventory_path.exists():
        inventory=json.loads(inventory_path.read_text(encoding="utf-8"))
        if len(inventory)!=len(recordings):
            raise ValueError("Incomplete original-audio inventory; no uploads will run")
    else:
        inventory={}
        # Finish the entire backup before overwriting even one audio object.
        for recording in recordings:
            bucket,key=recording["bucket"],recording["key"]
            storage=supabase.storage.from_(bucket)
            target=backup_dir/bucket/key
            exists=object_exists(bucket,key)
            if exists:
                data=storage.download(key)
                if not data:
                    raise ValueError(f"Empty existing audio object: {bucket}/{key}")
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(data)
            inventory[f"{bucket}/{key}"]={"existed":exists,
                                           "sha256":digest(data) if exists else None}
        tmp=inventory_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(inventory,indent=2)+"\n",encoding="utf-8")
        tmp.replace(inventory_path)
    for recording in recordings:
        bucket,key=recording["bucket"],recording["key"]
        item=inventory.get(f"{bucket}/{key}")
        if item is None:
            raise ValueError(f"Audio backup inventory missing {bucket}/{key}")
        if item["existed"] and digest((backup_dir/bucket/key).read_bytes())!=item["sha256"]:
            raise ValueError(f"Original audio backup changed: {bucket}/{key}")
    for n,recording in enumerate(recordings,1):
        bucket,key=recording["bucket"],recording["key"]
        storage=supabase.storage.from_(bucket)
        expected=recording["sha256"]
        upload_bytes(bucket,key,recording["path"].read_bytes(),content_type="audio/mpeg")
        if not wait_for_storage_hash(storage,key,expected):
            raise ValueError(f"Upload verification failed: {bucket}/{key}")
        print(f"UPLOADED {n}/{len(recordings)} {bucket}/{key}",flush=True)


def restore_audio(recordings, backup_dir: Path):
    """Undo only objects still matching this batch's uploaded bytes."""
    from backend.services.supabase_client import supabase
    from backend.services.supabase_storage import object_exists, upload_bytes
    inventory_path=backup_dir/"original-audio-inventory.json"
    if not inventory_path.exists():
        return  # No uploads start until the entire original inventory exists.
    inventory=json.loads(inventory_path.read_text(encoding="utf-8"))
    restored=0
    for recording in reversed(recordings):
        bucket,key=recording["bucket"],recording["key"]
        item=inventory[f"{bucket}/{key}"]
        storage=supabase.storage.from_(bucket)
        if not object_exists(bucket,key):
            continue
        if not wait_for_storage_hash(storage,key,recording["sha256"]):
            continue  # Do not undo another writer's change.
        if item["existed"]:
            original=(backup_dir/bucket/key).read_bytes()
            if digest(original)!=item["sha256"]:
                raise ValueError(f"Original backup corrupted: {bucket}/{key}")
            upload_bytes(bucket,key,original,content_type="audio/mpeg")
            if not wait_for_storage_hash(storage,key,item["sha256"]):
                raise ValueError(f"Audio restore failed: {bucket}/{key}")
        else:
            storage.remove([key])
            if object_exists(bucket,key):
                raise ValueError(f"New audio object could not be removed: {bucket}/{key}")
        restored+=1
    print(f"Restored {restored} uploaded objects after unsuccessful apply",flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--audio-dir",type=Path,required=True)
    parser.add_argument("--corrections",type=Path,required=True)
    parser.add_argument("--correction-audio-dir",type=Path,required=True)
    parser.add_argument("--backup-dir",type=Path,required=True)
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    plan=read_plan(args.plan)
    corrections=read_corrections(args.corrections)
    recordings=verified_main(args.plan,args.audio_dir)+verified_corrections(args.corrections,args.correction_audio_dir)
    if len(recordings)!=104 or len({(r["bucket"],r["key"]) for r in recordings})!=104:
        raise ValueError("Expected 104 distinct target audio objects")
    from backend.database import engine
    with engine.connect() as connection:
        require_rows(connection,plan,corrections)
    print("DB snapshot and 104 local MP3s verified; 33 Collection ranks will change")
    if not args.apply:
        print("DRY RUN ONLY. No uploads or database changes made")
        return
    try:
        upload_audio(recordings,args.backup_dir)
        with engine.begin() as connection:
            write_database(connection,plan,corrections)
    except Exception:
        try:
            restore_audio(recordings,args.backup_dir)
        except Exception as restore_error:
            print(f"Audio restore needs attention: {restore_error}. Original files remain in {args.backup_dir}")
        raise
    report={"completed_utc":datetime.now(timezone.utc).isoformat(),
            "collection_plan_sha256":digest(args.plan.read_bytes()),
            "shared_track_plan_sha256":digest(args.corrections.read_bytes()),
            "moved_rankings":33,"uploaded_and_verified_mp3s":104,
            "corrected_track_artist_id":corrections["new_artist_id"],
            "backup_directory":str(args.backup_dir)}
    (args.backup_dir/"apply-report.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print("Committed 33 rank changes, 104 intro texts/audio updates and shared artist correction")
    print(f"Saved {args.backup_dir/'apply-report.json'}")


if __name__=="__main__":
    main()
