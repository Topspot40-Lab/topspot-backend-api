from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

import requests

from backend.config import XAI_API_BASE, XAI_API_KEY
from backend.studio.production import Production


IMAGE_MODEL = "grok-imagine-image"
IMAGE_ASPECT_RATIO = "16:9"


def load_storyboard(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Storyboard not found: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def build_prompt(
    *,
    documentary_title: str,
    scene_title: str,
    visual_prompt: str,
) -> str:
    return (
        f"Create a premium documentary still for "
        f"'{documentary_title}'. "

        f"Scene: {scene_title}. "

        f"{visual_prompt}. "

        "The image must be historically accurate for the time period. "
        "Authentic clothing, hairstyles, architecture, furniture, "
        "television equipment, automobiles, cameras, lighting, and props. "

        "Look like a restored archival photograph or a frame from a "
        "high-end PBS or Ken Burns documentary. "

        "Warm cinematic lighting. Rich natural color. "
        "Emotionally engaging composition. "

        "No captions. "
        "No logos. "
        "No visible text. "
        "No watermarks. "

        "Ultra-realistic. 16:9 widescreen."
    )


def generate_image(prompt: str) -> bytes:
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
        print("XAI IMAGE ERROR STATUS:", response.status_code)
        print("XAI IMAGE ERROR BODY:", response.text)
        response.raise_for_status()

    data = response.json()
    items = data.get("data") or []

    if not items:
        raise RuntimeError("xAI returned no image data.")

    encoded = items[0].get("b64_json")

    if not encoded:
        raise RuntimeError(
            "xAI response did not contain b64_json image data."
        )

    return base64.b64decode(encoded)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument(
        "--scene",
        type=int,
        help="Generate only one numbered scene.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate every storyboard scene.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace images that already exist.",
    )
    args = parser.parse_args()

    if not args.all and args.scene is None:
        raise SystemExit("Use either --scene NUMBER or --all.")

    production = Production(args.slug)
    production.ensure_work_dirs()

    storyboard_path = production.work_root / "storyboard.json"
    storyboard = load_storyboard(storyboard_path)
    scenes = storyboard["scenes"]

    if args.scene is not None:
        scenes = [
            scene
            for scene in scenes
            if int(scene["scene"]) == args.scene
        ]

        if not scenes:
            raise SystemExit(
                f"Scene {args.scene} was not found in the storyboard."
            )

    images_dir = production.work_root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    print("🎨 TopSpot40 Studio Image Generator")
    print(f"Production: {storyboard['title']}")
    print(f"Scenes selected: {len(scenes)}")
    print()

    for scene in scenes:
        image_path = images_dir / scene["image_file"]

        if image_path.exists() and not args.force:
            print(f"↷ Skipped existing: {image_path.name}")
            continue

        prompt = build_prompt(
            documentary_title=storyboard["title"],
            scene_title=scene["title"],
            visual_prompt=scene["visual_prompt"],
        )

        print(
            f"Generating scene {scene['scene']:02d}: "
            f"{scene['title']}"
        )

        image_bytes = generate_image(prompt)
        image_path.write_bytes(image_bytes)

        print(
            f"✓ Saved {image_path} "
            f"({len(image_bytes):,} bytes)"
        )

    print()
    print("✅ Image generation complete")


if __name__ == "__main__":
    main()
