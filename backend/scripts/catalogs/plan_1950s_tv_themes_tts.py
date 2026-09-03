"""Produce a no-write plan for the 171 replacement narration MP3s."""
from __future__ import annotations
import json
from pathlib import Path
from backend.scripts.catalogs.tv_themes_1950s_pipeline import expected_narration, load_json, validate_production_plan

ROOT = Path(__file__).parent / "review_manifests"
def main() -> None:
    manifest, plan = load_json(ROOT / "1950s-tv_themes.v9.json"), load_json(ROOT / "1950s-tv-themes.production-plan.v1.json")
    validate_production_plan(manifest, plan)
    records = expected_narration(plan)
    print(json.dumps({"mode":"plan-only","expected_mp3s":len(records),"replacement_required":True,"external_calls":0,"records":records}, indent=2))
if __name__ == "__main__": main()
