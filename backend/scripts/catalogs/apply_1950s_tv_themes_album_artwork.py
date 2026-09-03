"""Persist established album artwork for the 19 catalog-63 TV-theme Track rows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.scripts.catalogs.tv_themes_1950s_pipeline import (
    album_artwork_records,
    apply_catalog_album_artwork,
    load_json,
    validate_production_plan,
)


ROOT = Path(__file__).parent / "review_manifests"


def main() -> None:
    parser = argparse.ArgumentParser(description="Default is a no-write artwork plan for catalog id 63 only.")
    parser.add_argument("--apply", action="store_true", help="explicitly update only catalog-63 Track.album_artwork fields")
    args = parser.parse_args()
    manifest = load_json(ROOT / "1950s-tv_themes.v9.json")
    plan = load_json(ROOT / "1950s-tv-themes.production-plan.v1.json")
    records = album_artwork_records(validate_production_plan(manifest, plan))
    if not args.apply:
        print(json.dumps({"mode": "plan-only", "catalog_id": 63, "track_artwork_updates": len(records), "database_writes": 0}, indent=2))
        return
    from sqlmodel import Session
    from backend.database import engine
    with Session(engine) as session:
        apply_catalog_album_artwork(session, records)
    print("Applied album artwork to 19 unshared catalog-63 Track rows only.")


if __name__ == "__main__":
    main()
