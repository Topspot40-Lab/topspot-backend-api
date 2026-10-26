"""Validate all locally generated Collection intro recordings before upload.

    python -m backend.scripts.verify_collection_gap_audio \
        --plan collection-gap-reviewed.json --audio-dir collection-gap-audio
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.scripts.stage_collection_gap_intros import LANGUAGES, digest, read_plan


def verified_recordings(plan_path: Path, audio_dir: Path) -> list[dict]:
    plan = read_plan(plan_path)
    manifest_path = audio_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["plan_sha256"] != digest(plan_path.read_bytes()):
        raise ValueError("Audio manifest belongs to another reviewed plan")
    result = []
    for program in plan["programs"]:
        for move in program["moves"]:
            for lang in LANGUAGES:
                item = manifest["recordings"].get(f"{move['ranking_id']}:{lang}")
                if item is None:
                    raise ValueError(f"No recording for ranking {move['ranking_id']}/{lang}")
                filename = f"{program['slug']}_{move['new_rank']:02d}.mp3"
                relative = f"{lang}/{filename}"
                if item["relative_path"] != relative:
                    raise ValueError(f"Wrong filename for ranking {move['ranking_id']}/{lang}")
                if item["intro_sha256"] != digest(move["intros_after"][lang].encode()):
                    raise ValueError(f"Text changed since recording ranking {move['ranking_id']}/{lang}")
                path = audio_dir / relative
                data = path.read_bytes()
                if len(data) <= 1000 or len(data) != item["bytes"] or digest(data) != item["mp3_sha256"]:
                    raise ValueError(f"Audio differs from manifest: {path}")
                result.append({"bucket": {"en": "audio-en", "es": "audio-es", "pt-BR": "audio-ptbr"}[lang],
                               "key": move["audio_after"][lang], "path": path,
                               "sha256": item["mp3_sha256"]})
    if len(result) != 99 or len({(r["bucket"], r["key"]) for r in result}) != 99:
        raise ValueError("Expected 99 unique replacement audio objects")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--audio-dir", required=True, type=Path)
    args = parser.parse_args()
    recordings = verified_recordings(args.plan, args.audio_dir)
    print(f"Verified {len(recordings)} MP3s against their reviewed text and manifest")


if __name__ == "__main__":
    main()
