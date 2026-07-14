from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from backend.studio.production import Production


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_candidate_image(directory: Path) -> Path | None:
    for extension in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = directory / f"candidate{extension}"
        if candidate.exists():
            return candidate

    return None


def escape(value: Any) -> str:
    return html.escape(str(value or ""))


def build_page(slug: str) -> Path:
    production = Production(slug)

    storyboard_path = (
        production.production_root / "storyboard.json"
    )
    storyboard = load_json(storyboard_path)

    candidates_root = (
        production.work_root / "historical_candidates"
    )
    candidates_root.mkdir(parents=True, exist_ok=True)

    cards: list[str] = []

    for scene in storyboard.get("scenes", []):
        narration = str(scene.get("narration") or "")

        for shot in scene.get("visual_shots", []):
            shot_number = int(shot["shot_number"])
            candidate_dir = candidates_root / f"{shot_number:03d}"
            metadata_path = candidate_dir / "candidate.json"

            if not metadata_path.exists():
                continue

            metadata = load_json(metadata_path)
            candidate_image = find_candidate_image(candidate_dir)

            if candidate_image is None:
                continue

            filename = str(
                shot.get("filename")
                or f"{shot_number:03d}.png"
            )

            ai_relative = (
                Path("..") / "images" / filename
            ).as_posix()

            candidate_relative = (
                Path(f"{shot_number:03d}")
                / candidate_image.name
            ).as_posix()

            approved = bool(shot.get("historical_asset"))

            approval_command = (
                ".venv/Scripts/python -m "
                "backend.studio.stations.approve_historical_image "
                f"--slug {slug} --shot {shot_number}"
            )

            cards.append(
                f"""
<section class="card">
  <div class="heading">
    <h2>Shot {shot_number:03d}</h2>
    <span class="status">
      {"APPROVED" if approved else "REVIEW"}
    </span>
  </div>

  <p><strong>Scene:</strong>
    {escape(scene.get("scene_number"))}
  </p>

  <p><strong>Narration:</strong>
    {escape(narration)}
  </p>

  <p><strong>Archive search:</strong>
    {escape(shot.get("historical_search"))}
  </p>

  <div class="comparison">
    <figure>
      <img src="{escape(ai_relative)}"
           alt="Current AI image">
      <figcaption>Current AI image</figcaption>
    </figure>

    <figure>
      <img src="{escape(candidate_relative)}"
           alt="Historical candidate">
      <figcaption>Historical candidate</figcaption>
    </figure>
  </div>

  <div class="metadata">
    <p><strong>Candidate:</strong>
      {escape(metadata.get("title"))}
    </p>

    <p><strong>Description:</strong>
      {escape(metadata.get("description"))}
    </p>

    <p><strong>Date:</strong>
      {escape(metadata.get("date") or "Not supplied")}
    </p>

    <p><strong>Creator:</strong>
      {escape(metadata.get("creator") or "Not supplied")}
    </p>

    <p><strong>License:</strong>
      {escape(metadata.get("license_name"))}
    </p>

    <p><strong>Score:</strong>
      {escape(metadata.get("score"))}
    </p>

    <p>
      <a href="{escape(metadata.get("page_url"))}"
         target="_blank">
        Open Wikimedia source page
      </a>
    </p>
  </div>

  <pre>{escape(approval_command)}</pre>
</section>
"""
            )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(storyboard.get("title"))} — Historical Review</title>
<style>
  body {{
    margin: 0;
    padding: 2rem;
    background: #171717;
    color: #f3f3f3;
    font-family: Arial, sans-serif;
  }}

  h1 {{
    margin-top: 0;
  }}

  .summary {{
    margin-bottom: 2rem;
    color: #cccccc;
  }}

  .card {{
    max-width: 1400px;
    margin: 0 auto 2rem;
    padding: 1.25rem;
    border: 1px solid #444;
    border-radius: 12px;
    background: #242424;
  }}

  .heading {{
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}

  .status {{
    padding: 0.35rem 0.7rem;
    border-radius: 999px;
    background: #444;
    font-weight: bold;
  }}

  .comparison {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    margin: 1rem 0;
  }}

  figure {{
    margin: 0;
  }}

  img {{
    display: block;
    width: 100%;
    aspect-ratio: 16 / 9;
    object-fit: contain;
    background: black;
    border-radius: 8px;
  }}

  figcaption {{
    padding-top: 0.5rem;
    text-align: center;
    color: #cccccc;
  }}

  .metadata {{
    line-height: 1.45;
  }}

  a {{
    color: #8cc8ff;
  }}

  pre {{
    overflow-x: auto;
    padding: 0.8rem;
    background: #111;
    border-radius: 6px;
    color: #d7ffd7;
  }}

  @media (max-width: 850px) {{
    .comparison {{
      grid-template-columns: 1fr;
    }}
  }}
</style>
</head>
<body>
<h1>{escape(storyboard.get("title"))} — Historical Image Review</h1>

<p class="summary">
  Downloaded candidates: {len(cards)}.
  Compare each historical candidate with the current AI image.
  Nothing on this page is approved automatically.
</p>

{"".join(cards)}
</body>
</html>
"""

    destination = candidates_root / "review.html"
    destination.write_text(page, encoding="utf-8")

    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    destination = build_page(args.slug)

    print(f"✅ Historical review page: {destination}")


if __name__ == "__main__":
    main()
