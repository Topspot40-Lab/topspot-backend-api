"""Generate local, deterministic narration drafts only when explicitly requested."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from backend.scripts.catalogs.tv_themes_1950s_pipeline import build_text_bundle, load_json, validate_production_plan

ROOT = Path(__file__).parent / "review_manifests"
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-drafts", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "1950s-tv-themes.narration-text.v1.json")
    args = parser.parse_args()
    manifest, plan = load_json(ROOT / "1950s-tv_themes.v9.json"), load_json(ROOT / "1950s-tv-themes.production-plan.v1.json")
    validate_production_plan(manifest, plan)
    records = build_text_bundle(plan)
    if not args.write_drafts:
        print(json.dumps({"mode":"plan-only","text_records":len(records),"database_writes":0,"paid_service_calls":0}, indent=2)); return
    args.output.write_text(json.dumps({"schema_version":"catalog-narration-text/v1","catalog_slug":"1950s-tv_themes","records":records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
if __name__ == "__main__": main()
