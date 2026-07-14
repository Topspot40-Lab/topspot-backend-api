from __future__ import annotations

import math
import re

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
            r"[a-z0-9]+",
            value.casefold(),
        )
        if len(word) >= 3
    }


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


def score_candidate(
    candidate: HistoricalImageCandidate,
    query: str,
) -> float:
    if not candidate_is_usable(candidate):
        candidate.score = -1_000_000.0
        return candidate.score

    query_words = normalized_words(query)

    searchable_text = " ".join(
        [
            candidate.title,
            candidate.description,
            candidate.creator,
            candidate.date,
        ]
    )
    candidate_words = normalized_words(searchable_text)

    matching_words = query_words & candidate_words
    overlap_count = len(matching_words)

    coverage = (
        overlap_count / len(query_words)
        if query_words
        else 0.0
    )

    # Relevance dominates the score.
    relevance_score = (
        coverage * 50.0
        + overlap_count * 8.0
    )

    # Prefer useful source resolution without letting enormous files
    # overwhelm historical relevance.
    resolution_score = min(
        math.log2(
            max(candidate.megapixels, 1.0)
        ),
        6.0,
    )

    # Prefer landscape images near widescreen shape.
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
            " ".join(
                [
                    candidate.title,
                    candidate.description,
                    candidate.date,
                ]
            ),
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
        + year_adjustment,
        3,
    )

    return candidate.score


def rank_candidates(
    candidates: list[HistoricalImageCandidate],
    query: str,
) -> list[HistoricalImageCandidate]:
    for candidate in candidates:
        score_candidate(candidate, query)

    usable = [
        candidate
        for candidate in candidates
        if candidate.score > -1_000.0
    ]

    usable.sort(
        key=lambda item: item.score,
        reverse=True,
    )

    return usable
