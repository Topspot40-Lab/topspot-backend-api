"""Generate the reviewed Collection intro MP3s locally, with safe resume.

    python -m backend.scripts.stage_collection_gap_intros \
        --plan collection-gap-reviewed.json --output-dir collection-gap-audio

This command calls ElevenLabs (99 intros, billed by the provider). It does not
write to the database or Supabase Storage. Re-running it skips verified output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

LANGUAGES = ("en", "es", "pt-BR")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_plan(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    programs = plan["programs"]
    if len(programs) != 17 or sum(len(p["moves"]) for p in programs) != 33:
        raise ValueError("Expected 17 Collections and 33 moved tracks")
    seen = set()
    for program in programs:
        slug = program["slug"]
        if not re.fullmatch(r"[a-z0-9_]+", slug):
            raise ValueError(f"Unexpected slug: {slug!r}")
        for move in program["moves"]:
            rid = move["ranking_id"]
            if rid in seen:
                raise ValueError(f"Duplicate ranking ID: {rid}")
            seen.add(rid)
            if move["old_rank"] <= move["new_rank"]:
                raise ValueError(f"Expected a tail track for ranking ID {rid}")
            if set(move["intros_after"]) != set(LANGUAGES):
                raise ValueError(f"Missing reviewed language for ranking ID {rid}")
            for lang in LANGUAGES:
                words = move["intros_after"][lang]
                if not isinstance(words, str) or not words.strip() or words == move["intros_before"][lang]:
                    raise ValueError(f"Intro not revised: {rid}/{lang}")
                expected_key = f"collections-intros/{slug}_{move['new_rank']:02d}.mp3"
                if move["audio_after"][lang] != expected_key:
                    raise ValueError(f"Unexpected audio key: {rid}/{lang}")
    return plan


def save_manifest(path: Path, manifest: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def stage(plan_path: Path, output_dir: Path) -> None:
    plan = read_plan(plan_path)
    plan_hash = digest(plan_path.read_bytes())
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["plan_sha256"] != plan_hash:
            raise ValueError("The reviewed plan changed. Use a fresh output directory")
    else:
        manifest = {"plan_sha256": plan_hash, "recordings": {}}
        save_manifest(manifest_path, manifest)

    # The backend uses this same voice profile for its existing Collection intros.
    from dotenv import load_dotenv
    load_dotenv()
    from backend.config.tts_config import TTS_PROFILES
    from backend.services.tts.elevenlabs_tts import generate_tts_mp3

    done = 0
    for program in plan["programs"]:
        for move in program["moves"]:
            for lang in LANGUAGES:
                words = move["intros_after"][lang]
                profile = TTS_PROFILES[lang]["intro"]
                profile_hash = digest(json.dumps(profile, sort_keys=True).encode())
                key = f"{move['ranking_id']}:{lang}"
                dest = output_dir / lang / f"{program['slug']}_{move['new_rank']:02d}.mp3"
                expected = {"intro_sha256": digest(words.encode("utf-8")),
                            "profile_sha256": profile_hash, "relative_path": dest.relative_to(output_dir).as_posix()}
                record = manifest["recordings"].get(key)
                if record and all(record.get(k) == v for k, v in expected.items()) and dest.is_file():
                    audio_bytes = dest.read_bytes()
                    if len(audio_bytes) > 1000 and digest(audio_bytes) == record["mp3_sha256"]:
                        done += 1
                        print(f"SKIP {done}/99 {key}", flush=True)
                        continue

                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".partial.mp3")
                tmp.unlink(missing_ok=True)
                print(f"MAKE {done+1}/99 {program['slug']} #{move['new_rank']} {lang}", flush=True)
                generate_tts_mp3(text=words, out_path=tmp,
                                 voice_id=profile["voice_id"], settings=profile["settings"],
                                 language=lang, overwrite=True, play=False)
                audio_bytes = tmp.read_bytes()
                if len(audio_bytes) <= 1000 or not (audio_bytes.startswith(b"ID3") or audio_bytes[:1] == b"\xff"):
                    raise ValueError(f"Generated audio looks invalid: {tmp}")
                os.replace(tmp, dest)
                manifest["recordings"][key] = {**expected, "mp3_sha256": digest(audio_bytes), "bytes": len(audio_bytes)}
                save_manifest(manifest_path, manifest)
                done += 1
    print(f"Staged {done} reviewed intro recordings in {output_dir}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    stage(args.plan, args.output_dir)


if __name__ == "__main__":
    main()
