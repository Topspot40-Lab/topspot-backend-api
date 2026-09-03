import csv
import re
from collections import Counter
from pathlib import Path


WORKSHEET = (
    Path(__file__).parents[1]
    / "scripts/catalogs/review_manifests/1950s-tv-themes.candidates.v1.csv"
)

GARY_DECISIONS = {
    "approved_current_recording",
    "approved_catalog_candidate",
    "rejected_wrong_recording",
    "unreviewed/incomplete",
}
HISTORICAL_STATUSES = {
    "research_needed",
    "historical_identity_verified",
    "historically_accepted",
    "deferred_to_1960s_queue",
}
SPOTIFY_STATUSES = {
    "research_needed",
    "candidate_public_track_verified",
    "verified_recognizable_cover",
    "verified_soundtrack_derived_first_season",
    "verified_uncertain_exact_release_lineage",
    "verified_1969_rerecording",
    "verified_public_alternative_no_spotify_id",
    "verified_later_issue_lineage_unconfirmed",
}
PROPOSED_ACTIONS = {
    "approved_catalog_candidate_pending_database_apply",
    "retain_current_recording_pending_historical_review",
    "research_replacement_recording",
    "research_and_complete",
    "research_show_identity_and_complete",
    "research_original_first_season_or_exclude",
    "move_to_1960s_review_queue",
    "reserve_for_historical_and_recording_research",
}


def _rows():
    with WORKSHEET.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _normalized_show_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def test_candidate_ids_are_unique_and_values_are_valid():
    rows = _rows()
    assert len(rows) == 54
    assert len({row["candidate_id"] for row in rows}) == len(rows)
    assert {row["gary_recording_decision"] for row in rows} <= GARY_DECISIONS
    assert {row["historical_review_status"] for row in rows} <= HISTORICAL_STATUSES
    assert {row["spotify_verification_status"] for row in rows} <= SPOTIFY_STATUSES
    assert {row["proposed_action"] for row in rows} <= PROPOSED_ACTIONS


def test_nonblank_normalized_show_titles_are_unique():
    titles = [_normalized_show_title(row["show_title"]) for row in _rows() if row["show_title"]]
    duplicates = [title for title, count in Counter(titles).items() if count > 1]
    assert duplicates == []


def test_garys_fourteen_manual_decisions_are_preserved():
    rows = _rows()
    original_decisions = {"approved_current_recording", "rejected_wrong_recording"}
    manual_rows = [
        row for row in rows
        if row["existing_rank"] and row["gary_recording_decision"] in original_decisions
    ]
    decisions_by_rank = {int(row["existing_rank"]): row["gary_recording_decision"] for row in manual_rows}
    assert decisions_by_rank == {
        1: "approved_current_recording", 2: "rejected_wrong_recording",
        3: "rejected_wrong_recording", 4: "approved_current_recording",
        5: "approved_current_recording", 6: "approved_current_recording",
        7: "approved_current_recording", 8: "rejected_wrong_recording",
        9: "approved_current_recording", 10: "rejected_wrong_recording",
        11: "rejected_wrong_recording", 12: "rejected_wrong_recording",
        14: "approved_current_recording", 39: "approved_current_recording",
    }
    assert Counter(decisions_by_rank.values()) == {
        "approved_current_recording": 8,
        "rejected_wrong_recording": 6,
    }


def test_new_catalog_candidates_are_approved_without_database_apply_authority():
    rows_by_title = {row["show_title"]: row for row in _rows() if row["show_title"]}
    for title in (
        "I Love Lucy", "Gunsmoke", "The Twilight Zone", "Zorro", "Wagon Train", "Davy Crockett",
        "Sea Hunt", "M Squad", "Bat Masterson", "The Untouchables",
    ):
        row = rows_by_title[title]
        assert row["gary_recording_decision"] == "approved_catalog_candidate"
        assert row["historical_review_status"] == "historically_accepted"
        assert row["proposed_action"] == "approved_catalog_candidate_pending_database_apply"
