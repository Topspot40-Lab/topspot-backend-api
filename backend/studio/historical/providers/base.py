from __future__ import annotations

from abc import ABC, abstractmethod

from backend.studio.historical.models import (
    HistoricalImageCandidate,
)


class HistoricalImageProvider(ABC):
    provider_name: str

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[HistoricalImageCandidate]:
        """Return historical-image candidates for one search phrase."""
        raise NotImplementedError
