"""Explicit full-replacement TTS executor for the 1950s TV Themes catalog.

Without both flags this is a plan only. It never accepts a partial batch, so a
later authorized run cannot intentionally mix old and new narration.
"""
from __future__ import annotations
import argparse
import json
import tempfile
from pathlib import Path
from backend.scripts.catalogs.tv_themes_1950s_pipeline import completeness_report, expected_narration, load_json, narration_identity, replace_catalog_tts_mappings, validate_production_plan

ROOT = Path(__file__).parent / "review_manifests"
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-records", type=Path, required=True)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--replace-all-narration", action="store_true")
    parser.add_argument("--resume", action="store_true", help="skip already-present canonical keys after an interrupted run")
    parser.add_argument("--max-generate", type=int, default=None, help="bounded resume batch; defers DB key mapping until a final complete run")
    args = parser.parse_args()
    manifest, plan = load_json(ROOT / "1950s-tv_themes.v9.json"), load_json(ROOT / "1950s-tv-themes.production-plan.v1.json")
    validate_production_plan(manifest, plan)
    expected, texts = expected_narration(plan), load_json(args.text_records)["records"]
    text_report = completeness_report(expected, texts, [])
    if len(texts) != 171 or text_report["missing_text"] or text_report["unexpected_text"]:
        raise SystemExit("refusing TTS: text bundle is not the exact 171-record scoped replacement")
    if not (args.generate and args.replace_all_narration):
        print(json.dumps({"mode":"plan-only","expected_mp3s":171,"replacement_required":True,"paid_service_calls":0}, indent=2)); return
    from backend.config.tts_config import TTS_PROFILES
    from backend.services.supabase_storage import object_exists_cached, upload_bytes
    from backend.services.tts.elevenlabs_tts import generate_tts_mp3
    text_by_identity = {narration_identity(row): row["text"] for row in texts}
    existing = set()
    if args.resume:
        existing = {narration_identity(record) for record in expected if object_exists_cached(record["bucket"], record["key"])}
    generated = 0
    for record in expected:
        if narration_identity(record) in existing:
            continue
        if args.max_generate is not None and generated >= args.max_generate:
            break
        kind = "intro" if record["narration_type"] == "intro" else "detail"
        profile = TTS_PROFILES[record["language"]][kind]
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            temp_path = Path(tmp.name)
        try:
            generate_tts_mp3(text=text_by_identity[narration_identity(record)], out_path=temp_path, voice_id=profile["voice_id"], settings=profile.get("settings"), language=record["language"], overwrite=True)
            upload_bytes(record["bucket"], record["key"], temp_path.read_bytes(), "audio/mpeg")
            generated += 1
        finally:
            temp_path.unlink(missing_ok=True)
    if args.max_generate is not None:
        print(f"Generated {generated}; reused {len(existing)} existing scoped MP3s; DB mappings deferred until final completion.")
        return
    from sqlmodel import Session
    from backend.database import engine
    with Session(engine) as session:
        replace_catalog_tts_mappings(session, expected)
        session.commit()
    print(f"Generated {generated}; reused {len(existing)} existing scoped MP3s; run completeness validation before release.")
if __name__ == "__main__": main()
