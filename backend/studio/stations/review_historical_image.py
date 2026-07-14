from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.studio.historical.downloader import (
    download_candidate,
)
from backend.studio.historical.ranking import (
    rank_candidates,
)
from backend.studio.historical.search import (
    search_all_providers,
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
        f"Search:     {query}"
    )
    print()

    candidates = search_all_providers(
        query,
        limit_per_provider=args.limit,
    )

    ranked = rank_candidates(
        candidates,
        query,
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
