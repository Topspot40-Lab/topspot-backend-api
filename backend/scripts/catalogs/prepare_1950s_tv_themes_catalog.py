"""Plan or explicitly replace rankings for the 1950s TV Themes catalog."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from backend.scripts.catalogs.tv_themes_1950s_pipeline import load_json, plan_summary, replace_catalog_rankings, validate_production_plan

ROOT = Path(__file__).parent / "review_manifests"
def main() -> None:
    parser = argparse.ArgumentParser(description="Default is a no-write plan for catalog id 63 only.")
    parser.add_argument("--apply", action="store_true", help="explicitly replace only catalog id 63 rankings")
    parser.add_argument("--create-missing-tracks", action="store_true", help="create only missing approved candidate Track/Artist rows")
    args = parser.parse_args()
    manifest, plan = load_json(ROOT / "1950s-tv_themes.v9.json"), load_json(ROOT / "1950s-tv-themes.production-plan.v1.json")
    entries = validate_production_plan(manifest, plan)
    if not args.apply:
        print(json.dumps(plan_summary(manifest, plan), indent=2)); return
    from sqlmodel import Session
    from backend.database import engine
    with Session(engine) as session:
        replace_catalog_rankings(session, entries, create_missing_tracks=args.create_missing_tracks)
        session.commit()
    print("Applied 19 replacement rankings to 1950s-tv_themes only.")
if __name__ == "__main__": main()
