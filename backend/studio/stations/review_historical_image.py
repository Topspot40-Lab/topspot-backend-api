from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.studio.historical.downloader import (
    download_candidate,
)
from backend.studio.historical.identity import (
    build_search_queries,
    load_or_build_identity,
    strengthen_query,
)
from backend.studio.historical.ranking import (
    rank_candidates,
)
from backend.studio.historical.search import (
    search_query_variants,
)
from backend.studio.production import Production


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"JSON file not found: {path}"
        )

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def find_shot(
    storyboard: dict[str, Any],
    shot_number: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    for scene in storyboard.get("scenes", []):
        for shot in scene.get(
            "visual_shots",
            [],
        ):
            if int(
                shot["shot_number"]
            ) == shot_number:
                return scene, shot

    raise LookupError(
        f"Shot {shot_number} was not found."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download the highest-ranked historical "
            "candidate into a review folder."
        )
    )
    parser.add_argument(
        "--slug",
        required=True,
    )
    parser.add_argument(
        "--shot",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--force",
        action="store_true",
    )
    args = parser.parse_args()

    production = Production(args.slug)

    identity = load_or_build_identity(
        production
    )

    storyboard_path = (
        production.production_root
        / "storyboard.json"
    )
    storyboard = load_json(storyboard_path)

    scene, shot = find_shot(
        storyboard,
        args.shot,
    )

    query = str(
        shot.get("historical_search")
        or ""
    ).strip()

    if not query:
        raise SystemExit(
            f"Shot {args.shot} has no "
            "historical_search value."
        )

    enhanced_query = strengthen_query(
        query,
        identity,
    )

    destination_directory = (
        production.work_root
        / "historical_candidates"
        / f"{args.shot:03d}"
    )

    metadata_path = (
        destination_directory
        / "candidate.json"
    )

    if metadata_path.exists() and not args.force:
        raise SystemExit(
            f"Candidate already exists: "
            f"{metadata_path}\n"
            "Use --force to replace it."
        )

    print("=" * 80)
    print(
        "TOPSPOT STUDIO — HISTORICAL IMAGE REVIEW"
    )
    print("=" * 80)
    print(
        f"Production: {storyboard.get('title')}"
    )
    print(
        f"Scene:      "
        f"{scene.get('scene_number')}"
    )
    print(
        f"Shot:       {args.shot:03d}"
    )
    print(
        f"Identity:   {identity.canonical_name}"
    )

    if identity.aliases:
        print(
            "Aliases:    "
            + ", ".join(identity.aliases)
        )

    if identity.identity_terms:
        print(
            "Anchors:    "
            + ", ".join(identity.identity_terms)
        )

    print(
        f"Original:   {query}"
    )
    print(
        f"Search:     {enhanced_query}"
    )
    print()

    historical_plan = shot.get(
        "historical_plan",
        {},
    )

    if not isinstance(historical_plan, dict):
        historical_plan = {}

    planned_queries = [
        str(value).strip()
        for value in historical_plan.get(
            "search_queries",
            [],
        )
        if str(value).strip()
    ]

    fallback_queries = build_search_queries(
        query,
        identity,
    )

    search_queries: list[str] = []
    seen_queries: set[str] = set()

    for search_query in [
        *planned_queries,
        *fallback_queries,
    ]:
        key = search_query.casefold()

        if key not in seen_queries:
            search_queries.append(search_query)
            seen_queries.add(key)

    print("Queries:")
    for search_query in search_queries:
        print(f"  - {search_query}")
    print()

    candidates = search_query_variants(
        search_queries,
        limit_per_provider=args.limit,
    )

    identity_names = [
        identity.canonical_name,
        *identity.aliases,
    ]

    normalized_original = query.casefold()

    require_exact_identity = any(
        name.casefold() in normalized_original
        for name in identity_names
        if name.strip()
    )

    ranked = rank_candidates(
        candidates,
        enhanced_query,
        identity=identity,
        require_exact_identity=(
            require_exact_identity
        ),
        historical_plan=historical_plan,
    )

    print(
        f"Raw candidates:    {len(candidates)}"
    )
    print(
        f"Usable candidates: {len(ranked)}"
    )

    if not ranked:
        print()
        print(
            "No acceptable historical image "
            "was found."
        )
        return

    winner = ranked[0]

    image_path, saved_metadata_path = (
        download_candidate(
            winner,
            destination_directory,
        )
    )

    print()
    print("Selected candidate:")
    print(
        f"  Title:   {winner.title}"
    )
    print(
        f"  Creator: "
        f"{winner.creator or 'Not supplied'}"
    )
    print(
        f"  License: "
        f"{winner.license_name}"
    )
    print(
        f"  Size:    "
        f"{winner.width} × {winner.height}"
    )
    print(
        f"  Score:   {winner.score}"
    )
    print(
        "  Identity confidence: "
        f"{winner.identity_confidence:.3f}"
    )
    print()
    print(
        f"Image saved:    {image_path}"
    )
    print(
        f"Metadata saved: "
        f"{saved_metadata_path}"
    )
    print()
    print(
        "Review only: the finished AI image "
        "was not changed."
    )


if __name__ == "__main__":
    main()
