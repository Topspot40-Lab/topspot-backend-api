from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class HistoricalImageCandidate:
    provider: str
    title: str
    original_url: str
    page_url: str

    width: int
    height: int
    mime_type: str

    creator: str = ""
    credit: str = ""
    description: str = ""
    date: str = ""

    license_name: str = ""
    license_url: str = ""
    usage_terms: str = ""
    attribution_required: bool = False

    score: float = 0.0

    @property
    def aspect_ratio(self) -> float:
        if self.height <= 0:
            return 0.0

        return self.width / self.height

    @property
    def megapixels(self) -> float:
        return (
            self.width * self.height
        ) / 1_000_000

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
