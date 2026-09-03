import json
from pathlib import Path
import subprocess
import sys
import pytest

from backend.config import TTS_PROFILES as CONFIG_TTS_PROFILES
from backend.config.tts_config import TTS_PROFILES as ESTABLISHED_TTS_PROFILES
from backend.scripts.catalogs.tv_themes_1950s_pipeline import (
    CATALOG_ID,
    CATALOG_SLUG,
    build_text_bundle,
    canonical_key,
    approved_english_intros,
    apply_catalog_rankings,
    completeness_report,
    expected_narration,
    load_json,
    plan_summary,
    validate_production_plan,
)
from backend.models.dbmodels import Track, TrackRanking


ROOT = Path(__file__).parents[1] / "scripts/catalogs/review_manifests"
MANIFEST = ROOT / "1950s-tv_themes.v9.json"
PLAN = ROOT / "1950s-tv-themes.production-plan.v1.json"


def _inputs():
    return load_json(MANIFEST), load_json(PLAN)


def test_production_plan_is_exactly_the_authoritative_playable_set_and_is_unapplied():
    manifest, plan = _inputs()
    entries = validate_production_plan(manifest, plan)
    assert plan["status"] == "final_production_order_approved_not_applied"
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


def test_every_draft_has_a_concise_short_form_and_four_natural_long_sentences():
    _, plan = _inputs()
    records = build_text_bundle(plan)
    for language in ("en", "es", "pt-BR"):
        shorts = [row["text"] for row in records if row["language"] == language and row["narration_type"] == "short_detail"]
        assert len(shorts) == 19
        assert all(20 <= len(text.replace(",", "").replace(".", "").split()) <= 35 for text in shorts)
        for narration_type in ("intro", "short_detail", "long_detail"):
            texts = [row["text"] for row in records if row["language"] == language and row["narration_type"] == narration_type]
            assert len(texts) == len(set(texts)) == 19
    longs = [row["text"] for row in records if row["narration_type"] == "long_detail"]
    assert all(text.count(".") == 4 for text in longs)
    localized = [row["text"] for row in records if row["language"] in {"es", "pt-BR"}]
    assert not any("Gary accepted" in text or "Recording qualification" in text for text in localized)


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


def test_importer_validates_exactly_one_nonblank_matching_english_intro_per_rank_before_apply():
    _, plan = _inputs()
    entries = plan["ranked_candidates"]
    records = build_text_bundle(plan)
    intros = approved_english_intros(entries, records)
    assert len(intros) == 19
    assert all(intros[(entry["proposed_rank"], entry["spotify_track_id"])] for entry in entries)
    broken = [dict(row) for row in records]
    next(row for row in broken if row["language"] == "en" and row["narration_type"] == "intro")["text"] = ""
    with pytest.raises(ValueError, match="invalid English intro"):
        approved_english_intros(entries, broken)
    missing = [row for row in records if not (row["language"] == "en" and row["narration_type"] == "intro" and row["ranking"] == 1)]
    with pytest.raises(ValueError, match="exactly one English intro"):
        approved_english_intros(entries, missing)


class _Result:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class _RollbackSession:
    def __init__(self, tracks, existing, fail_commit=False):
        self._results = [tracks, existing]
        self.added, self.deleted, self.flushes = [], [], 0
        self.fail_commit, self.committed, self.rolled_back = fail_commit, False, False
    def exec(self, _statement): return _Result(self._results.pop(0))
    def add(self, item): self.added.append(item)
    def delete(self, item): self.deleted.append(item)
    def flush(self): self.flushes += 1
    def commit(self):
        if self.fail_commit: raise RuntimeError("simulated database failure")
        self.committed = True
    def rollback(self): self.rolled_back = True


def test_importer_never_inserts_null_intros_and_rolls_back_on_commit_failure():
    _, plan = _inputs()
    entries, records = plan["ranked_candidates"], build_text_bundle(plan)
    intros = approved_english_intros(entries, records)
    tracks = [Track(id=100 + index, track_name=entry["theme_title"], spotify_track_id=entry["spotify_track_id"], artist_id=1) for index, entry in enumerate(entries)]
    old = [TrackRanking(id=1, track_id=1, decade_genre_id=63, ranking=1, intro="old")]
    session = _RollbackSession(tracks, old)
    apply_catalog_rankings(session, entries, intros, create_missing_tracks=False)
    inserted = [item for item in session.added if isinstance(item, TrackRanking)]
    assert len(inserted) == 19
    assert [item.intro for item in inserted] == [intros[(entry["proposed_rank"], entry["spotify_track_id"])] for entry in entries]
    assert all(item.intro is not None for item in inserted)
    assert session.committed is True
    failing = _RollbackSession(tracks, old, fail_commit=True)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        apply_catalog_rankings(failing, entries, intros, create_missing_tracks=False)
    assert failing.rolled_back is True


def test_tts_executor_has_an_explicit_resume_mode_for_interrupted_authorized_runs():
    source = (Path(__file__).parents[1] / "scripts/catalogs/generate_1950s_tv_themes_tts.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--resume"' in source
    assert 'parser.add_argument("--max-generate"' in source
    assert 'parser.add_argument("--verified-existing-records"' in source
    assert "object existence alone does not prove narration content" in source
    assert "audio_sha256" in source
    assert "if narration_identity(record) in existing:" in source


def test_ptbr_intro_voice_matches_established_tts_config_not_the_placeholder():
    assert CONFIG_TTS_PROFILES["pt-BR"]["intro"] == ESTABLISHED_TTS_PROFILES["pt-BR"]["intro"]
    assert CONFIG_TTS_PROFILES["pt-BR"]["intro"]["voice_id"] == "cyD08lEy76q03ER1jZ7y"
