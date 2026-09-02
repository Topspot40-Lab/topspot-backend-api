import json
from pathlib import Path


RESEARCH_FILE = (
    Path(__file__).parents[1]
    / "scripts/catalogs/review_manifests/1950s-tv-themes.research-batch-01.v1.json"
)
EXPECTED_RANKS = {2, 3, 8, 10, 11, 12}


def _batch():
    return json.loads(RESEARCH_FILE.read_text(encoding="utf-8"))


def test_research_batch_has_the_expected_read_only_structure():
    batch = _batch()
    assert batch["schema_version"] == "1950s-tv-themes-research-batch/v1"
    assert "no Spotify authentication" in batch["research_method"]
    assert batch["approval_gate"].startswith("Every Spotify candidate remains pending Gary")
    assert {program["existing_rank"] for program in batch["programs"]} == EXPECTED_RANKS


def test_each_rejected_program_has_identity_and_candidate_listening_data():
    for program in _batch()["programs"]:
        theme = program["historical_theme"]
        assert program["original_broadcast_years"]
        assert theme["official_title"] and theme["composer"] and theme["broadcast_version"]
        assert program["principal_characters"] and program["historical_source_urls"]
        rejected = program["current_rejected_recording"]
        assert rejected["spotify_track_id"] and rejected["spotify_url"] and rejected["rejection_basis"]
        for candidate in program["spotify_candidates"]:
            assert candidate["track_title"] and candidate["displayed_artist"]
            assert candidate["recording_claim"] in {"claims original", "soundtrack", "cover", "uncertain"}
            assert candidate["evidence_source_urls"] and candidate["listening_note"]
            if candidate["spotify_track_id"]:
                assert candidate["spotify_url"].endswith(candidate["spotify_track_id"])


def test_no_candidate_is_preapproved_or_ranked():
    contents = RESEARCH_FILE.read_text(encoding="utf-8").lower()
    assert '"approved"' not in contents
    assert '"final_rank"' not in contents
