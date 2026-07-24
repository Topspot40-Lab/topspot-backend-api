from __future__ import annotations

import argparse
import json

from backend.studio.historical.ranking import (
    rank_candidates,
)
from backend.studio.historical.search import (
    search_all_providers,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Test historical-image providers "
            "without downloading images."
        )
    )
    parser.add_argument(
        "--query",
        required=True,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
    )
    args = parser.parse_args()

    print("=" * 80)
    print("TOPSPOT STUDIO — HISTORICAL IMAGE SEARCH TEST")
    print("=" * 80)
    print(f"Query: {args.query}")
    print()

    candidates = search_all_providers(
        args.query,
        limit_per_provider=args.limit,
    )

    ranked = rank_candidates(
        candidates,
        args.query,
    )

    print(
        f"Candidates returned: {len(candidates)}"
    )
    print(
        f"Usable candidates:   {len(ranked)}"
    )
    print()

    for index, candidate in enumerate(
        ranked,
        start=1,
    ):
        print("-" * 80)
        print(
            f"{index}. {candidate.title}"
        )
        print(
            f"   Provider: {candidate.provider}"
        )
        print(
            f"   Size:     "
            f"{candidate.width} × "
            f"{candidate.height}"
        )
        print(
            f"   MIME:     "
            f"{candidate.mime_type}"
        )
        print(
            f"   Creator:  "
            f"{candidate.creator or 'Not supplied'}"
        )
        print(
            f"   Score:    "
            f"{candidate.score}"
        )
        print(
            f"   License:  "
            f"{candidate.license_name or 'Not supplied'}"
        )
        print(
            f"   Terms:    "
            f"{candidate.usage_terms or 'Not supplied'}"
        )
        print(
            f"   Page:     "
            f"{candidate.page_url}"
        )

    print()
    print("JSON preview:")
    print(
        json.dumps(
            [
                candidate.to_dict()
                for candidate in ranked[:2]
            ],
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
