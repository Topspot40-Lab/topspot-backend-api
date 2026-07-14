from __future__ import annotations

import html
import re
from typing import Any

import requests

from backend.studio.historical.models import (
    HistoricalImageCandidate,
)
from backend.studio.historical.providers.base import (
    HistoricalImageProvider,
)


COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"

USER_AGENT = (
    "TopSpot40-Studio/1.0 "
    "(historical documentary image research; "
    "contact: gwsteele77@gmail.com)"
)


def clean_html(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)

    return " ".join(text.split()).strip()


def metadata_value(
    metadata: dict[str, Any],
    key: str,
) -> str:
    item = metadata.get(key)

    if not isinstance(item, dict):
        return ""

    return clean_html(item.get("value"))


def parse_boolean(value: str) -> bool:
    return value.strip().casefold() in {
        "1",
        "true",
        "yes",
        "required",
    }


class WikimediaCommonsProvider(HistoricalImageProvider):
    provider_name = "wikimedia_commons"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            }
        )

    def _search_titles(
        self,
        query: str,
        *,
        limit: int,
    ) -> list[str]:
        response = self.session.get(
            COMMONS_API_URL,
            params={
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "list": "search",
                "srsearch": query,
                "srnamespace": 6,
                "srlimit": limit,
            },
            timeout=(10, 45),
        )
        response.raise_for_status()

        payload = response.json()

        return [
            str(item["title"])
            for item in (
                payload
                .get("query", {})
                .get("search", [])
            )
            if str(
                item.get("title") or ""
            ).startswith("File:")
        ]

    def _load_file_information(
        self,
        titles: list[str],
    ) -> list[HistoricalImageCandidate]:
        if not titles:
            return []

        response = self.session.get(
            COMMONS_API_URL,
            params={
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "prop": "imageinfo",
                "titles": "|".join(titles),
                "iiprop": "url|size|mime|extmetadata",
                "iiextmetadatafilter": (
                    "Artist|Credit|LicenseShortName|"
                    "LicenseUrl|UsageTerms|"
                    "AttributionRequired|"
                    "ImageDescription|DateTimeOriginal"
                ),
                "iiextmetadatalanguage": "en",
            },
            timeout=(10, 60),
        )
        response.raise_for_status()

        payload = response.json()
        candidates: list[
            HistoricalImageCandidate
        ] = []

        pages = (
            payload
            .get("query", {})
            .get("pages", [])
        )

        for page in pages:
            image_information = (
                page.get("imageinfo") or []
            )

            if not image_information:
                continue

            information = image_information[0]
            metadata = (
                information.get("extmetadata")
                or {}
            )

            original_url = str(
                information.get("url") or ""
            )

            if not original_url:
                continue

            attribution_value = metadata_value(
                metadata,
                "AttributionRequired",
            )

            candidates.append(
                HistoricalImageCandidate(
                    provider=self.provider_name,
                    title=str(
                        page.get("title") or ""
                    ),
                    original_url=original_url,
                    page_url=str(
                        information.get(
                            "descriptionurl"
                        )
                        or ""
                    ),
                    width=int(
                        information.get("width")
                        or 0
                    ),
                    height=int(
                        information.get("height")
                        or 0
                    ),
                    mime_type=str(
                        information.get("mime")
                        or ""
                    ),
                    creator=(
                        metadata_value(
                            metadata,
                            "Artist",
                        )
                        or metadata_value(
                            metadata,
                            "Credit",
                        )
                    ),
                    credit=metadata_value(
                        metadata,
                        "Credit",
                    ),
                    description=metadata_value(
                        metadata,
                        "ImageDescription",
                    ),
                    date=metadata_value(
                        metadata,
                        "DateTimeOriginal",
                    ),
                    license_name=metadata_value(
                        metadata,
                        "LicenseShortName",
                    ),
                    license_url=metadata_value(
                        metadata,
                        "LicenseUrl",
                    ),
                    usage_terms=metadata_value(
                        metadata,
                        "UsageTerms",
                    ),
                    attribution_required=(
                        parse_boolean(
                            attribution_value
                        )
                    ),
                )
            )

        return candidates

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[HistoricalImageCandidate]:
        cleaned_query = query.strip()

        if not cleaned_query:
            return []

        titles = self._search_titles(
            cleaned_query,
            limit=limit,
        )

        return self._load_file_information(
            titles
        )
