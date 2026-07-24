from __future__ import annotations

from backend.studio.historical.models import (
    HistoricalImageCandidate,
)
from backend.studio.historical.providers.base import (
    HistoricalImageProvider,
)
from backend.studio.historical.providers.wikimedia import (
    WikimediaCommonsProvider,
)


def default_providers() -> list[
    HistoricalImageProvider
]:
    return [
        WikimediaCommonsProvider(),
    ]


def search_all_providers(
    query: str,
    *,
    limit_per_provider: int = 10,
    providers: list[
        HistoricalImageProvider
    ] | None = None,
) -> list[HistoricalImageCandidate]:
    selected_providers = (
        providers
        if providers is not None
        else default_providers()
    )

    candidates: list[
        HistoricalImageCandidate
    ] = []

    for provider in selected_providers:
        try:
            results = provider.search(
                query,
                limit=limit_per_provider,
            )

            candidates.extend(results)

        except Exception as exc:
            print(
                f"⚠ Provider "
                f"{provider.provider_name} failed: "
                f"{type(exc).__name__}: {exc}"
            )

    return candidates


def search_query_variants(
    queries: list[str],
    *,
    limit_per_provider: int = 10,
    providers: list[
        HistoricalImageProvider
    ] | None = None,
) -> list[HistoricalImageCandidate]:
    """
    Search several concise queries and merge duplicate candidates.

    Archive search engines often return nothing for long, over-specific
    phrases. Multiple focused searches produce better recall, while the
    identity-aware ranker still protects subject accuracy.
    """
    merged: dict[
        tuple[str, str],
        HistoricalImageCandidate,
    ] = {}

    for query in queries:
        cleaned = " ".join(query.split()).strip()

        if not cleaned:
            continue

        for candidate in search_all_providers(
            cleaned,
            limit_per_provider=limit_per_provider,
            providers=providers,
        ):
            key = (
                candidate.provider,
                candidate.page_url
                or candidate.original_url,
            )

            merged.setdefault(key, candidate)

    return list(merged.values())
