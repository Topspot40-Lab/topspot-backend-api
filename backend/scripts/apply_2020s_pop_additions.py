"""Safely add ten reviewed 2020s Pop songs and their 60 new narration MP3s.

Dry run:
    python -m backend.scripts.apply_2020s_pop_additions \
      --plan 2020s-pop-reviewed.json --audio-check 2020s-pop-audio-check.json \
      --audio-dir 2020s-pop-audio --backup-dir 2020s-pop-backup

Add --apply only after the dry run succeeds. Audio is uploaded and verified
before the database transaction; failures restore the backed-up audio.
"""

from __future__ import annotations

import argparse
import json
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from backend.scripts.stage_2020s_pop_audio import (
    BUCKETS, LANGUAGES, digest, read_audio_check, read_plan, verified_recordings,
)
from backend.scripts.check_2020s_pop_preflight import inspect as inspect_database


def missing_object(exc: Exception) -> bool:
    code = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    message = str(exc).lower()
    return str(code) == "404" or "not_found" in message or "not found" in message


def optional_download(storage, key: str) -> bytes | None:
    try:
        return storage.download(key)
    except Exception as exc:
        if missing_object(exc):
            return None
        raise


def wait_for_hash(storage, key: str, expected: str | None, *, attempts: int = 45) -> bool:
    for n in range(attempts):
        data = optional_download(storage, key)
        if (digest(data) if data is not None else None) == expected:
            return True
        if n == 2:
            print(f"Waiting for storage to serve {key}", flush=True)
        if n < attempts - 1:
            time.sleep(2)
    return False


def atomic_json(path: Path, data: object) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()


def artist_artwork(plan) -> dict:
    from dotenv import load_dotenv
    load_dotenv()
    from backend.services.spotify.spotify_lookup import sp
    artwork = {}
    for a in plan["additions"]:
        if a["reuse_artist_id"] is not None:
            continue
        artist = sp.artist(a["spotify_artist_id"])
        if artist["id"] != a["spotify_artist_id"] or normalize(artist["name"]) != normalize(a["artist_name"]):
            raise ValueError(f"Spotify artist has changed at rank {a['rank']}")
        artwork[artist["id"]] = artist["images"][0]["url"] if artist.get("images") else None
    return artwork


def require_database(connection, plan) -> None:
    result = inspect_database(plan, connection, storage=False)
    if not result["ready"]:
        raise ValueError("2020s Pop database changed: " + json.dumps(result, ensure_ascii=False))
    identity = connection.execute(text("""
        SELECT d.slug AS decade,g.slug AS genre FROM decade_genre dg
        JOIN decade d ON d.id=dg.decade_id JOIN genre g ON g.id=dg.genre_id
        WHERE dg.id=:id
    """), {"id":plan["program"]["id"]}).mappings().one()
    if dict(identity) != {"decade":"2020s", "genre":"pop"}:
        raise ValueError("The target program is no longer 2020s Pop")
    for a in plan["additions"]:
        if a["featured_artist_spotify_id"]:
            featured = connection.execute(text("""
                SELECT id FROM artist WHERE spotify_artist_id=:sid
            """), {"sid":a["featured_artist_spotify_id"]}).scalars().all()
            if len(featured) != 1 or featured[0] != 402:
                raise ValueError("APT. featured Bruno Mars artist is missing or changed")


def verify_existing_audio(plan) -> None:
    """All reused details and artist biographies remain downloadable."""
    from backend.services.supabase_client import supabase
    keys = set()
    for a in plan["additions"]:
        for lang in LANGUAGES:
            if a["reuse_track_id"] is not None:
                keys.add((BUCKETS[lang], f"detail/{a['spotify_track_id']}.mp3"))
            if a["reuse_artist_id"] is not None:
                keys.add((BUCKETS[lang], f"artist/{a['spotify_artist_id']}.mp3"))
    if len(keys) != 30:
        raise ValueError("Unexpected reused narration inventory")
    for bucket,key in sorted(keys):
        data = optional_download(supabase.storage.from_(bucket), key)
        if data is None or len(data) <= 1000 or not (data.startswith(b"ID3") or data[:1] == b"\xff"):
            raise ValueError(f"Reused audio missing or invalid: {bucket}/{key}")


def create_inventory(recordings, backup_dir: Path, plan_hash: str) -> dict:
    """Finish a durable inventory and backup before uploading any object."""
    from backend.services.supabase_client import supabase
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / "original-audio-inventory.json"
    if path.exists():
        inventory = json.loads(path.read_text(encoding="utf-8"))
        if inventory["plan_sha256"] != plan_hash:
            raise ValueError("Backup directory belongs to a different plan")
    else:
        inventory = {"plan_sha256":plan_hash, "objects":{}}
        for item in recordings:
            bucket,key = item["bucket"],item["key"]
            data = optional_download(supabase.storage.from_(bucket),key)
            name = f"{bucket}/{key}"
            if data is not None:
                target = backup_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            inventory["objects"][name] = {"existed":data is not None,
                                           "sha256":digest(data) if data is not None else None}
        atomic_json(path, inventory)
    if len(inventory["objects"]) != len(recordings):
        raise ValueError("Audio inventory does not cover all 60 destinations")
    for item in recordings:
        name = f"{item['bucket']}/{item['key']}"
        record = inventory["objects"].get(name)
        if record is None:
            raise ValueError(f"No audio inventory for {name}")
        if record["existed"] and digest((backup_dir / name).read_bytes()) != record["sha256"]:
            raise ValueError(f"Audio backup changed: {name}")
    return inventory


def upload_audio(recordings, backup_dir: Path, inventory: dict) -> None:
    from backend.services.supabase_client import supabase
    from backend.services.supabase_storage import upload_bytes
    journal = backup_dir / "upload-journal.json"
    if journal.exists():
        raise ValueError("A previous apply left an upload journal; inspect it before retrying")
    pending = []
    for index,item in enumerate(recordings,1):
        bucket,key = item["bucket"],item["key"]
        storage = supabase.storage.from_(bucket)
        original = inventory["objects"][f"{bucket}/{key}"]
        current = optional_download(storage,key)
        if (digest(current) if current is not None else None) != original["sha256"]:
            raise ValueError(f"Destination changed since backup: {bucket}/{key}")
        # Record intent first so a crash after upload still leaves a rollback trail.
        pending.append(f"{bucket}/{key}")
        atomic_json(journal, pending)
        upload_bytes(bucket,key,item["path"].read_bytes(),content_type="audio/mpeg")
        if not wait_for_hash(storage,key,item["sha256"]):
            raise ValueError(f"Upload verification failed: {bucket}/{key}")
        print(f"UPLOADED {index}/{len(recordings)} {bucket}/{key}",flush=True)


def restore_audio(recordings, backup_dir: Path, inventory: dict) -> None:
    from backend.services.supabase_client import supabase
    from backend.services.supabase_storage import upload_bytes
    journal = backup_dir / "upload-journal.json"
    if not journal.exists():
        return
    touched = json.loads(journal.read_text(encoding="utf-8"))
    by_name = {f"{r['bucket']}/{r['key']}":r for r in recordings}
    for name in reversed(touched):
        item = by_name[name]
        bucket,key = item["bucket"],item["key"]
        storage = supabase.storage.from_(bucket)
        current = optional_download(storage,key)
        original = inventory["objects"][name]
        current_hash = digest(current) if current is not None else None
        if current_hash == original["sha256"]:
            continue
        if current_hash != item["sha256"]:
            raise ValueError(f"Cannot safely restore changed destination: {name}")
        if original["existed"]:
            old = (backup_dir / name).read_bytes()
            if digest(old) != original["sha256"]:
                raise ValueError(f"Backup corrupted: {name}")
            upload_bytes(bucket,key,old,content_type="audio/mpeg")
        else:
            storage.remove([key])
        if not wait_for_hash(storage,key,original["sha256"]):
            raise ValueError(f"Audio restore did not verify: {name}")
    journal.unlink()
    print(f"Restored uploaded audio for {len(touched)} destinations",flush=True)


def write_database(connection, plan, artwork: dict) -> dict:
    # A row lock holds the catalog snapshot steady throughout this transaction.
    connection.execute(text("""
        SELECT id FROM track_ranking WHERE decade_genre_id=:id ORDER BY id FOR UPDATE
    """), {"id":plan["program"]["id"]}).all()
    require_database(connection,plan)
    ids = {a["spotify_artist_id"]:a["reuse_artist_id"] for a in plan["additions"] if a["reuse_artist_id"] is not None}
    created_artist_ids = []
    for a in plan["additions"]:
        if a["reuse_artist_id"] is not None:
            continue
        aid = connection.execute(text("""
            INSERT INTO artist (artist_name,spotify_artist_id,artist_artwork,artist_description,not_on_spotify,language)
            VALUES (:name,:spotify,:artwork,:bio,false,'en') RETURNING id
        """), {"name":a["artist_name"],"spotify":a["spotify_artist_id"],
               "artwork":artwork[a["spotify_artist_id"]],"bio":a["artist_bio"]["en"]}).scalar_one()
        ids[a["spotify_artist_id"]] = aid
        created_artist_ids.append(aid)
        for lang in ("es","pt-BR"):
            connection.execute(text("""
                INSERT INTO artist_locale (artist_id,language_code,artist_description_text,tts_bucket,tts_key)
                VALUES (:aid,:lang,:bio,:bucket,:key)
            """), {"aid":aid,"lang":lang,"bio":a["artist_bio"][lang],
                   "bucket":BUCKETS[lang],"key":f"artist/{a['spotify_artist_id']}.mp3"})
    created_track_ids = []
    ranking_ids = []
    for a in plan["additions"]:
        tid = a["reuse_track_id"]
        if tid is None:
            year = 2020 if a["rank"] == 28 else int(a["release_date"][:4])
            featured_id = ids.get(a["featured_artist_spotify_id"]) if a["featured_artist_spotify_id"] else None
            if a["featured_artist_spotify_id"] and not featured_id:
                raise ValueError(f"Missing featured artist at rank {a['rank']}")
            tid = connection.execute(text("""
                INSERT INTO track (track_name,album_name,artist_display_name,spotify_track_id,
                  mode_flag,duration_ms,album_artwork,year_released,artist_id,featured_artist_id,
                  is_explicit,detail,language)
                VALUES (:title,:album,:display,:spotify,CAST(:mode AS modeflag),:duration,:artwork,
                  :year,:artist_id,:featured,:explicit,:detail,'en') RETURNING id
            """), {"title":a["title"],"album":a["album_name"],"display":a["artist_display_name"],
                   "spotify":a["spotify_track_id"],"mode":"DUET" if featured_id else "SOLO",
                   "duration":a["duration_ms"],"artwork":a["album_artwork"],"year":year,
                   "artist_id":ids[a["spotify_artist_id"]],"featured":featured_id,
                   "explicit":a["explicit"],"detail":a["detail"]["en"]}).scalar_one()
            created_track_ids.append(tid)
            for lang in ("es","pt-BR"):
                connection.execute(text("""
                    INSERT INTO track_locale (track_id,language_code,detail_text,tts_bucket,tts_key)
                    VALUES (:tid,:lang,:detail,:bucket,:key)
                """), {"tid":tid,"lang":lang,"detail":a["detail"][lang],
                       "bucket":BUCKETS[lang],"key":f"detail/{a['spotify_track_id']}.mp3"})
        rid = connection.execute(text("""
            INSERT INTO track_ranking (track_id,decade_genre_id,tracklist_id,ranking,intro,created_at)
            VALUES (:tid,:program_id,1,:rank,:intro,now()) RETURNING id
        """), {"tid":tid,"program_id":plan["program"]["id"],"rank":a["rank"],
               "intro":a["intro"]["en"]}).scalar_one()
        ranking_ids.append(rid)
        for lang in ("es","pt-BR"):
            connection.execute(text("""
                INSERT INTO track_ranking_locale (track_ranking_id,language_code,intro_text,tts_bucket,tts_key)
                VALUES (:rid,:lang,:intro,:bucket,:key)
            """), {"rid":rid,"lang":lang,"intro":a["intro"][lang],
                   "bucket":BUCKETS[lang],"key":f"intro/2020s_pop_{a['rank']:02d}.mp3"})
    ranks = connection.execute(text("""
        SELECT ranking FROM track_ranking WHERE decade_genre_id=:id ORDER BY ranking
    """), {"id":plan["program"]["id"]}).scalars().all()
    if ranks != list(range(1,46)):
        raise ValueError("The finished 2020s Pop ranks are not continuous through 45")
    return {"artist_ids":created_artist_ids,"track_ids":created_track_ids,"ranking_ids":ranking_ids}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--audio-check", type=Path, required=True)
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--apply",action="store_true")
    args = parser.parse_args()
    plan = read_plan(args.plan)
    read_audio_check(args.audio_check)
    recordings = verified_recordings(args.plan,args.audio_dir)
    from backend.database import engine
    with engine.connect() as connection:
        require_database(connection,plan)
    verify_existing_audio(plan)
    artwork = artist_artwork(plan)
    # Run all intended inserts in a disposable transaction before uploading.
    # The database rolls back all rows after this check (sequences may advance).
    with engine.connect() as rehearsal:
        transaction = rehearsal.begin()
        try:
            write_database(rehearsal, plan, artwork)
        finally:
            transaction.rollback()
    print("DB transaction rehearsal passed and rolled back")
    print("DB snapshot and 90 remote/local MP3s verified; 10 rankings, 6 tracks, 4 artists will be added")
    if not args.apply:
        print("DRY RUN ONLY. No uploads or database changes made")
        return
    backup_dir = args.backup_dir
    inventory = create_inventory(recordings,backup_dir,digest(args.plan.read_bytes()))
    try:
        upload_audio(recordings,backup_dir,inventory)
        with engine.begin() as connection:
            result = write_database(connection,plan,artwork)
    except Exception:
        try:
            restore_audio(recordings,backup_dir,inventory)
        except Exception as exc:
            print(f"Audio restore needs attention: {exc}. Backups remain in {backup_dir}",flush=True)
        raise
    (backup_dir / "upload-journal.json").unlink(missing_ok=True)
    report = {"completed_utc":datetime.now(timezone.utc).isoformat(),
              "plan_sha256":digest(args.plan.read_bytes()),"added_rankings":10,
              "created_tracks":6,"created_artists":4,"uploaded_audio":60,**result}
    atomic_json(backup_dir / "apply-report.json", report)
    print("Committed 10 rankings, 6 tracks, 4 artists and 60 narrated audio files")
    print(f"Saved {backup_dir/'apply-report.json'}")


if __name__ == "__main__":
    main()
