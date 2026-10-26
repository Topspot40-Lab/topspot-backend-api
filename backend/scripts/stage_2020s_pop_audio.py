"""Generate the 60 reviewed 2020s Pop narrations locally; safely resumes.

    python -m backend.scripts.stage_2020s_pop_audio \
      --plan 2020s-pop-reviewed.json --audio-check 2020s-pop-audio-check.json \
      --output-dir 2020s-pop-audio

This calls ElevenLabs; it does not change the database or Supabase Storage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

LANGUAGES = ("en", "es", "pt-BR")
BUCKETS = {"en": "audio-en", "es": "audio-es", "pt-BR": "audio-ptbr"}
RANKS = (6, 7, 8, 9, 10, 11, 12, 28, 44, 45)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_plan(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan["version"] != 1 or plan["program"] != {"id": 22, "decade": "2020s", "genre": "pop"}:
        raise ValueError("Not the reviewed 2020s Pop plan")
    additions = plan["additions"]
    if tuple(a["rank"] for a in additions) != RANKS or len(plan["snapshot_rankings"]) != 35:
        raise ValueError("Unexpected rankings in reviewed plan")
    if sum(a["reuse_track_id"] is None for a in additions) != 6 or sum(a["reuse_artist_id"] is None for a in additions) != 4:
        raise ValueError("Unexpected track or artist reuse")
    for a in additions:
        if not re.fullmatch(r"[A-Za-z0-9]{22}", a["spotify_track_id"]) or not re.fullmatch(r"[A-Za-z0-9]{22}", a["spotify_artist_id"]):
            raise ValueError(f"Invalid Spotify identifier at rank {a['rank']}")
        for kind, field, expected in (("intro", "intro", True), ("detail", "detail", a["reuse_track_id"] is None), ("artist", "artist_bio", a["reuse_artist_id"] is None)):
            words = a[field]
            if bool(words) != expected:
                raise ValueError(f"Unexpected {kind} narration at rank {a['rank']}")
            if words and (set(words) != set(LANGUAGES) or any(not isinstance(words[lang], str) or len(words[lang].strip()) < 20 for lang in LANGUAGES)):
                raise ValueError(f"Incomplete {kind} narration at rank {a['rank']}")
    return plan


def read_audio_check(path: Path) -> dict:
    check = json.loads(path.read_text(encoding="utf-8"))
    if check["confirmed_missing"] or check["download_errors"] or check["preflight_missing"] != len(check["found_by_download"]):
        raise ValueError("Reused audio was not fully verified by download")
    return check


def specifications(plan: dict) -> list[dict]:
    specs = []
    for a in plan["additions"]:
        for kind, field, key in (
            ("intro", "intro", f"intro/2020s_pop_{a['rank']:02d}.mp3"),
            ("detail", "detail", f"detail/{a['spotify_track_id']}.mp3"),
            ("artist", "artist_bio", f"artist/{a['spotify_artist_id']}.mp3"),
        ):
            if not a[field]:
                continue
            for lang in LANGUAGES:
                specs.append({"id": f"{kind}:{a['rank']}:{lang}", "kind":kind, "lang":lang,
                              "rank":a["rank"], "text":a[field][lang], "bucket":BUCKETS[lang],
                              "key":key, "relative_path":f"{lang}/{kind}/{key.split('/')[-1]}"})
    if len(specs) != 60 or len({(s["bucket"], s["key"]) for s in specs}) != 60:
        raise ValueError("Expected 60 distinct local and remote recordings")
    return specs


def save_manifest(path: Path, manifest: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def stage(plan_path: Path, audio_check_path: Path, output_dir: Path) -> None:
    plan = read_plan(plan_path)
    read_audio_check(audio_check_path)
    specs = specifications(plan)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    plan_hash = digest(plan_path.read_bytes())
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["plan_sha256"] != plan_hash:
            raise ValueError("Reviewed plan changed; choose a new output directory")
    else:
        manifest = {"plan_sha256":plan_hash, "recordings":{}}
        save_manifest(manifest_path, manifest)

    from dotenv import load_dotenv
    load_dotenv()
    from backend.config.tts_config import TTS_PROFILES
    from backend.services.tts.elevenlabs_tts import generate_tts_mp3

    for index, spec in enumerate(specs, 1):
        profile = TTS_PROFILES[spec["lang"]][spec["kind"]]
        fingerprint = {"relative_path":spec["relative_path"],
                       "text_sha256":digest(spec["text"].encode("utf-8")),
                       "profile_sha256":digest(json.dumps(profile, sort_keys=True).encode("utf-8"))}
        dest = output_dir / spec["relative_path"]
        saved = manifest["recordings"].get(spec["id"])
        if saved and all(saved.get(k) == v for k,v in fingerprint.items()) and dest.is_file():
            data = dest.read_bytes()
            if len(data) > 1000 and digest(data) == saved["mp3_sha256"]:
                print(f"SKIP {index}/60 {spec['id']}", flush=True)
                continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".partial.mp3")
        tmp.unlink(missing_ok=True)
        print(f"MAKE {index}/60 {spec['id']}", flush=True)
        generate_tts_mp3(text=spec["text"], out_path=tmp,
                         voice_id=profile["voice_id"], settings=profile["settings"],
                         language=spec["lang"], overwrite=True, play=False)
        data = tmp.read_bytes()
        if len(data) <= 1000 or not (data.startswith(b"ID3") or data[:1] == b"\xff"):
            raise ValueError(f"Invalid MP3: {tmp}")
        os.replace(tmp, dest)
        manifest["recordings"][spec["id"]] = {**fingerprint, "mp3_sha256":digest(data), "bytes":len(data)}
        save_manifest(manifest_path, manifest)
    print(f"Staged 60 reviewed recordings in {output_dir}", flush=True)


def verified_recordings(plan_path: Path, output_dir: Path) -> list[dict]:
    plan = read_plan(plan_path)
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest["plan_sha256"] != digest(plan_path.read_bytes()):
        raise ValueError("Audio manifest no longer matches the plan")
    from backend.config.tts_config import TTS_PROFILES
    results = []
    for spec in specifications(plan):
        record = manifest["recordings"].get(spec["id"])
        if not record or record["relative_path"] != spec["relative_path"]:
            raise ValueError(f"Missing staged recording {spec['id']}")
        if record["text_sha256"] != digest(spec["text"].encode("utf-8")) or record["profile_sha256"] != digest(json.dumps(TTS_PROFILES[spec["lang"]][spec["kind"]], sort_keys=True).encode("utf-8")):
            raise ValueError(f"Staged narration text or voice differs at {spec['id']}")
        data = (output_dir / record["relative_path"]).read_bytes()
        if len(data) <= 1000 or len(data) != record["bytes"] or digest(data) != record["mp3_sha256"]:
            raise ValueError(f"Staged MP3 changed at {spec['id']}")
        results.append({**spec, "sha256":record["mp3_sha256"], "path":output_dir / record["relative_path"]})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--audio-check", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    stage(args.plan, args.audio_check, args.output_dir)


if __name__ == "__main__":
    main()
