from __future__ import annotations

import math
import re
from typing import Any

from backend.studio.historical.identity import (
    HistoricalIdentity,
)
from backend.studio.historical.models import (
    HistoricalImageCandidate,
)


ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
}

ALLOWED_LICENSE_MARKERS = {
    "public domain",
    "cc0",
    "cc by",
    "cc-by",
}

MIN_WIDTH = 800
MIN_HEIGHT = 500


def normalized_words(value: str) -> set[str]:
    return {
        word
        for word in re.findall(
            r"[a-z0-9áéíóúüñ]+",
            value.casefold(),
        )
        if len(word) >= 3
    }


def candidate_searchable_text(
    candidate: HistoricalImageCandidate,
) -> str:
    return " ".join(
        [
            candidate.title,
            candidate.description,
            candidate.creator,
            candidate.date,
            candidate.page_url,
        ]
    )


def license_is_allowed(
    candidate: HistoricalImageCandidate,
) -> bool:
    combined = " ".join(
        [
            candidate.license_name,
            candidate.usage_terms,
            candidate.license_url,
        ]
    ).casefold()

    return any(
        marker in combined
        for marker in ALLOWED_LICENSE_MARKERS
    )


def candidate_is_usable(
    candidate: HistoricalImageCandidate,
) -> bool:
    if candidate.mime_type not in ALLOWED_MIME_TYPES:
        return False

    if candidate.width < MIN_WIDTH:
        return False

    if candidate.height < MIN_HEIGHT:
        return False

    if not candidate.original_url:
        return False

    if not license_is_allowed(candidate):
        return False

    return True


def normalized_phrase(value: str) -> str:
    return " ".join(
        re.findall(
            r"[a-z0-9áéíóúüñ]+",
            value.casefold(),
        )
    )


def candidate_has_exact_identity(
    candidate: HistoricalImageCandidate,
    identity: HistoricalIdentity,
) -> bool:
    searchable = normalized_phrase(
        candidate_searchable_text(candidate)
    )

    accepted_phrases = [
        identity.canonical_name,
        *identity.aliases,
    ]

    return any(
        normalized_phrase(phrase) in searchable
        for phrase in accepted_phrases
        if normalized_phrase(phrase)
    )


def identity_adjustment(
    candidate: HistoricalImageCandidate,
    identity: HistoricalIdentity | None,
) -> float:
    if identity is None:
        candidate.identity_confidence = 0.0
        return 0.0

    candidate_words = normalized_words(
        candidate_searchable_text(candidate)
    )
    name_words = normalized_words(
        " ".join(
            [
                identity.canonical_name,
                *identity.aliases,
            ]
        )
    )

    identity_term_words = normalized_words(
        " ".join(identity.identity_terms)
    )
    negative_words = normalized_words(
        " ".join(identity.negative_terms)
    )

    name_matches = name_words & candidate_words
    term_matches = (
        identity_term_words & candidate_words
    )
    negative_matches = (
        negative_words & candidate_words
    )

    name_coverage = (
        len(name_matches) / len(name_words)
        if name_words
        else 0.0
    )

    term_coverage = (
        len(term_matches) / len(identity_term_words)
        if identity_term_words
        else 0.0
    )

    if identity_term_words:
        confidence = (
            name_coverage * 0.65
            + term_coverage * 0.35
        )
    else:
        confidence = name_coverage

    candidate.identity_confidence = round(
        min(max(confidence, 0.0), 1.0),
        3,
    )

    adjustment = 0.0

    # The canonical person or subject should dominate.
    adjustment += name_coverage * 80.0
    adjustment += len(name_matches) * 10.0

    # Nationality, profession, genre, or known role help distinguish
    # ambiguous names such as Luis Miguel.
    adjustment += term_coverage * 45.0
    adjustment += len(term_matches) * 7.0

    if name_words and not name_matches:
        adjustment -= 70.0

    if (
        identity_term_words
        and not term_matches
    ):
        adjustment -= 25.0

    if negative_matches:
        adjustment -= (
            75.0 * len(negative_matches)
        )

    return adjustment


LIFE_STAGE_EVIDENCE = {
    "childhood": {
        "child",
        "childhood",
        "young",
        "boy",
        "girl",
        "juvenile",
        "early years",
    },
    "teenage": {
        "teen",
        "teenage",
        "teenager",
        "adolescent",
        "young",
    },
    "early career": {
        "early career",
        "debut",
        "young",
        "early years",
        "first performance",
        "first recording",
    },
    "late career": {
        "late career",
        "later years",
        "final years",
        "retirement",
    },
}


def has_life_stage_evidence(
    searchable: str,
    era: str,
) -> bool:
    normalized_era = normalized_phrase(era)

    evidence_terms = LIFE_STAGE_EVIDENCE.get(
        normalized_era
    )

    if not evidence_terms:
        return True

    return any(
        normalized_phrase(term) in searchable
        for term in evidence_terms
    )


def historical_plan_adjustment(
    candidate: HistoricalImageCandidate,
    historical_plan: dict[str, Any] | None,
) -> float:
    """
    Reward evidence that the candidate fits the requested scene and
    reject explicit mismatches.

    required_terms are soft evidence because archive metadata can be
    incomplete. avoid_terms are treated as hard exclusions.
    """
    if not historical_plan:
        return 0.0

    searchable = normalized_phrase(
        candidate_searchable_text(candidate)
    )
    candidate_words = normalized_words(
        searchable
    )

    required_terms = [
        str(value).strip()
        for value in historical_plan.get(
            "required_terms",
            [],
        )
        if str(value).strip()
    ]

    avoid_terms = [
        str(value).strip()
        for value in historical_plan.get(
            "avoid_terms",
            [],
        )
        if str(value).strip()
    ]

    era = str(
        historical_plan.get("era", "")
    ).strip()

    # A life-stage request must have explicit metadata evidence.
    # When an archive cannot establish the requested stage, reject the
    # candidate and preserve the AI fallback instead of guessing.
    if (
        era
        and not has_life_stage_evidence(
            searchable,
            era,
        )
    ):
        return -1_000_000.0

    for avoid_term in avoid_terms:
        normalized_avoid = normalized_phrase(
            avoid_term
        )

        if normalized_avoid and normalized_avoid in searchable:
            return -1_000_000.0

    adjustment = 0.0

    for required_term in required_terms:
        normalized_required = normalized_phrase(
            required_term
        )

        if (
            normalized_required
            and normalized_required in searchable
        ):
            adjustment += 24.0
            continue

        required_words = normalized_words(
            required_term
        )

        if required_words:
            overlap = (
                required_words
                & candidate_words
            )

            adjustment += (
                len(overlap)
                / len(required_words)
            ) * 12.0

    if era:
        normalized_era = normalized_phrase(era)

        if normalized_era in searchable:
            adjustment += 20.0

        era_words = normalized_words(era)
        era_overlap = era_words & candidate_words

        if era_words:
            adjustment += (
                len(era_overlap)
                / len(era_words)
            ) * 10.0

    return adjustment


def score_candidate(
    candidate: HistoricalImageCandidate,
    query: str,
    *,
    identity: HistoricalIdentity | None = None,
    require_exact_identity: bool = False,
    historical_plan: dict[str, Any] | None = None,
) -> float:
    if not candidate_is_usable(candidate):
        candidate.score = -1_000_000.0
        candidate.identity_confidence = 0.0
        return candidate.score

    if (
        require_exact_identity
        and identity is not None
        and not candidate_has_exact_identity(
            candidate,
            identity,
        )
    ):
        candidate.score = -1_000_000.0
        candidate.identity_confidence = 0.0
        return candidate.score

    query_words = normalized_words(query)
    searchable_text = candidate_searchable_text(
        candidate
    )
    candidate_words = normalized_words(
        searchable_text
    )

    matching_words = query_words & candidate_words
    overlap_count = len(matching_words)

    coverage = (
        overlap_count / len(query_words)
        if query_words
        else 0.0
    )

    relevance_score = (
        coverage * 50.0
        + overlap_count * 8.0
    )

    resolution_score = min(
        math.log2(
            max(candidate.megapixels, 1.0)
        ),
        6.0,
    )

    aspect_ratio = candidate.aspect_ratio
    aspect_distance = abs(
        aspect_ratio - (16 / 9)
    )
    aspect_score = max(
        0.0,
        5.0 - aspect_distance * 3.0,
    )

    landscape_bonus = (
        4.0
        if candidate.width > candidate.height
        else 0.0
    )

    public_domain_bonus = (
        5.0
        if "public domain"
        in (
            candidate.license_name
            + " "
            + candidate.usage_terms
        ).casefold()
        else 0.0
    )

    query_years = {
        int(value)
        for value in re.findall(
            r"\b(?:18|19|20)\d{2}\b",
            query,
        )
    }

    candidate_years = {
        int(value)
        for value in re.findall(
            r"\b(?:18|19|20)\d{2}\b",
            searchable_text,
        )
    }

    year_adjustment = 0.0

    if query_years and candidate_years:
        closest_year_difference = min(
            abs(query_year - candidate_year)
            for query_year in query_years
            for candidate_year in candidate_years
        )

        if closest_year_difference == 0:
            year_adjustment = 25.0
        elif closest_year_difference <= 2:
            year_adjustment = 10.0
        elif closest_year_difference <= 5:
            year_adjustment = -15.0
        else:
            year_adjustment = -60.0

    candidate.score = round(
        relevance_score
        + resolution_score
        + aspect_score
        + landscape_bonus
        + public_domain_bonus
        + year_adjustment
        + identity_adjustment(
            candidate,
            identity,
        )
        + historical_plan_adjustment(
            candidate,
            historical_plan,
        ),
        3,
    )

    return candidate.score


def rank_candidates(
    candidates: list[HistoricalImageCandidate],
    query: str,
    *,
    identity: HistoricalIdentity | None = None,
    require_exact_identity: bool = False,
    historical_plan: dict[str, Any] | None = None,
) -> list[HistoricalImageCandidate]:
    for candidate in candidates:
        score_candidate(
            candidate,
            query,
            identity=identity,
            require_exact_identity=(
                require_exact_identity
            ),
            historical_plan=historical_plan,
        )

    usable = [
        candidate
        for candidate in candidates
        if candidate.score > -1_000.0
    ]

    usable.sort(
        key=lambda item: (
            item.score,
            item.identity_confidence,
        ),
        reverse=True,
    )

    return usable
