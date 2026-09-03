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
REVIEW_MANIFEST_V3 = (
    Path(__file__).parents[1]
    / "scripts/catalogs/review_manifests/1950s-tv_themes.v3.json"
)
REVIEW_MANIFEST_V4 = (
    Path(__file__).parents[1]
    / "scripts/catalogs/review_manifests/1950s-tv_themes.v4.json"
)
REVIEW_MANIFEST_V5 = (
    Path(__file__).parents[1]
    / "scripts/catalogs/review_manifests/1950s-tv_themes.v5.json"
)
RANKED_REVIEW = (
    Path(__file__).parents[1]
    / "scripts/catalogs/review_manifests/1950s-tv-themes.ranked-review.v1.csv"
)
RESEARCH_BATCH_02 = (
    Path(__file__).parents[1]
    / "scripts/catalogs/review_manifests/1950s-tv-themes.research-batch-02.v1.json"
)
RESEARCH_BATCH_03 = (
    Path(__file__).parents[1]
    / "scripts/catalogs/review_manifests/1950s-tv-themes.research-batch-03.v1.json"
)
EXPECTED_RANKS = {2, 3, 8, 10, 11, 12}
APPROVED_REPLACEMENTS = {
    2: "799kpXdBhIzYscq144QVEn",
    3: "6cHhJfIQE4tOQ6fVcMm1CA",
    8: "4sYOSzhDiBZuX88Ylh7O2N",
    10: "12ynoGdWbebDuV61rsJyp1",
    11: "5Iyz89IZQSNtATjrTwpO2H",
    12: "4nBCLGl2EXO3bIk30Jyv5b",
}


def _batch():
    return json.loads(RESEARCH_FILE.read_text(encoding="utf-8"))


def test_research_batch_has_the_expected_read_only_structure():
    batch = _batch()
    assert batch["schema_version"] == "1950s-tv-themes-research-batch/v1"
    assert "no Spotify authentication" in batch["research_method"]
    assert "six explicitly marked exact Spotify recordings" in batch["approval_gate"]
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
    assert decisions[11]["approved_exact_spotify_recording"]["spotify_track_id"] == "5Iyz89IZQSNtATjrTwpO2H"


def test_dragnet_candidates_have_public_ids_and_only_the_approved_one_is_not_pending():
    dragnet = next(program for program in _batch()["programs"] if program["existing_rank"] == 11)
    assert len(dragnet["spotify_candidates"]) == 3
    for candidate in dragnet["spotify_candidates"]:
        assert candidate["spotify_track_id"]
        assert candidate["spotify_url"].endswith(candidate["spotify_track_id"])
        expected = "approved" if candidate["spotify_track_id"] == "5Iyz89IZQSNtATjrTwpO2H" else "pending"
        assert candidate["gary_listening_decision"] == expected


def test_ranked_review_keeps_approved_recordings_and_defers_batman():
    import csv

    with RANKED_REVIEW.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    keepers = [row for row in rows if row["status"] == "keep"]
    assert [int(row["proposed_rank"]) for row in keepers] == list(range(1, 14))
    assert {row["spotify_track_id"] for row in keepers} >= set(APPROVED_REPLACEMENTS.values())
    batman = next(row for row in rows if row["program_name"] == "Batman")
    assert batman["status"] == "defer"


def test_conditional_listening_approvals_and_next_batch_are_explicit():
    batch = json.loads(RESEARCH_BATCH_02.read_text(encoding="utf-8"))
    approvals = batch["historically_accepted_catalog_candidates"]
    assert {item["spotify_track_id"] for item in approvals} == {
        "5lSfu6Bb1lZHvEA5Lp3FSo", "71qlBJvHesvpK3TJXGN95O",
        "2esm55sr13FFKqoP6qwjUz", "301w6yavJnABE4APW72ynW",
    }
    relationships = {item["show_title"]: item["historical_relationship"] for item in approvals}
    assert relationships["I Love Lucy"] == relationships["Gunsmoke"] == relationships["Zorro"] == "recognizable cover"
    assert relationships["The Twilight Zone"] == "soundtrack-derived first-season television theme"
    twilight = next(item for item in approvals if item["show_title"] == "The Twilight Zone")
    assert twilight["spotify_track_id"] == "2esm55sr13FFKqoP6qwjUz"


def test_conditional_approvals_are_listening_only_and_not_catalog_acceptance():
    manifest = json.loads(REVIEW_MANIFEST_V3.read_text(encoding="utf-8"))
    assert manifest["supersedes"] == "1950s-tv_themes.v2.json"
    decisions = manifest["conditional_listening_approvals"]
    assert {decision["show_title"] for decision in decisions} == {
        "I Love Lucy", "Gunsmoke", "Zorro"
    }
    for decision in decisions:
        assert decision["catalog_acceptance_status"] == "pending_historical_acceptance"
        approved = decision["approved_exact_spotify_recording"]
        assert approved["gary_listening_decision"] == "approved"
        assert approved["recording_classification"] == "recognizable_cover"


def test_v4_promotes_exactly_four_catalog_candidates_without_apply_authority():
    manifest = json.loads(REVIEW_MANIFEST_V4.read_text(encoding="utf-8"))
    assert manifest["supersedes"] == "1950s-tv_themes.v3.json"
    approved = {item["show_title"]: item for item in manifest["approved_catalog_candidates"]}
    assert set(approved) == {"I Love Lucy", "Gunsmoke", "The Twilight Zone", "Zorro"}
    assert approved["The Twilight Zone"]["spotify_track_id"] == "2esm55sr13FFKqoP6qwjUz"
    assert all(item["database_status"].endswith("no_database_apply_authorized") for item in approved.values())


def test_research_batch_three_preserves_two_approved_candidates_and_one_unresolved_program():
    batch = json.loads(RESEARCH_BATCH_03.read_text(encoding="utf-8"))
    programs = {item["show_title"]: item for item in batch["programs"]}
    assert set(programs) == {"Wagon Train", "Sea Hunt", "Davy Crockett"}
    for title in ("Wagon Train", "Davy Crockett"):
        candidate = programs[title]["spotify_candidate"]
        assert candidate["spotify_track_id"]
        assert candidate["spotify_url"].endswith(candidate["spotify_track_id"])
        assert programs[title]["gary_listening_decision"] == "approved"
        assert programs[title]["catalog_candidate_status"] == "approved_catalog_candidate"
    sea_hunt = programs["Sea Hunt"]["spotify_candidate"]
    assert sea_hunt["classification"] == "unresolved"
    assert sea_hunt["spotify_track_id"] == sea_hunt["spotify_url"] == ""


def test_v5_records_wagon_and_davy_qualifications_without_promoting_sea_hunt():
    manifest = json.loads(REVIEW_MANIFEST_V5.read_text(encoding="utf-8"))
    assert manifest["supersedes"] == "1950s-tv_themes.v4.json"
    approved = {item["show_title"]: item for item in manifest["approved_catalog_candidates"]}
    assert approved["Wagon Train"]["spotify_track_id"] == "7up8IVBnHisqNGn2ewyuyk"
    assert approved["Wagon Train"]["recording_classification"] == "uncertain_exact_release_lineage"
    assert approved["Davy Crockett"]["spotify_track_id"] == "3Gr3f20ajbTXP25lmrg2Qb"
    assert "1969_rerecording" in approved["Davy Crockett"]["recording_classification"]
    assert manifest["unresolved_research"] == [{
        "show_title": "Sea Hunt",
        "status": "unresolved_no_defensible_spotify_track_id",
        "spotify_track_id": "",
    }]
