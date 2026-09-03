"""Plan or explicitly replace rankings for the 1950s TV Themes catalog."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from backend.scripts.catalogs.tv_themes_1950s_pipeline import approved_english_intros, apply_catalog_rankings, load_json, plan_summary, validate_production_plan

ROOT = Path(__file__).parent / "review_manifests"
def main() -> None:
    parser = argparse.ArgumentParser(description="Default is a no-write plan for catalog id 63 only.")
    parser.add_argument("--apply", action="store_true", help="explicitly replace only catalog id 63 rankings")
    parser.add_argument("--create-missing-tracks", action="store_true", help="create only missing approved candidate Track/Artist rows")
    parser.add_argument("--text-records", type=Path, default=ROOT / "1950s-tv-themes.narration-text.v1.json")
    args = parser.parse_args()
    manifest, plan = load_json(ROOT / "1950s-tv_themes.v9.json"), load_json(ROOT / "1950s-tv-themes.production-plan.v1.json")
    entries = validate_production_plan(manifest, plan)
    english_intros = approved_english_intros(entries, load_json(args.text_records)["records"])
    if not args.apply:
        print(json.dumps(plan_summary(manifest, plan), indent=2)); return
    from sqlmodel import Session
    from backend.database import engine
    with Session(engine) as session:
        apply_catalog_rankings(session, entries, english_intros, create_missing_tracks=args.create_missing_tracks)
    print("Applied 19 replacement rankings to 1950s-tv_themes only.")
if __name__ == "__main__": main()
