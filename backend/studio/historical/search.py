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
