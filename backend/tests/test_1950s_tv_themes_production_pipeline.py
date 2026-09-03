import json
from pathlib import Path
import subprocess
import sys

from backend.config import TTS_PROFILES as CONFIG_TTS_PROFILES
from backend.config.tts_config import TTS_PROFILES as ESTABLISHED_TTS_PROFILES
from backend.scripts.catalogs.tv_themes_1950s_pipeline import (
    CATALOG_ID,
    CATALOG_SLUG,
    build_text_bundle,
    canonical_key,
    completeness_report,
    expected_narration,
    load_json,
    plan_summary,
    validate_production_plan,
)


ROOT = Path(__file__).parents[1] / "scripts/catalogs/review_manifests"
MANIFEST = ROOT / "1950s-tv_themes.v9.json"
PLAN = ROOT / "1950s-tv-themes.production-plan.v1.json"


def _inputs():
    return load_json(MANIFEST), load_json(PLAN)


def test_production_plan_is_exactly_the_authoritative_playable_set_and_is_unapplied():
    manifest, plan = _inputs()
    entries = validate_production_plan(manifest, plan)
    assert plan["status"] == "proposed_ranking_not_applied"
    assert plan["catalog"] == {"decade_genre_id": CATALOG_ID, "slug": CATALOG_SLUG}
    assert [entry["proposed_rank"] for entry in entries] == list(range(1, 20))
    assert {entry["spotify_track_id"] for entry in entries} == {
        entry["spotify_track_id"] for entry in manifest["approved_catalog_candidates"] if entry["spotify_track_id"]
    }


def test_plan_has_the_required_171_scoped_audio_records_and_canonical_keys():
    _, plan = _inputs()
    expected = expected_narration(plan)
    assert len(expected) == 171
    assert {(row["language"], row["narration_type"]) for row in expected} == {
        (language, kind) for language in ("en", "es", "pt-BR") for kind in ("intro", "short_detail", "long_detail")
    }
    assert canonical_key(plan["ranked_candidates"][0], "intro") == "intro/1950s-tv_themes_01.mp3"
    assert all(row["catalog_id"] == 63 and row["catalog_slug"] == "1950s-tv_themes" for row in expected)


def test_deterministic_multilingual_text_bundle_is_complete_and_has_no_ai_dependency():
    _, plan = _inputs()
    text = build_text_bundle(plan)
    assert len(text) == 171
    assert {row["language"] for row in text} == {"en", "es", "pt-BR"}
    assert all(row["text"].strip() for row in text)
    source = Path(__file__).parents[1] / "scripts/catalogs/tv_themes_1950s_pipeline.py"
    assert "elevenlabs" not in source.read_text(encoding="utf-8").lower()
    assert "xai" not in source.read_text(encoding="utf-8").lower()


def test_completeness_validator_detects_missing_audio_and_wrong_key_without_external_reads():
    _, plan = _inputs()
    expected = expected_narration(plan)
    text = build_text_bundle(plan)
    complete_audio = [dict(row) for row in expected]
    report = completeness_report(expected, text, complete_audio)
    assert report["complete"] is True
    incomplete = complete_audio[:-1]
    incomplete[0]["key"] = "detail/not-the-canonical-key.mp3"
    report = completeness_report(expected, text, incomplete)
    assert report["complete"] is False
    assert len(report["missing_audio"]) == 1
    assert report["invalid_audio_keys"] == 1


def test_plan_mode_summary_is_explicitly_non_mutating():
    manifest, plan = _inputs()
    summary = plan_summary(manifest, plan)
    assert summary == {
        "mode": "plan-only", "catalog_slug": "1950s-tv_themes", "catalog_id": 63,
        "ranked_candidates": 19, "narration_files": 171,
        "narration_files_by_language": {"en": 57, "es": 57, "pt-BR": 57},
        "database_writes": 0, "storage_writes": 0, "paid_service_calls": 0,
    }


def test_importer_default_mode_is_a_no_write_plan():
    result = subprocess.run(
        [sys.executable, "-m", "backend.scripts.catalogs.prepare_1950s_tv_themes_catalog"],
        cwd=Path(__file__).parents[2], capture_output=True, text=True, check=True,
    )
    summary = json.loads(result.stdout)
    assert summary["mode"] == "plan-only"
    assert summary["database_writes"] == summary["storage_writes"] == summary["paid_service_calls"] == 0


def test_ptbr_intro_voice_matches_established_tts_config_not_the_placeholder():
    assert CONFIG_TTS_PROFILES["pt-BR"]["intro"] == ESTABLISHED_TTS_PROFILES["pt-BR"]["intro"]
    assert CONFIG_TTS_PROFILES["pt-BR"]["intro"]["voice_id"] == "cyD08lEy76q03ER1jZ7y"
