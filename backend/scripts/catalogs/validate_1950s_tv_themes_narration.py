"""Validate scoped text/audio record manifests without network or database access."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from backend.scripts.catalogs.tv_themes_1950s_pipeline import completeness_report, expected_narration, live_database_narration_rows, load_json, validate_production_plan

ROOT = Path(__file__).parent / "review_manifests"
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-records", type=Path, required=True)
    parser.add_argument("--audio-records", type=Path, help="local audio record manifest; required unless --live")
    parser.add_argument("--live", action="store_true", help="read database and storage; never writes")
    parser.add_argument("--text-only", action="store_true", help="validate the 171 text records before TTS is authorized")
    args = parser.parse_args()
    manifest, plan = load_json(ROOT / "1950s-tv_themes.v9.json"), load_json(ROOT / "1950s-tv-themes.production-plan.v1.json")
    validate_production_plan(manifest, plan)
    expected = expected_narration(plan)
    texts = load_json(args.text_records)["records"]
    if args.text_only and args.live:
        parser.error("--text-only and --live cannot be combined")
    if args.text_only:
        audio, mapped = [], "not_checked"
    elif args.live:
        from sqlmodel import Session
        from backend.database import engine
        from backend.services.supabase_storage import object_exists_cached
        with Session(engine) as session:
            texts, mapped = live_database_narration_rows(session, expected)
        audio = [row for row in expected if object_exists_cached(row["bucket"], row["key"])]
    else:
        if args.audio_records is None:
            parser.error("--audio-records is required unless --live is used")
        audio = load_json(args.audio_records)["records"]
        mapped = "not_checked"
    report = completeness_report(expected, texts, audio)
    report["database_mapping_count"] = mapped
    report["text_complete"] = not report["missing_text"] and not report["unexpected_text"]
    if args.text_only:
        report["audio_not_checked_count"] = len(expected)
        report["missing_audio"] = []
        report["complete"] = report["text_complete"]
        report["audio_checked"] = False
    print(json.dumps(report, indent=2))
if __name__ == "__main__": main()
