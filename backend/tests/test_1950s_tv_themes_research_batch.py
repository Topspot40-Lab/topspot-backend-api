import json
from pathlib import Path


RESEARCH_FILE = (
    Path(__file__).parents[1]
    / "scripts/catalogs/review_manifests/1950s-tv-themes.research-batch-01.v1.json"
)
REVIEW_MANIFEST = (
    Path(__file__).parents[1]
    / "scripts/catalogs/review_manifests/1950s-tv_themes.v2.json"
)
EXPECTED_RANKS = {2, 3, 8, 10, 11, 12}
APPROVED_REPLACEMENTS = {
    2: "799kpXdBhIzYscq144QVEn",
    3: "6cHhJfIQE4tOQ6fVcMm1CA",
    8: "4sYOSzhDiBZuX88Ylh7O2N",
    10: "12ynoGdWbebDuV61rsJyp1",
    12: "4nBCLGl2EXO3bIk30Jyv5b",
}


def _batch():
    return json.loads(RESEARCH_FILE.read_text(encoding="utf-8"))


def test_research_batch_has_the_expected_read_only_structure():
    batch = _batch()
    assert batch["schema_version"] == "1950s-tv-themes-research-batch/v1"
    assert "no Spotify authentication" in batch["research_method"]
    assert "Dragnet candidates remain pending Gary" in batch["approval_gate"]
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
            assert candidate["recording_claim"] in {"claims original", "soundtrack", "rerecorded", "cover", "uncertain"}
            assert candidate["evidence_source_urls"] and candidate["listening_note"]
            if candidate["spotify_track_id"]:
                assert candidate["spotify_url"].endswith(candidate["spotify_track_id"])


def test_no_candidate_is_preapproved_or_ranked():
    contents = RESEARCH_FILE.read_text(encoding="utf-8").lower()
    assert '"final_rank"' not in contents


def test_garys_five_exact_approvals_are_separate_from_pending_database_replacements():
    manifest = json.loads(REVIEW_MANIFEST.read_text(encoding="utf-8"))
    decisions = {item["rank"]: item for item in manifest["recording_replacement_decisions"]}
    assert set(decisions) == EXPECTED_RANKS
    for rank, spotify_track_id in APPROVED_REPLACEMENTS.items():
        decision = decisions[rank]
        assert decision["historical_program_decision"] == "approved_historical_program"
        assert decision["current_database_recording_status"] == "rejected_wrong_recording_pending_replacement"
        assert decision["approved_exact_spotify_recording"]["spotify_track_id"] == spotify_track_id
        assert decision["approved_exact_spotify_recording"]["gary_listening_decision"] == "approved"
    assert decisions[11]["approved_exact_spotify_recording"] is None
    assert decisions[11]["gary_listening_decision"] == "pending"


def test_dragnet_candidates_have_public_ids_and_remain_pending():
    dragnet = next(program for program in _batch()["programs"] if program["existing_rank"] == 11)
    assert len(dragnet["spotify_candidates"]) == 3
    for candidate in dragnet["spotify_candidates"]:
        assert candidate["spotify_track_id"]
        assert candidate["spotify_url"].endswith(candidate["spotify_track_id"])
        assert candidate["gary_listening_decision"] == "pending"
