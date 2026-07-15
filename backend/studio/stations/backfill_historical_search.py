from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from backend.studio.production import Production
from backend.studio.stations.generate_visual_plan import (
    request_visual_plan,
)


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
    *,
    attempts: int = 5,
) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")

    temporary_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    last_error: OSError | None = None

    for attempt in range(1, attempts + 1):
        try:
            temporary_path.replace(path)
            return
        except PermissionError as exc:
            last_error = exc

            if attempt == attempts:
                break

            time.sleep(0.5 * attempt)

    raise RuntimeError(
        f"Could not replace {path} after {attempts} attempts. "
        "Close any editor or process holding the file open."
    ) from last_error


def find_scene(
    storyboard: dict[str, Any],
    scene_number: int,
) -> dict[str, Any]:
    for scene in storyboard.get("scenes", []):
        if int(scene["scene_number"]) == scene_number:
            return scene

    raise LookupError(f"Scene {scene_number} was not found.")


def backfill_scene(
    *,
    documentary_title: str,
    scene: dict[str, Any],
    force: bool,
) -> tuple[int, int]:
    shots = scene.get("visual_shots", [])

    needs_search = [
        shot
        for shot in shots
        if force
        or "historical_plan" not in shot
        or not isinstance(
            shot.get("historical_plan"),
            dict,
        )
    ]

    if not needs_search:
        return 0, len(shots)

    plan = request_visual_plan(
        documentary_title=documentary_title,
        scene=scene,
    )

    plan_by_number = {
        int(item["shot_number"]): item
        for item in plan
    }

    updated = 0
    skipped = 0

    for shot in shots:
        number = int(shot["shot_number"])
        existing_plan = shot.get(
            "historical_plan"
        )

        if (
            isinstance(existing_plan, dict)
            and existing_plan
            and not force
        ):
            skipped += 1
            continue

        plan_item = plan_by_number.get(number)

        if plan_item is None:
            raise RuntimeError(
                f"Scene {scene['scene_number']}: "
                f"visual plan omitted shot {number}."
            )

        historical_search = str(
            plan_item.get("historical_search") or ""
        ).strip()

        if len(historical_search) > 160:
            raise RuntimeError(
                f"Shot {number}: historical_search exceeds "
                "160 characters."
            )

        historical_plan = plan_item.get(
            "historical_plan",
            {},
        )

        if not isinstance(historical_plan, dict):
            historical_plan = {}

        # Preserve generated images and shot status. Only historical
        # research metadata is upgraded.
        shot["historical_search"] = historical_search
        shot["historical_plan"] = {
            "subject": str(
                historical_plan.get(
                    "subject",
                    "",
                )
            ).strip(),
            "subject_type": str(
                historical_plan.get(
                    "subject_type",
                    "generic",
                )
            ).strip(),
            "era": str(
                historical_plan.get("era", "")
            ).strip(),
            "required_terms": [
                str(value).strip()
                for value in historical_plan.get(
                    "required_terms",
                    [],
                )
                if str(value).strip()
            ],
            "avoid_terms": [
                str(value).strip()
                for value in historical_plan.get(
                    "avoid_terms",
                    [],
                )
                if str(value).strip()
            ],
            "search_queries": [
                str(value).strip()
                for value in historical_plan.get(
                    "search_queries",
                    [],
                )
                if str(value).strip()
            ],
        }
        updated += 1

    return updated, skipped


def run(
    *,
    slug: str,
    scene_number: int | None,
    backfill_all: bool,
    force: bool,
) -> None:
    production = Production(slug)

    storyboard_path = (
        production.production_root / "storyboard.json"
    )
    storyboard = load_json(storyboard_path)

    title = str(
        storyboard.get("title")
        or production.title
    )

    if scene_number is not None:
        scenes = [
            find_scene(storyboard, scene_number)
        ]
    elif backfill_all:
        scenes = list(storyboard.get("scenes", []))
    else:
        raise ValueError("Use either --scene NUMBER or --all.")

    if not scenes:
        raise RuntimeError(
            f"No storyboard scenes found: {storyboard_path}"
        )

    print("=" * 80)
    print("TOPSPOT STUDIO — HISTORICAL SEARCH BACKFILL")
    print("=" * 80)
    print(f"Production: {title}")
    print(f"Slug:       {slug}")
    print(f"Scenes:     {len(scenes)}")
    print(f"Force:      {force}")
    print()

    total_updated = 0
    total_skipped = 0

    for scene in scenes:
        number = int(scene["scene_number"])

        updated, skipped = backfill_scene(
            documentary_title=title,
            scene=scene,
            force=force,
        )

        total_updated += updated
        total_skipped += skipped

        print(
            f"Scene {number:03d}: "
            f"{updated} updated, {skipped} skipped"
        )

        # Save after every scene so a long run is resumable.
        save_json_atomic(
            storyboard_path,
            storyboard,
        )

    print()
    print(f"Historical searches added: {total_updated}")
    print(f"Existing searches skipped: {total_skipped}")
    print(f"Storyboard preserved:      {storyboard_path}")
    print()
    print("✅ Historical-search backfill complete")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Add historical_search phrases to existing storyboard "
            "shots without changing finished images or shot status."
        )
    )
    parser.add_argument("--slug", required=True)
    parser.add_argument(
        "--scene",
        type=int,
        help="Backfill one narration scene.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Backfill every narration scene.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing historical_search values.",
    )
    args = parser.parse_args()

    if args.scene is not None and args.all:
        raise SystemExit(
            "Use --scene or --all, not both."
        )

    if args.scene is None and not args.all:
        raise SystemExit(
            "Use either --scene NUMBER or --all."
        )

    run(
        slug=args.slug,
        scene_number=args.scene,
        backfill_all=args.all,
        force=args.force,
    )


if __name__ == "__main__":
    main()
