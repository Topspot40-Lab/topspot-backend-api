"""Build the approved registry manifest from the preserved Phase 2 audit."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "audits" / "program_code_phase2" / "program_code_phase2_mapping.json"
OUTPUT = ROOT / "data" / "program_code_manifest.json"


def build_manifest(audit: dict) -> dict:
    assignments = []
    for record in audit["records"]:
        identity = record["stable_target_identity"]
        if record["type"] == "nostalgia":
            assignments.append({"code": record["code"], "kind": "nostalgia", "target": {
                "decade_slug": identity["decade_slug"], "genre_slug": identity["genre_slug"],
            }})
        elif record["type"] == "collection":
            assignments.append({"code": record["code"], "kind": "collection", "target": {
                "slug": identity["collection_slug"],
            }})

    proposals = audit["proposed_assignments_requiring_gary_approval"]
    assignments.extend({
        "code": record["proposed_code"],
        "kind": "artist_spotlight",
        "target": {"artist_id": record["stable_target_identity"]["artist_id"]},
    } for record in proposals["artist_spotlights"])
    assignments.extend({
        "code": record["proposed_code"],
        "kind": "docuseries_story",
        "target": {"slug": record["stable_target_identity"]["music_docuseries_slug"]},
    } for record in proposals["docuseries_stories"])
    return {
        "version": 1,
        "approved": True,
        "source": "Phase 2 audit approved by Gary: 64 N, 52 C, 226 A, 127 D",
        "assignments": assignments,
    }


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    OUTPUT.write_text(json.dumps(build_manifest(audit), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
