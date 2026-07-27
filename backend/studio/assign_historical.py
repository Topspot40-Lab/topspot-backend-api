from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.studio.production import Production
from backend.studio.studio_config import ASSETS_DIR
from backend.studio.historical_assets import (
    historical_directories_for_production,
)


SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"JSON file not found: {path}"
        )

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON file: {path}"
        ) from exc


def save_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

def find_shot(
    storyboard: dict[str, Any],
    shot_number: int,
) -> dict[str, Any]:
    for scene in storyboard.get("scenes", []):
        for shot in scene.get(
            "visual_shots",
            [],
        ):
            if int(
                shot["shot_number"]
            ) == shot_number:
                return shot

    raise LookupError(
        f"Shot {shot_number} was not found."
    )


def find_photo(
    *,
    production: Production,
    photo_id: str,
) -> Path:
    photos_dir = (
        historical_directories_for_production(
            production
        ).photos
    )

    if not photos_dir.exists():
        raise FileNotFoundError(
            f"Historical photo directory "
            f"not found: {photos_dir}"
        )

    normalized_id = photo_id.zfill(3)

    matches = sorted(
        path
        for path in photos_dir.iterdir()
        if path.is_file()
        and path.suffix.casefold()
        in SUPPORTED_EXTENSIONS
        and path.name.startswith(
            f"{normalized_id}-"
        )
    )

    if not matches:
        raise FileNotFoundError(
            f"No curated photo found for "
            f"library ID {normalized_id}."
        )

    if len(matches) > 1:
        names = ", ".join(
            path.name
            for path in matches
        )
        raise RuntimeError(
            f"Multiple curated photos found "
            f"for library ID {normalized_id}: "
            f"{names}"
        )

    return matches[0]


def relative_asset_path(
    photo_path: Path,
) -> str:
    return photo_path.relative_to(
        ASSETS_DIR.parent
    ).as_posix()


def run(
    *,
    slug: str,
    shot_number: int,
    photo_id: str,
) -> None:
    production = Production(slug)

    storyboard_path = (
        production.production_root
        / "storyboard.json"
    )

    storyboard = load_json(
        storyboard_path
    )

    shot = find_shot(
        storyboard,
        shot_number,
    )

    photo_path = find_photo(
        production=production,
        photo_id=photo_id,
    )

    old_source = str(
        shot.get("source") or "unknown"
    )

    old_asset = shot.get(
        "historical_asset"
    )

    approved_image = relative_asset_path(
        photo_path
    )

    shot["source"] = "historical"
    shot["historical_asset"] = {
        "provider": "curated_library",
        "approved_image": approved_image,
        "library_filename": photo_path.name,
        "library_id": photo_id.zfill(3),
        "curated": True,
    }
    shot["review_notes"] = (
        f"Curated historical photo "
        f"{photo_path.name} assigned manually."
    )

    backup_path = storyboard_path.with_suffix(
        ".before-manual-assignments.json"
    )

    if not backup_path.exists():
        save_json(
            backup_path,
            storyboard,
        )

    save_json(
        storyboard_path,
        storyboard,
    )

    print("=" * 72)
    print(
        "TOPSPOT STUDIO — ASSIGN HISTORICAL PHOTO"
    )
    print("=" * 72)
    print(f"Production: {storyboard.get('title')}")
    print(f"Slug:       {slug}")
    print(f"Shot:       {shot_number:03d}")
    print()
    print(f"Previous source: {old_source}")

    if isinstance(old_asset, dict):
        old_image = str(
            old_asset.get(
                "approved_image"
            )
            or "not supplied"
        )
        print(
            f"Previous image:  {old_image}"
        )

    print(f"New photo:       {photo_path.name}")
    print(f"Storyboard path: {storyboard_path}")
    print()
    print("✅ Curated historical photo assigned")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Assign a curated historical photo "
            "to a storyboard shot."
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
        "--photo",
        required=True,
        help=(
            "Curated photo ID, such as 001."
        ),
    )

    args = parser.parse_args()

    run(
        slug=args.slug,
        shot_number=args.shot,
        photo_id=args.photo,
    )


if __name__ == "__main__":
    main()
