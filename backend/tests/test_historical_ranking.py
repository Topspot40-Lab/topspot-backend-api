from backend.studio.historical.models import HistoricalImageCandidate
from backend.studio.historical.ranking import rank_candidates


def candidate(title: str, description: str = "") -> HistoricalImageCandidate:
    return HistoricalImageCandidate(
        provider="test",
        title=title,
        description=description,
        original_url="https://example.test/image.jpg",
        page_url="https://example.test/page",
        width=1600,
        height=900,
        mime_type="image/jpeg",
        license_name="Public domain",
    )


def test_rejects_buffalo_street_scene_for_plane_crash_plan():
    image = candidate("Main Street, Buffalo, New York, 1959")
    plan = {
        "subject_type": "event",
        "subject": "plane crash",
        "required_terms": ["plane", "crash"],
        "avoid_terms": [],
    }

    assert rank_candidates(
        [image], "1959 Buffalo plane crash", historical_plan=plan
    ) == []


def test_rejects_don_mclean_guitar_exhibit_for_person_plan():
    image = candidate(
        "Don McLean guitar on exhibit",
        "Museum display case containing a guitar.",
    )
    plan = {
        "subject_type": "person",
        "subject": "Don McLean",
        "required_terms": ["performing"],
        "avoid_terms": [],
    }

    assert rank_candidates(
        [image], "Don McLean performing", historical_plan=plan
    ) == []


def test_rejects_cliff_richard_for_elvis_presley_person_plan():
    image = candidate("Cliff Richard performing on stage")
    plan = {
        "subject_type": "person",
        "subject": "Elvis Presley",
        "required_terms": ["performing"],
        "avoid_terms": [],
    }

    assert rank_candidates(
        [image], "Elvis Presley performing", historical_plan=plan
    ) == []


def test_rejects_voltaire_print_for_don_mclean_person_plan():
    image = candidate("Portrait print of Voltaire")
    plan = {
        "subject_type": "person",
        "subject": "Don McLean",
        "required_terms": ["portrait"],
        "avoid_terms": [],
    }

    assert rank_candidates(
        [image], "Don McLean portrait", historical_plan=plan
    ) == []


def test_retains_candidate_matching_historical_plan():
    image = candidate(
        "Don McLean performing with guitar",
        "Don McLean live concert performance.",
    )
    plan = {
        "subject_type": "person",
        "subject": "Don McLean",
        "required_terms": ["guitar", "concert"],
        "avoid_terms": ["museum exhibit"],
    }

    assert rank_candidates(
        [image], "Don McLean guitar concert", historical_plan=plan
    ) == [image]


def test_without_historical_plan_preserves_existing_behavior():
    image = candidate("Main Street, Buffalo, New York, 1959")

    assert rank_candidates(
        [image], "1959 Buffalo plane crash"
    ) == [image]


def test_avoid_term_remains_a_hard_exclusion():
    image = candidate(
        "Don McLean guitar museum exhibit",
        "Don McLean concert memorabilia.",
    )
    plan = {
        "subject_type": "person",
        "subject": "Don McLean",
        "required_terms": ["guitar"],
        "avoid_terms": ["museum exhibit"],
    }

    assert rank_candidates(
        [image], "Don McLean guitar", historical_plan=plan
    ) == []
