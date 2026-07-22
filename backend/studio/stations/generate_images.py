from __future__ import annotations

import argparse
import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.studio.production import Production
from backend.studio.visuals.image_quality import (
    build_corrective_prompt,
    evaluate_image_bytes,
)
from backend.studio.visuals.image_qa_summary import (
    print_image_qa_summary,
    write_image_qa_summary,
)


IMAGE_MODEL = "grok-imagine-image"
IMAGE_ASPECT_RATIO = "16:9"


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


def all_visual_shots(
    storyboard: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        shot
        for scene in storyboard.get("scenes", [])
        for shot in scene.get("visual_shots", [])
    ]


def generate_image_once(prompt: str) -> bytes:
    """
    Generate one image through xAI.

    Imports are deliberately lazy so --help and module imports work
    without requiring API configuration.
    """
    import requests

    from backend.config import XAI_API_BASE, XAI_API_KEY

    if not XAI_API_KEY:
        raise RuntimeError(
            "XAI_API_KEY is missing. Check your .env file."
        )

    response = requests.post(
        f"{XAI_API_BASE}/images/generations",
        headers={
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": IMAGE_MODEL,
            "prompt": prompt,
            "n": 1,
            "aspect_ratio": IMAGE_ASPECT_RATIO,
            "response_format": "b64_json",
        },
        timeout=(10, 300),
    )

    if not response.ok:
        print("xAI image error status:", response.status_code)
        print("xAI image error body:", response.text)
        response.raise_for_status()

    payload = response.json()
    items = payload.get("data") or []

    if not items:
        raise RuntimeError("xAI returned no image data.")

    encoded = items[0].get("b64_json")

    if not encoded:
        raise RuntimeError(
            "xAI response did not contain b64_json image data."
        )

    return base64.b64decode(encoded)

def generate_image(
    prompt: str,
    *,
    max_attempts: int = 5,
    initial_delay_seconds: float = 3.0,
) -> bytes:
    """
    Generate one image with retries for temporary network failures.

    Existing image files are still skipped by the normal station logic,
    so rerunning the pipeline resumes at the first missing shot.
    """
    import random
    import time

    import requests

    delay = initial_delay_seconds
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return generate_image_once(prompt)

        except requests.exceptions.HTTPError as exc:
            status = (
                exc.response.status_code
                if exc.response is not None
                else None
            )

            # Authentication, permissions, and most bad requests will not
            # improve by retrying. Rate limits and server errors may.
            retryable = (
                status is None
                or status in {408, 409, 425, 429}
                or status >= 500
            )

            if not retryable:
                raise

            last_error = exc

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.SSLError,
            requests.exceptions.ChunkedEncodingError,
            OSError,
        ) as exc:
            last_error = exc

        if attempt == max_attempts:
            break

        jitter = random.uniform(0.0, 1.5)
        wait_seconds = delay + jitter

        print(
            f"  ⚠ Image request failed "
            f"(attempt {attempt}/{max_attempts}): "
            f"{type(last_error).__name__}: {last_error}"
        )
        print(
            f"  ↻ Retrying in {wait_seconds:.1f} seconds..."
        )

        time.sleep(wait_seconds)
        delay = min(delay * 2.0, 30.0)

    raise RuntimeError(
        f"Image generation failed after {max_attempts} attempts."
    ) from last_error


def validate_prompt(shot: dict[str, Any]) -> str:
    prompt = str(shot.get("prompt") or "").strip()

    if not prompt:
        raise RuntimeError(
            f"Shot {shot.get('shot_number')} has no image prompt."
        )

    if shot.get("status") not in {
        "prompt_ready",
        "image_ready",
        "approved",
    }:
        raise RuntimeError(
            f"Shot {shot.get('shot_number')} is not prompt-ready. "
            f"Status={shot.get('status')!r}"
        )

    return prompt


def image_is_valid(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def update_production_record(
    production: Production,
    *,
    image_count: int,
) -> None:
    manifest = dict(production.manifest)
    status = dict(manifest.get("status", {}))
    artifacts = dict(manifest.get("artifacts", {}))

    status.update(
        {
            "current_station": "images_ready",
            "images_ready": True,
            "image_review_complete": False,
        }
    )

    artifacts.update(
        {
            "images_directory": "images",
            "image_count": image_count,
        }
    )

    manifest["status"] = status
    manifest["artifacts"] = artifacts
    manifest["updated_at"] = datetime.now(UTC).isoformat()

    save_json_atomic(
        production.manifest_path,
        manifest,
    )


def generate_images(
    *,
    slug: str,
    shot_number: int | None,
    generate_all: bool,
    force: bool,
) -> None:
    production = Production(slug)
    production.ensure_work_dirs()

    station_name = "generate_images"
    production.session.start_station(station_name)

    storyboard_path = (
        production.production_root / "storyboard.json"
    )
    storyboard = load_json(storyboard_path)

    shots = all_visual_shots(storyboard)

    if not shots:
        raise RuntimeError(
            f"Storyboard contains no visual shots: {storyboard_path}"
        )

    if shot_number is not None:
        selected = [
            shot
            for shot in shots
            if int(shot["shot_number"]) == shot_number
        ]

        if not selected:
            raise LookupError(
                f"Visual shot {shot_number} was not found."
            )
    elif generate_all:
        selected = shots
    else:
        raise ValueError("Use either --shot NUMBER or --all.")

    images_root = production.work_root / "images"
    images_root.mkdir(parents=True, exist_ok=True)

    qa_root = production.work_root / "image_qa"
    qa_root.mkdir(parents=True, exist_ok=True)

    generated_count = 0
    regenerated_count = 0
    skipped_count = 0

    for shot in selected:
        number = int(shot["shot_number"])
        filename = str(
            shot.get("filename") or f"{number:03d}.png"
        )
        destination = images_root / filename

        historical_asset = shot.get(
            "historical_asset"
        )

        approved_historical_image = ""

        if isinstance(
            historical_asset,
            dict,
        ):
            approved_historical_image = str(
                historical_asset.get(
                    "approved_image"
                )
                or ""
            ).strip()

        if approved_historical_image:
            print(
                f"↷ Shot {number:03d}: approved "
                "historical image assigned"
            )

            shot["status"] = (
                "historical_image_ready"
            )
            skipped_count += 1

            save_json_atomic(
                storyboard_path,
                storyboard,
            )
            continue

        if image_is_valid(destination) and not force:
            print(
                f"↷ Shot {number:03d}: existing image "
                f"({destination.stat().st_size:,} bytes)"
            )

            shot["status"] = "image_ready"
            shot["image_path"] = (
                f"images/{filename}"
            )
            skipped_count += 1

            save_json_atomic(
                storyboard_path,
                storyboard,
            )
            continue

        prompt = validate_prompt(shot)

        print(
            f"Generating shot {number:03d}: "
            f"{shot.get('visual_intent', '')}"
        )

        attempts: list[dict[str, Any]] = []

        first_bytes = generate_image(prompt)

        if not first_bytes:
            raise RuntimeError(
                f"Shot {number:03d}: xAI returned an empty image."
            )

        first_quality = evaluate_image_bytes(first_bytes)

        attempts.append(
            {
                "attempt": 1,
                "score": first_quality.score,
                "passed": first_quality.passed,
                "quality": first_quality.to_dict(),
            }
        )

        best_bytes = first_bytes
        best_quality = first_quality
        selected_attempt = 1

        print(
            f"  QA attempt 1: {first_quality.score}/100 "
            f"({'pass' if first_quality.passed else 'retry'})"
        )

        if not first_quality.passed:
            retry_prompt = build_corrective_prompt(
                prompt,
                first_quality,
            )

            print(
                f"  ↻ Shot {number:03d}: "
                "local QA requested one regeneration"
            )

            second_bytes = generate_image(retry_prompt)

            if second_bytes:
                second_quality = evaluate_image_bytes(
                    second_bytes
                )

                attempts.append(
                    {
                        "attempt": 2,
                        "score": second_quality.score,
                        "passed": second_quality.passed,
                        "quality": second_quality.to_dict(),
                    }
                )

                print(
                    f"  QA attempt 2: "
                    f"{second_quality.score}/100 "
                    f"({'pass' if second_quality.passed else 'best available'})"
                )

                regenerated_count += 1

                if second_quality.score > first_quality.score:
                    best_bytes = second_bytes
                    best_quality = second_quality
                    selected_attempt = 2

        destination.write_bytes(best_bytes)

        qa_payload = {
            "shot_number": number,
            "filename": filename,
            "evaluated_at": datetime.now(UTC).isoformat(),
            "selected_attempt": selected_attempt,
            "final_score": best_quality.score,
            "passed": best_quality.passed,
            "attempt_count": len(attempts),
            "attempts": attempts,
        }

        save_json_atomic(
            qa_root / f"{number:03d}.json",
            qa_payload,
        )

        shot["status"] = "image_ready"
        shot["image_path"] = f"images/{filename}"
        shot["generated_at"] = datetime.now(UTC).isoformat()
        shot["approved"] = False
        shot["image_qa"] = {
            "score": best_quality.score,
            "passed": best_quality.passed,
            "attempts": len(attempts),
            "selected_attempt": selected_attempt,
            "report": f"image_qa/{number:03d}.json",
        }

        storyboard["updated_at"] = datetime.now(UTC).isoformat()

        # Save after every generated image so the station can resume.
        save_json_atomic(
            storyboard_path,
            storyboard,
        )

        generated_count += 1

        print(
            f"✓ Saved {destination} "
            f"({destination.stat().st_size:,} bytes)"
        )

    ready_shots = []

    for shot in shots:
        number = int(shot["shot_number"])
        filename = str(
            shot.get("filename") or f"{number:03d}.png"
        )
        image_path = images_root / filename

        if image_is_valid(image_path):
            ready_shots.append(shot)
            shot["status"] = "image_ready"
            shot["image_path"] = f"images/{filename}"

    all_ready = len(ready_shots) == len(shots)

    storyboard["images_ready"] = all_ready
    storyboard["updated_at"] = datetime.now(UTC).isoformat()

    save_json_atomic(
        storyboard_path,
        storyboard,
    )

    qa_summary = write_image_qa_summary(
        production_slug=slug,
        qa_root=qa_root,
    )

    if all_ready:
        update_production_record(
            production,
            image_count=len(ready_shots),
        )

    print()
    print(f"Generated:   {generated_count}")
    print(f"Regenerated: {regenerated_count}")
    print(f"Skipped:     {skipped_count}")
    print(f"Ready:       {len(ready_shots)} of {len(shots)}")
    print(
        f"Entire image set ready: "
        f"{'yes' if all_ready else 'no'}"
    )

    production.session.metric(
        "generated",
        generated_count,
        station=station_name,
    )
    production.session.metric(
        "regenerated",
        regenerated_count,
        station=station_name,
    )
    production.session.metric(
        "skipped",
        skipped_count,
        station=station_name,
    )
    production.session.metric(
        "ready_images",
        len(ready_shots),
        station=station_name,
    )
    production.session.metric(
        "total_images",
        len(shots),
        station=station_name,
    )
    production.session.metric(
        "qa_average_score",
        qa_summary.average_score,
        station=station_name,
    )
    production.session.metric(
        "qa_passed",
        qa_summary.passed,
        station=station_name,
    )
    production.session.metric(
        "qa_below_threshold",
        qa_summary.below_threshold,
        station=station_name,
    )

    production.session.artifact(
        "images_directory",
        images_root,
        station=station_name,
    )
    production.session.artifact(
        "qa_summary",
        qa_root / "summary.json",
        station=station_name,
    )

    production.session.finish_station(
        station_name,
        success=all_ready,
    )

    print_image_qa_summary(qa_summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate documentary images from the visual-shot "
            "prompts in a TopSpot Studio storyboard."
        )
    )

    parser.add_argument(
        "--slug",
        required=True,
        help="Existing production slug, such as casey_kasem.",
    )

    parser.add_argument(
        "--shot",
        type=int,
        help="Generate only one numbered visual shot.",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate every visual shot.",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace images that already exist.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.shot is not None and args.all:
        raise SystemExit(
            "❌ Use --shot NUMBER or --all, not both."
        )

    try:
        production = Production(args.slug)

        print()
        print("Factory Station 5 — Generate Images")
        print(f"Production: {production.documentary.title}")
        print(f"Slug:       {production.slug}")

        if args.shot is not None:
            print(f"Shot:       {args.shot}")
        elif args.all:
            print("Shot:       all")

        print()

        generate_images(
            slug=args.slug,
            shot_number=args.shot,
            generate_all=args.all,
            force=args.force,
        )

    except (
        FileNotFoundError,
        KeyError,
        LookupError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise SystemExit(f"❌ {exc}") from exc

    print()
    print("✅ Factory Station 5 run complete")


if __name__ == "__main__":
    main()
