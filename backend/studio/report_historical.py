from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.studio.production import Production
from backend.studio.studio_config import ASSETS_DIR


SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON file: {path}"
        ) from exc


def library_photos(
    *,
    slug: str,
) -> list[Path]:
    photos_dir = (
        ASSETS_DIR
        / "historical"
        / slug
        / "photos"
    )

    if not photos_dir.exists():
        return []

    return sorted(
        path
        for path in photos_dir.iterdir()
        if path.is_file()
        and path.suffix.casefold()
        in SUPPORTED_EXTENSIONS
    )


def storyboard_assignments(
    storyboard: dict[str, Any],
) -> dict[str, list[int]]:
    assigned: dict[str, list[int]] = defaultdict(
        list
    )

    for scene in storyboard.get("scenes", []):
        for shot in scene.get(
            "visual_shots",
            [],
        ):
            historical_asset = shot.get(
                "historical_asset"
            )

            if not isinstance(
                historical_asset,
                dict,
            ):
                continue

            approved_image = str(
                historical_asset.get(
                    "approved_image"
                )
                or ""
            ).strip()

            if not approved_image:
                continue

            filename = Path(
                approved_image
            ).name

            assigned[filename].append(
                int(shot["shot_number"])
            )

    return dict(assigned)


def photo_id(path: Path) -> str:
    stem = path.stem

    if len(stem) >= 3 and stem[:3].isdigit():
        return stem[:3]

    return "---"


def run(
    *,
    slug: str,
) -> None:
    production = Production(slug)

    storyboard_path = (
        production.production_root
        / "storyboard.json"
    )

    storyboard = load_json(
        storyboard_path
    )

    photos = library_photos(
        slug=slug
    )

    assignments = storyboard_assignments(
        storyboard
    )

    assigned_count = sum(
        1
        for photo in photos
        if photo.name in assignments
    )

    print("=" * 72)
    print(
        "TOPSPOT STUDIO — HISTORICAL LIBRARY REPORT"
    )
    print("=" * 72)
    print(
        f"Production: {storyboard.get('title')}"
    )
    print(f"Slug:       {slug}")
    print()
    print(f"Library photos: {len(photos)}")
    print(f"Assigned:       {assigned_count}")
    print(
        f"Unassigned:     "
        f"{len(photos) - assigned_count}"
    )
    print()

    if not photos:
        print(
            "No curated photos found in:"
        )
        print(
            ASSETS_DIR
            / "historical"
            / slug
            / "photos"
        )
        return

    for photo in photos:
        shots = assignments.get(
            photo.name,
            [],
        )

        print("-" * 72)
        print(
            f"{photo_id(photo)}  "
            f"{photo.name}"
        )

        if shots:
            formatted = ", ".join(
                f"{shot:03d}"
                for shot in shots
            )
            print(
                f"Used in shot(s): {formatted}"
            )
        else:
            print("Used in shot(s): none")

    print()
    print("=" * 72)
    print("UNASSIGNED PHOTOS")
    print("=" * 72)

    unassigned = [
        photo
        for photo in photos
        if photo.name not in assignments
    ]

    if not unassigned:
        print("All curated photos are assigned.")
    else:
        for photo in unassigned:
            print(
                f"{photo_id(photo)}  "
                f"{photo.name}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Report curated historical photos "
            "and storyboard assignments."
        )
    )

    parser.add_argument(
        "--slug",
        required=True,
    )

    args = parser.parse_args()

    run(
        slug=args.slug,
    )


if __name__ == "__main__":
    main()
