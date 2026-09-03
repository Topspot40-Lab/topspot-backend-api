"""Explicitly replace all scoped narration text after human review."""
from __future__ import annotations
import argparse
from pathlib import Path
from backend.scripts.catalogs.tv_themes_1950s_pipeline import load_json, replace_catalog_narration_text

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-records", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace-all-narration", action="store_true")
    args = parser.parse_args()
    records = load_json(args.text_records)["records"]
    if not (args.apply and args.replace_all_narration):
        print("PLAN ONLY: pass --apply --replace-all-narration to replace all 171 text records."); return
    from sqlmodel import Session
    from backend.database import engine
    with Session(engine) as session:
        replace_catalog_narration_text(session, records)
        session.commit()
    print("Replaced all 171 scoped narration text records.")
if __name__ == "__main__": main()
