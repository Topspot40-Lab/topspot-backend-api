from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.studio.historical_assets import (
    historical_directories_for_production,
)
from backend.studio.production import Production

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
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON file: {path}") from exc


def save_json_atomic(
        path: Path,
        payload: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary_path.replace(path)


def safe_filename_part(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"^file:", "", value)
    value = Path(value).stem
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")

    return value[:80] or "historical_image"


def find_candidate_image(
        candidate_directory: Path,
        metadata: dict[str, Any],
) -> Path:
    downloaded_file = str(
        metadata.get("downloaded_file") or ""
    ).strip()

    if downloaded_file:
        candidate = (
                candidate_directory
                / downloaded_file
        )

        if candidate.exists():
            return candidate

    matches = [
        path
        for path in candidate_directory.iterdir()
        if path.is_file()
           and path.suffix.lower()
           in SUPPORTED_EXTENSIONS
    ]

    if len(matches) == 1:
        return matches[0]

    if not matches:
        raise FileNotFoundError(
            f"No candidate image found in "
            f"{candidate_directory}"
        )

    raise RuntimeError(
        f"Multiple candidate images found in "
        f"{candidate_directory}: "
        f"{[path.name for path in matches]}"
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


def remove_previous_approved_files(
        *,
        historical_directory: Path,
        shot_number: int,
        keep: Path | None = None,
) -> None:
    prefixes = (
        f"{shot_number:03d}_",
        f"{shot_number:02d}_",
    )

    for path in historical_directory.iterdir():
        if not path.is_file():
            continue

        if not path.name.startswith(prefixes):
            continue

        if path.suffix.lower() not in (
                SUPPORTED_EXTENSIONS | {".json"}
        ):
            continue

        if keep is not None and path == keep:
            continue

        path.unlink()
        print(
            f"Removed previous approved asset: "
            f"{path}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Approve a reviewed historical-image candidate "
            "for a TopSpot Studio shot."
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
        "--force",
        action="store_true",
        help=(
            "Replace an existing approved historical "
            "asset for this shot."
        ),
    )
    args = parser.parse_args()

    production = Production(args.slug)

    storyboard_path = (
            production.production_root
            / "storyboard.json"
    )
    storyboard = load_json(storyboard_path)

    shot = find_shot(
        storyboard,
        args.shot,
    )

    candidate_directory = (
            production.work_root
            / "historical_candidates"
            / f"{args.shot:03d}"
    )

    candidate_metadata_path = (
            candidate_directory
            / "candidate.json"
    )

    metadata = load_json(
        candidate_metadata_path
    )

    candidate_image = find_candidate_image(
        candidate_directory,
        metadata,
    )

    historical_directories = (
        historical_directories_for_production(
            production
        )
    )
    historical_directories.ensure()

    photos_directory = historical_directories.photos
    metadata_directory = historical_directories.metadata

    title = str(
        metadata.get("title")
        or "historical_image"
    )

    safe_title = safe_filename_part(title)

    approved_image_name = (
        f"{args.shot:03d}_{safe_title}"
        f"{candidate_image.suffix.lower()}"
    )
    approved_image_path = (
            photos_directory
            / approved_image_name
    )

    approved_metadata_path = (
            metadata_directory
            / f"{args.shot:03d}_{safe_title}.json"
    )

    prefixes = (
        f"{args.shot:03d}_",
        f"{args.shot:02d}_",
    )

    existing_assets = [
        path
        for directory in (
            photos_directory,
            metadata_directory,
        )
        for path in directory.iterdir()
        if path.is_file()
           and path.name.startswith(prefixes)
    ]

    if existing_assets and not args.force:
        raise SystemExit(
            "An approved historical asset already "
            f"exists for shot {args.shot}:\n"
            + "\n".join(
                str(path)
                for path in existing_assets
            )
            + "\nUse --force to replace it."
        )

    if args.force:
        for directory in (
            photos_directory,
            metadata_directory,
        ):
            remove_previous_approved_files(
                historical_directory=directory,
                shot_number=args.shot,
            )

    shutil.copy2(
        candidate_image,
        approved_image_path,
    )

    approved_at = datetime.now(
        UTC
    ).isoformat()

    approved_metadata = dict(metadata)
    approved_metadata.update(
        {
            "approved": True,
            "approved_at": approved_at,
            "production_slug": args.slug,
            "shot_number": args.shot,
            "approved_image": (
                approved_image_path.name
            ),
            "candidate_source_file": str(
                candidate_image
            ),
        }
    )

    save_json_atomic(
        approved_metadata_path,
        approved_metadata,
    )

    shot["source"] = str(
        metadata.get("provider")
        or "historical"
    )

    shot["historical_asset"] = {
        "provider": metadata.get(
            "provider",
            "",
        ),
        "title": metadata.get(
            "title",
            "",
        ),
        "creator": metadata.get(
            "creator",
            "",
        ),
        "credit": metadata.get(
            "credit",
            "",
        ),
        "license": metadata.get(
            "license_name",
            "",
        ),
        "license_url": metadata.get(
            "license_url",
            "",
        ),
        "usage_terms": metadata.get(
            "usage_terms",
            "",
        ),
        "page_url": metadata.get(
            "page_url",
            "",
        ),
        "original_url": metadata.get(
            "original_url",
            "",
        ),
        "approved_image": str(
            approved_image_path.relative_to(
                Path("backend/studio")
            )
        ).replace("\\", "/"),
        "approved_at": approved_at,
    }

    save_json_atomic(
        storyboard_path,
        storyboard,
    )

    print("=" * 80)
    print(
        "TOPSPOT STUDIO — HISTORICAL IMAGE APPROVAL"
    )
    print("=" * 80)
    print(f"Production: {args.slug}")
    print(f"Shot:       {args.shot:03d}")
    print()
    print(
        f"Candidate:  {candidate_image}"
    )
    print(
        f"Approved:   {approved_image_path}"
    )
    print(
        f"Metadata:   {approved_metadata_path}"
    )
    print()
    print(
        "Storyboard updated:"
    )
    print(
        f"  source = {shot['source']!r}"
    )
    print(
        "  historical_asset = populated"
    )
    print()
    print(
        "✅ Historical image approved"
    )
    print(
        "The renderer will now prefer this image "
        "for the selected shot."
    )


if __name__ == "__main__":
    main()
