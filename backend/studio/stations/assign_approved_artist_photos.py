from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import re

from backend.studio.assign_historical import (
    relative_asset_path,
)
from backend.studio.historical_assets import (
    historical_directories_for_production,
)
from backend.studio.production import Production


POSITIVE_TERMS = {
    "candid",
    "concert",
    "live",
    "performance",
    "performing",
    "portrait",
    "singing",
    "stage",
}

UNSAFE_TERMS = {
    "15-year-old",
    "baby",
    "child",
    "childhood",
    "daughter",
    "father",
    "grammy",
    "hospital",
    "little girl",
    "mother",
    "school",
    "son",
    "surgery",
    "throat",
    "toddler",
    "trophy",
    "vocal cord",
    "young",
}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"JSON file not found: {path}"
        )

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def save_json_atomic(
    path: Path,
    payload: dict[str, Any],
) -> None:
    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def all_visual_shots(
    storyboard: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        shot
        for scene in storyboard.get("scenes", [])
        for shot in scene.get("visual_shots", [])
    ]


def normalized(value: Any) -> str:
    return " ".join(
        str(value or "").casefold().split()
    )

def contains_term(
    text: str,
    term: str,
) -> bool:
    pattern = (
        r"(?<!\w)"
        + re.escape(term)
        + r"(?!\w)"
    )

    return bool(
        re.search(pattern, text)
    )


def is_safe_artist_shot(
    shot: dict[str, Any],
    artist_name: str,
) -> bool:
    plan = shot.get("historical_plan")

    if not isinstance(plan, dict):
        plan = {}

    subject = normalized(
        plan.get("subject")
    )

    searchable_text = normalized(
        " ".join(
            [
                str(
                    shot.get("visual_intent")
                    or ""
                ),
                str(
                    shot.get("historical_search")
                    or ""
                ),
                str(
                    shot.get("prompt")
                    or ""
                ),
            ]
        )
    )

    artist = normalized(artist_name)

    identity_match = (
        artist in subject
        or artist in searchable_text
    )

    if not identity_match:
        return False

    if any(
            contains_term(
                searchable_text,
                term,
            )
            for term in UNSAFE_TERMS
    ):
        return False

    return any(
        contains_term(
            searchable_text,
            term,
        )
        for term in POSITIVE_TERMS
    )


def approved_metadata(
    metadata_dir: Path,
) -> list[dict[str, Any]]:
    approved: list[dict[str, Any]] = []

    if not metadata_dir.exists():
        return approved

    for path in sorted(
        metadata_dir.glob("*.json")
    ):
        try:
            payload = load_json(path)
        except (
            OSError,
            json.JSONDecodeError,
        ):
            continue

        if not payload.get("approved"):
            continue

        if not str(
            payload.get("storage_bucket")
            or ""
        ).strip():
            continue

        if not str(
            payload.get("storage_key")
            or ""
        ).strip():
            continue

        payload["_metadata_path"] = str(path)
        approved.append(payload)

    return approved


def download_photo(
    *,
    metadata: dict[str, Any],
    destination: Path,
) -> None:
    if (
        destination.exists()
        and destination.stat().st_size > 0
    ):
        return

    from backend.services.supabase_client import (
        supabase,
    )

    bucket = str(
        metadata["storage_bucket"]
    )
    key = str(
        metadata["storage_key"]
    )

    content = (
        supabase.storage
        .from_(bucket)
        .download(key)
    )

    if not content:
        raise RuntimeError(
            f"Empty storage download: "
            f"{bucket}/{key}"
        )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    destination.write_bytes(content)


def build_historical_asset(
    *,
    metadata: dict[str, Any],
    photo_path: Path,
) -> dict[str, Any]:
    return {
        "provider": metadata.get(
            "provider",
            "curated_artist_photo",
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
        "page_url": metadata.get(
            "page_url",
            "",
        ),
        "approved_image": (
            relative_asset_path(photo_path)
        ),
        "library_filename": photo_path.name,
        "storage_bucket": metadata.get(
            "storage_bucket",
            "",
        ),
        "storage_key": metadata.get(
            "storage_key",
            "",
        ),
        "curated": True,
        "artist_photo": True,
    }


def run(*, slug: str) -> None:
    production = Production(slug)

    source_type = normalized(
        production.documentary.source_type
    )

    if source_type not in {
        "artist",
        "artist_story",
        "premium_artist",
    }:
        print(
            "✓ Approved artist-photo assignment "
            "skipped: not an artist production"
        )
        return

    directories = (
        historical_directories_for_production(
            production
        )
    )

    records = approved_metadata(
        directories.metadata
    )

    if not records:
        print(
            "✓ No approved artist photos available"
        )
        return

    artist_name = str(
        records[0].get("artist_name")
        or production.slug
    ).strip()

    storyboard_path = (
        production.production_root
        / "storyboard.json"
    )
    storyboard = load_json(storyboard_path)

    shots = all_visual_shots(
        storyboard
    )

    existing_artist_photos = sum(
        1
        for shot in shots
        if isinstance(
            shot.get("historical_asset"),
            dict,
        )
        and shot["historical_asset"].get(
            "artist_photo"
        )
    )

    target_count = max(
        1,
        round(len(shots) * 0.25),
    )

    remaining_target = max(
        0,
        target_count
        - existing_artist_photos,
    )

    if remaining_target == 0:
        print(
            "✓ Approved artist photos already "
            f"assigned: {existing_artist_photos}"
        )
        return

    eligible_shots = [
        shot
        for shot in shots
        if not shot.get("historical_asset")
        and is_safe_artist_shot(
            shot,
            artist_name,
        )
    ]

    if len(eligible_shots) > remaining_target:
        if remaining_target == 1:
            eligible_shots = [
                eligible_shots[
                    len(eligible_shots) // 2
                ]
            ]
        else:
            last_index = (
                len(eligible_shots) - 1
            )

            selected_indexes = [
                round(
                    index
                    * last_index
                    / (remaining_target - 1)
                )
                for index in range(
                    remaining_target
                )
            ]

            eligible_shots = [
                eligible_shots[index]
                for index in selected_indexes
            ]

    if not eligible_shots:
        print(
            "✓ No safe artist-photo shots "
            "need assignment"
        )
        return

    cache_dir = (
        production.work_root
        / "approved_artist_photos"
    )
    cache_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    restored: list[
        tuple[dict[str, Any], Path]
    ] = []

    for metadata in records:
        filename = str(
            metadata.get("approved_image")
            or Path(
                str(metadata["storage_key"])
            ).name
        )

        destination = cache_dir / filename

        download_photo(
            metadata=metadata,
            destination=destination,
        )

        restored.append(
            (metadata, destination)
        )

    backup_path = storyboard_path.with_suffix(
        ".before-approved-artist-photos.json"
    )

    if not backup_path.exists():
        backup_path.write_text(
            storyboard_path.read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )

    assigned = 0

    for index, shot in enumerate(
        eligible_shots
    ):
        metadata, photo_path = restored[
            index % len(restored)
        ]

        shot["source"] = (
            "curated_artist_photo"
        )
        shot["historical_asset"] = (
            build_historical_asset(
                metadata=metadata,
                photo_path=photo_path,
            )
        )
        shot["review_notes"] = (
            "Automatically assigned from the "
            "approved artist-photo library."
        )
        assigned += 1

    save_json_atomic(
        storyboard_path,
        storyboard,
    )

    print()
    print(
        "TOPSPOT STUDIO — APPROVED "
        "ARTIST PHOTOS"
    )
    print("=" * 70)
    print(f"Artist:     {artist_name}")
    print(f"Approved:   {len(records)}")
    print(f"Restored:   {len(restored)}")
    print(f"Assigned:   {assigned}")
    print(f"Cache:      {cache_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Restore approved artist photos "
            "and assign them to safe storyboard "
            "shots."
        )
    )
    parser.add_argument(
        "--slug",
        required=True,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(slug=args.slug)


if __name__ == "__main__":
    main()