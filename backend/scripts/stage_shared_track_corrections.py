"""Stage five extra intros for the shared recording by The Band.

    python -m backend.scripts.stage_shared_track_corrections \
        --plan shared-track-corrections.json --output-dir shared-track-audio

This calls ElevenLabs. It never changes Supabase or the database. Re-running
skips finished recordings whose text, voice profile, and MP3 hash still match.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from backend.scripts.stage_collection_gap_intros import digest, save_manifest


def read_corrections(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if (plan["track_id"], plan["old_artist_id"], plan["new_artist_id"]) != (2315, 911, 2899):
        raise ValueError("This correction is only for the inspected shared track")
    recordings = plan["recordings"]
    if len(recordings) != 5 or len({(r["bucket"], r["key"]) for r in recordings}) != 5:
        raise ValueError("Expected five unique supplemental intro recordings")
    if {(r["kind"],r["lang"]) for r in recordings} != {
        ("collection","en"),("collection","es"),("collection","pt-BR"),
        ("nostalgia","es"),("nostalgia","pt-BR")
    }:
        raise ValueError("Unexpected set of supplemental narrations")
    for record in recordings:
        if record["lang"] not in ("en", "es", "pt-BR"):
            raise ValueError("Unexpected language")
        if record["bucket"] != {"en":"audio-en","es":"audio-es","pt-BR":"audio-ptbr"}[record["lang"]]:
            raise ValueError("Unexpected language bucket")
        if not record["text"].strip() or "Muddy Waters" in record["text"] or "muddy waters" in record["text"]:
            raise ValueError("Artist credit has not been corrected")
        expected = ("collections-intros/american_folk_heroes_41.mp3" if record["kind"] == "collection"
                    else "intro/1960s_folk_acoustic_41.mp3" if record["kind"] == "nostalgia" else None)
        if record["key"] != expected or record["ranking_id"] != (2298 if record["kind"] == "collection" else 3095):
            raise ValueError("Unexpected audio destination")
        if record["text"] != plan[record["kind"]]["after"][record["lang"]]:
            raise ValueError("Spoken audio differs from the planned database intro")
    return plan


def stage(plan_path: Path, output_dir: Path):
    plan = read_corrections(plan_path)
    plan_hash = digest(plan_path.read_bytes())
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["plan_sha256"] != plan_hash:
            raise ValueError("Correction plan changed; use a fresh output directory")
    else:
        manifest = {"plan_sha256": plan_hash, "recordings": {}}
        save_manifest(manifest_path, manifest)

    from dotenv import load_dotenv
    load_dotenv()
    from backend.config.tts_config import TTS_PROFILES
    from backend.services.tts.elevenlabs_tts import generate_tts_mp3

    for index, recording in enumerate(plan["recordings"], 1):
        lang = recording["lang"]
        profile = TTS_PROFILES[lang]["intro"]
        profile_hash = digest(json.dumps(profile, sort_keys=True).encode())
        relative = f"{lang}/{recording['kind']}_{recording['ranking_id']}.mp3"
        dest = output_dir / relative
        fingerprint = {"relative_path":relative,
                       "intro_sha256":digest(recording["text"].encode()),
                       "profile_sha256":profile_hash}
        key = f"{recording['kind']}:{recording['ranking_id']}:{lang}"
        old = manifest["recordings"].get(key)
        if old and all(old.get(k)==v for k,v in fingerprint.items()) and dest.is_file():
            data = dest.read_bytes()
            if len(data)>1000 and digest(data)==old["mp3_sha256"]:
                print(f"SKIP {index}/5 {key}",flush=True)
                continue
        dest.parent.mkdir(parents=True,exist_ok=True)
        tmp = dest.with_suffix(".partial.mp3")
        tmp.unlink(missing_ok=True)
        print(f"MAKE {index}/5 {key}",flush=True)
        generate_tts_mp3(text=recording["text"],out_path=tmp,
                         voice_id=profile["voice_id"],settings=profile["settings"],
                         language=lang,overwrite=True,play=False)
        data=tmp.read_bytes()
        if len(data)<=1000 or not (data.startswith(b"ID3") or data[:1]==b"\xff"):
            raise ValueError(f"Invalid audio: {tmp}")
        os.replace(tmp,dest)
        manifest["recordings"][key]={**fingerprint,"mp3_sha256":digest(data),"bytes":len(data)}
        save_manifest(manifest_path,manifest)
    print("Staged five shared-track intro corrections",flush=True)


def verified_recordings(plan_path: Path, output_dir: Path) -> list[dict]:
    plan=read_corrections(plan_path)
    manifest=json.loads((output_dir/"manifest.json").read_text(encoding="utf-8"))
    if manifest["plan_sha256"]!=digest(plan_path.read_bytes()):
        raise ValueError("Shared-track manifest does not match its plan")
    verified=[]
    for record in plan["recordings"]:
        key=f"{record['kind']}:{record['ranking_id']}:{record['lang']}"
        item=manifest["recordings"][key]
        path=output_dir/item["relative_path"]
        data=path.read_bytes()
        if len(data)<=1000 or (digest(data),len(data),digest(record["text"].encode())) != (
            item["mp3_sha256"],item["bytes"],item["intro_sha256"]):
            raise ValueError(f"Shared-track MP3 changed: {path}")
        verified.append({**record,"path":path,"sha256":item["mp3_sha256"]})
    return verified


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    stage(args.plan,args.output_dir)


if __name__=="__main__":
    main()
