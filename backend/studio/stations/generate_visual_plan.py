from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.studio.production import Production


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

    temporary_path.replace(path)


def clean_json_response(raw: str) -> Any:
    cleaned = raw.strip()

    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):].lstrip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```"):].lstrip()

    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].rstrip()

    return json.loads(cleaned)


def build_scene_request(
    *,
    documentary_title: str,
    scene: dict[str, Any],
) -> dict[str, Any]:
    shots = scene.get("visual_shots", [])

    return {
        "scene_number": int(scene["scene_number"]),
        "narration": str(scene["narration"]),
        "shot_count": len(shots),
        "shots": [
            {
                "shot_number": int(shot["shot_number"]),
                "duration_seconds": float(
                    shot["estimated_seconds"]
                ),
            }
            for shot in shots
        ],
        "documentary_title": documentary_title,
    }


def request_visual_plan(
    *,
    documentary_title: str,
    scene: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Ask xAI to assign one distinct visual idea to every shot in one
    narration scene.

    The import is deliberately lazy so --help works without API setup.
    """
    from backend.services.xai_client import ask_xai

    request = build_scene_request(
        documentary_title=documentary_title,
        scene=scene,
    )

    prompt = f"""
Create a visual shot plan for one scene in a TopSpot40 music documentary.

DOCUMENTARY:
{documentary_title}

SCENE NUMBER:
{request["scene_number"]}

NARRATION:
{request["narration"]}

NUMBER OF VISUAL SHOTS:
{request["shot_count"]}

SHOT NUMBERS AND DURATIONS:
{json.dumps(request["shots"], indent=2)}

Create exactly one distinct visual idea for every listed shot.

Rules:
- Preserve every supplied shot_number exactly.
- Return exactly {request["shot_count"]} shot entries.
- Each shot must illustrate a different part, detail, mood, location,
  person, object, or consequence found in the narration.
- Avoid near-duplicate compositions within the same scene.
- Use historically believable details appropriate to the stated era.
- Prefer documentary-style visual storytelling.
- A real named person may be represented respectfully and recognizably.
- Do not include captions, signs, logos, trademarks, visible writing,
  album covers, television screenshots, or watermarks.
- Do not invent factual events that are absent from the narration.
- Do not invent a person's age, gender, ethnicity, relationship, or
  identity unless the narration or historical context supports it.
- For a generic listener or audience, use an inclusive composition
  without unnecessary demographic detail.
- Do not specify an exact decade unless the narration or surrounding
  historical context supports it.
- visual_intent should be a brief plain-language description.
- historical_search should be a concise web-archive search phrase.
- historical_search should contain only useful names, places, events,
  programs, organizations, and dates supported by the narration.
- Keep historical_search short, normally 3 to 10 words.
- Do not include cinematic styling, camera instructions, lighting,
  aspect ratio, moods, or phrases such as "documentary image."
- When the shot is generic and no specific historical photograph is
  likely to exist, return an empty string for historical_search.
- historical_plan must describe what would make a real archival image appropriate for this exact shot.
- historical_plan.subject is the named person, group, event, place, organization, or object shown. Use an empty string for a generic shot.
- historical_plan.subject_type must be one of: person, group, event, place, organization, object, generic.
- historical_plan.era should be a supported year, decade, event period, or life stage such as "childhood", "1968", or "early career".
- historical_plan.required_terms should contain zero to four concrete clues that establish scene relevance.
- historical_plan.avoid_terms should contain zero to four concrete clues that make an otherwise related image unsuitable.
- historical_plan.search_queries should contain two to five concise archive queries a human picture researcher might try.
- Do not include cinematic style, lighting, camera instructions, aspect ratio, or mood language in historical_plan.
- When historical_search is empty, historical_plan.search_queries must also be empty.
- image_prompt should be ready for a 16:9 documentary image generator.
- Include camera framing, setting, era, subjects, lighting, and mood.
- Return valid JSON only.
- No markdown and no commentary.

JSON format:
[
  {{
    "shot_number": 1,
    "visual_intent": "Brief description of what the viewer sees",
    "historical_search": "Concise archive search phrase or empty string",
    "historical_plan": {{
      "subject": "Named subject or empty string",
      "subject_type": "person",
      "era": "Supported year, decade, event period, or life stage",
      "required_terms": ["concrete relevance clue"],
      "avoid_terms": ["concrete mismatch clue"],
      "search_queries": [
        "concise archive query one",
        "concise archive query two"
      ]
    }},
    "image_prompt": "Complete image-generation prompt"
  }}
]
""".strip()

    raw = ask_xai(
        (
            "You are the visual director for historically grounded "
            "music documentaries. Produce distinct, cinematic shots "
            "that accurately support the supplied narration."
        ),
        prompt,
        temperature=0.25,
    )

    data = clean_json_response(raw)

    if not isinstance(data, list):
        raise RuntimeError(
            f"Scene {scene['scene_number']}: "
            "xAI response was not a JSON list."
        )

    return data


def validate_scene_plan(
    *,
    scene: dict[str, Any],
    plan: list[dict[str, Any]],
) -> None:
    expected_shots = [
        int(shot["shot_number"])
        for shot in scene.get("visual_shots", [])
    ]

    returned_shots: list[int] = []

    for item in plan:
        if not isinstance(item, dict):
            raise RuntimeError(
                f"Scene {scene['scene_number']}: "
                "visual plan contains a non-object entry."
            )

        shot_number = int(item["shot_number"])
        visual_intent = str(
            item.get("visual_intent", "")
        ).strip()
        historical_search = str(
            item.get("historical_search", "")
        ).strip()

        historical_plan = item.get(
            "historical_plan",
            {},
        )

        if not isinstance(historical_plan, dict):
            raise RuntimeError(
                f"Shot {shot_number}: "
                "historical_plan must be an object."
            )

        subject_type = str(
            historical_plan.get(
                "subject_type",
                "generic",
            )
        ).strip()

        allowed_subject_types = {
            "person",
            "group",
            "event",
            "place",
            "organization",
            "object",
            "generic",
        }

        if subject_type not in allowed_subject_types:
            raise RuntimeError(
                f"Shot {shot_number}: invalid "
                f"subject_type {subject_type!r}."
            )

        required_terms = historical_plan.get(
            "required_terms",
            [],
        )
        avoid_terms = historical_plan.get(
            "avoid_terms",
            [],
        )
        search_queries = historical_plan.get(
            "search_queries",
            [],
        )

        for field_name, values in (
            ("required_terms", required_terms),
            ("avoid_terms", avoid_terms),
            ("search_queries", search_queries),
        ):
            if not isinstance(values, list):
                raise RuntimeError(
                    f"Shot {shot_number}: "
                    f"{field_name} must be a list."
                )

            if not all(
                isinstance(value, str)
                for value in values
            ):
                raise RuntimeError(
                    f"Shot {shot_number}: "
                    f"{field_name} must contain strings."
                )

        if len(required_terms) > 4:
            raise RuntimeError(
                f"Shot {shot_number}: "
                "too many required_terms."
            )

        if len(avoid_terms) > 4:
            raise RuntimeError(
                f"Shot {shot_number}: "
                "too many avoid_terms."
            )

        if len(search_queries) > 5:
            raise RuntimeError(
                f"Shot {shot_number}: "
                "too many search_queries."
            )

        if not historical_search and search_queries:
            raise RuntimeError(
                f"Shot {shot_number}: search_queries "
                "must be empty when historical_search is empty."
            )

        image_prompt = str(
            item.get("image_prompt", "")
        ).strip()

        if not visual_intent:
            raise RuntimeError(
                f"Shot {shot_number}: visual_intent is empty."
            )

        if len(historical_search) > 160:
            raise RuntimeError(
                f"Shot {shot_number}: historical_search is too long "
                f"({len(historical_search)} characters)."
            )

        if not image_prompt:
            raise RuntimeError(
                f"Shot {shot_number}: image_prompt is empty."
            )

        returned_shots.append(shot_number)

    if returned_shots != expected_shots:
        raise RuntimeError(
            f"Scene {scene['scene_number']}: expected shot numbers "
            f"{expected_shots}, received {returned_shots}."
        )


def apply_scene_plan(
    *,
    scene: dict[str, Any],
    plan: list[dict[str, Any]],
) -> None:
    by_shot_number = {
        int(item["shot_number"]): item
        for item in plan
    }

    for shot in scene.get("visual_shots", []):
        shot_number = int(shot["shot_number"])
        plan_item = by_shot_number[shot_number]

        shot["visual_intent"] = str(
            plan_item["visual_intent"]
        ).strip()

        shot["historical_search"] = str(
            plan_item.get("historical_search", "")
        ).strip()

        historical_plan = plan_item.get(
            "historical_plan",
            {},
        )

        if not isinstance(historical_plan, dict):
            historical_plan = {}

        shot["historical_plan"] = {
            "subject": str(
                historical_plan.get("subject", "")
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

        shot["prompt"] = str(
            plan_item["image_prompt"]
        ).strip()

        shot["status"] = "prompt_ready"
        shot["approved"] = False


def count_shots(storyboard: dict[str, Any]) -> int:
    return sum(
        len(scene.get("visual_shots", []))
        for scene in storyboard.get("scenes", [])
    )


def update_production_record(
    production: Production,
    *,
    visual_shot_count: int,
) -> None:
    manifest = dict(production.manifest)
    status = dict(manifest.get("status", {}))
    artifacts = dict(manifest.get("artifacts", {}))

    status.update(
        {
            "current_station": "visual_plan_ready",
            "visual_plan_ready": True,
            "images_ready": False,
            "image_review_complete": False,
        }
    )

    artifacts.update(
        {
            "visual_plan": "storyboard.json",
            "visual_shot_count": visual_shot_count,
        }
    )

    manifest["status"] = status
    manifest["artifacts"] = artifacts
    manifest["updated_at"] = datetime.now(UTC).isoformat()

    save_json_atomic(
        production.manifest_path,
        manifest,
    )


def generate_visual_plan(
    *,
    slug: str,
    refresh: bool,
    scene_number: int | None,
) -> Path:
    production = Production(slug)
    storyboard_path = (
        production.production_root / "storyboard.json"
    )
    storyboard = load_json(storyboard_path)

    scenes = storyboard.get("scenes", [])

    if not scenes:
        raise RuntimeError(
            f"Storyboard contains no scenes: {storyboard_path}"
        )

    if scene_number is not None:
        selected_scenes = [
            scene
            for scene in scenes
            if int(scene["scene_number"]) == scene_number
        ]

        if not selected_scenes:
            raise LookupError(
                f"Scene {scene_number} was not found."
            )
    else:
        selected_scenes = scenes

    completed_scenes = 0
    completed_shots = 0

    for scene in selected_scenes:
        shots = scene.get("visual_shots", [])

        if not shots:
            raise RuntimeError(
                f"Scene {scene['scene_number']} has no visual shots."
            )

        already_ready = all(
            shot.get("status") == "prompt_ready"
            and shot.get("prompt")
            for shot in shots
        )

        if already_ready and not refresh:
            print(
                f"↷ Scene {int(scene['scene_number']):02d}: "
                f"prompts already ready"
            )
            completed_scenes += 1
            completed_shots += len(shots)
            continue

        print(
            f"Planning scene {int(scene['scene_number']):02d} "
            f"({len(shots)} visual shot(s))..."
        )

        plan = request_visual_plan(
            documentary_title=production.documentary.title,
            scene=scene,
        )

        validate_scene_plan(
            scene=scene,
            plan=plan,
        )

        apply_scene_plan(
            scene=scene,
            plan=plan,
        )

        # Save after every scene so completed work survives an
        # interruption or API failure later in the run.
        storyboard["updated_at"] = datetime.now(UTC).isoformat()
        save_json_atomic(
            storyboard_path,
            storyboard,
        )

        completed_scenes += 1
        completed_shots += len(shots)

        print(
            f"✓ Scene {int(scene['scene_number']):02d}: "
            f"{len(shots)} prompt(s) ready"
        )

    all_shots = [
        shot
        for scene in scenes
        for shot in scene.get("visual_shots", [])
    ]

    all_ready = bool(all_shots) and all(
        shot.get("status") == "prompt_ready"
        and shot.get("prompt")
        for shot in all_shots
    )

    storyboard["visual_plan_ready"] = all_ready
    storyboard["updated_at"] = datetime.now(UTC).isoformat()

    save_json_atomic(
        storyboard_path,
        storyboard,
    )

    if all_ready:
        update_production_record(
            production,
            visual_shot_count=count_shots(storyboard),
        )

    print()
    print(
        f"Scenes processed: {completed_scenes}"
    )
    print(
        f"Shots processed:  {completed_shots}"
    )
    print(
        f"Entire visual plan ready: {'yes' if all_ready else 'no'}"
    )

    return storyboard_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate distinct visual intents and image prompts for "
            "an existing TopSpot Studio storyboard."
        )
    )

    parser.add_argument(
        "--slug",
        required=True,
        help="Existing production slug, such as casey_kasem.",
    )

    parser.add_argument(
        "--scene",
        type=int,
        help="Generate or refresh only one narration scene.",
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Replace visual plans that are already prompt-ready.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        production = Production(args.slug)

        print()
        print("Factory Station 4 — Generate Visual Plan")
        print(f"Production: {production.documentary.title}")
        print(f"Slug:       {production.slug}")

        if args.scene is not None:
            print(f"Scene:      {args.scene}")
        else:
            print("Scene:      all")

        print()

        storyboard_path = generate_visual_plan(
            slug=args.slug,
            refresh=args.refresh,
            scene_number=args.scene,
        )

    except (
        FileNotFoundError,
        KeyError,
        LookupError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise SystemExit(f"❌ {exc}") from exc

    print()
    print(f"✓ Visual plan saved: {storyboard_path}")
    print()
    print("✅ Factory Station 4 complete")
    print("   No images generated yet.")


if __name__ == "__main__":
    main()
