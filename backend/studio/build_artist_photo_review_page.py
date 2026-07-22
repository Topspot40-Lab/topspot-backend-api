from __future__ import annotations

import argparse
import html
import json
import shlex
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from sqlmodel import Session

from backend.database import engine
from backend.models.dbmodels import Artist
from backend.studio.collect_artist_photo import (
    candidate_matches_artist,
)
from backend.studio.documentary import slugify
from backend.studio.historical.providers.wikimedia import (
    WikimediaCommonsProvider,
)
from backend.studio.historical.ranking import (
    candidate_is_usable,
    normalized_phrase,
    score_candidate,
)
from backend.studio.historical_assets import (
    historical_directories,
)


WORK_ROOT = Path(
    "backend/studio/work/artist_photo_research"
)


def escape(value: Any) -> str:
    return html.escape(
        str(value or ""),
        quote=True,
    )


def load_artist(artist_id: int) -> Artist:
    with Session(engine) as db:
        artist = db.get(Artist, artist_id)

        if artist is None:
            raise LookupError(
                f"Artist ID not found: {artist_id}"
            )

        return artist


def default_queries(artist_name: str) -> list[str]:
    quoted_name = f'"{artist_name}"'

    return [
        quoted_name,
        f"{quoted_name} singer musician",
        f"{quoted_name} portrait",
        f"{quoted_name} concert performance",
        f"{quoted_name} publicity press photo",
        f"{quoted_name} recording studio",
    ]


NON_PORTRAIT_TITLE_TERMS = {
    "album",
    "awardees",
    "building",
    "hall",
    "museum",
    "plaque",
    "poster",
    "record",
    "statue",
    "theater",
    "theatre",
}


def likely_artist_photo(
    candidate,
    artist_name: str,
) -> bool:
    title = normalized_phrase(candidate.title)
    artist = normalized_phrase(artist_name)

    if not artist or artist not in title:
        return False

    title_words = set(title.split())

    return not bool(
        title_words & NON_PORTRAIT_TITLE_TERMS
    )


def approved_page_urls(
    artist_slug: str,
) -> set[str]:
    directories = historical_directories(
        source_type="artist_story",
        slug=artist_slug,
    )

    urls: set[str] = set()

    for metadata_path in directories.metadata.glob(
        "*.json"
    ):
        try:
            metadata = json.loads(
                metadata_path.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError):
            continue

        page_url = str(
            metadata.get("page_url") or ""
        )

        if page_url:
            urls.add(page_url)

    return urls


def approval_command(
    *,
    artist_id: int,
    query: str,
    limit: int,
    page_url: str,
) -> str:
    arguments = [
        ".venv/Scripts/python",
        "-m",
        "dotenv",
        "run",
        "--",
        ".venv/Scripts/python",
        "-m",
        "backend.studio.collect_artist_photo",
        "--artist-id",
        str(artist_id),
        "--query",
        query,
        "--limit",
        str(limit),
        "--select-page-url",
        page_url,
    ]

    return (
        "PYTHONIOENCODING=utf-8 "
        + shlex.join(arguments)
    )


def build_page(
    *,
    artist_id: int,
    queries: list[str],
    limit: int,
) -> Path:
    artist = load_artist(artist_id)
    artist_name = artist.artist_name.strip()
    artist_slug = slugify(artist_name)

    provider = WikimediaCommonsProvider()
    approved_urls = approved_page_urls(
        artist_slug
    )

    merged: dict[str, dict[str, Any]] = {}
    rejected_count = 0

    print()
    print("TOPSPOT STUDIO — ARTIST PHOTO RESEARCH")
    print("=" * 70)
    print(f"Artist: {artist_name}")
    print(f"Queries: {len(queries)}")
    print()

    for query in queries:
        print(f"Searching: {query}")

        candidates = provider.search(
            query,
            limit=limit,
        )

        for candidate in candidates:
            if not candidate_is_usable(candidate):
                rejected_count += 1
                continue

            key = (
                candidate.page_url
                or candidate.original_url
            )

            if key not in merged:
                merged[key] = {
                    "candidate": candidate,
                    "queries": [],
                }

            merged[key]["queries"].append(query)

    records = list(merged.values())

    identity_review_count = sum(
        1
        for record in records
        if not candidate_matches_artist(
            record["candidate"],
            artist_name,
        )
        and record["candidate"].page_url
        not in approved_urls
    )

    records = [
        record
        for record in records
        if candidate_matches_artist(
            record["candidate"],
            artist_name,
        )
        or record["candidate"].page_url
        in approved_urls
    ]

    for record in records:
        score_candidate(
            record["candidate"],
            artist_name,
        )

    records.sort(
        key=lambda record: (
            likely_artist_photo(
                record["candidate"],
                artist_name,
            ),
            record["candidate"].score,
            record["candidate"].megapixels,
        ),
        reverse=True,
    )

    cards: list[str] = []

    for record in records:
        candidate = record["candidate"]
        matched_queries = record["queries"]
        identity_match = likely_artist_photo(
            candidate,
            artist_name,
        )
        already_approved = (
            candidate.page_url in approved_urls
        )

        if already_approved:
            status = "APPROVED"
            status_class = "approved"
        elif identity_match:
            status = "ELIGIBLE"
            status_class = "eligible"
        else:
            status = "REVIEW IDENTITY"
            status_class = "review"

        query = matched_queries[0]

        command = approval_command(
            artist_id=artist_id,
            query=query,
            limit=limit,
            page_url=candidate.page_url,
        )

        cards.append(
            f"""
<section class="card">
  <div class="heading">
    <span class="status {status_class}">
      {escape(status)}
    </span>
    <span>{candidate.width} × {candidate.height}</span>
  </div>

  <img
    src="{escape(candidate.thumbnail_url or candidate.original_url)}"
    alt="{escape(candidate.title)}"
    loading="lazy">

  <h2>{escape(candidate.title)}</h2>

  <dl>
    <dt>Date</dt>
    <dd>{escape(candidate.date or "Not supplied")}</dd>

    <dt>Creator</dt>
    <dd>{escape(candidate.creator or "Not supplied")}</dd>

    <dt>License</dt>
    <dd>{escape(candidate.license_name)}</dd>

    <dt>Queries</dt>
    <dd>{escape(", ".join(matched_queries))}</dd>
  </dl>

  <p class="description">
    {escape(candidate.description)}
  </p>

  <p>
    <a href="{escape(candidate.page_url)}"
       target="_blank">
      Open Wikimedia source
    </a>
  </p>
  <button
    type="button"
    class="copy-button"
    data-command="{escape(command)}"
    onclick="copyCommand(this)">
    Copy approval command
  </button>  
  <pre>{escape(command)}</pre>
</section>
"""
        )

    picryl_links = "\n".join(
        (
            '<a class="source-link" target="_blank" '
            f'href="https://picryl.com/search?q={quote_plus(query)}">'
            f'PICRYL: {escape(query)}</a>'
        )
        for query in queries
    )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(artist_name)} — Artist Photo Research</title>
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
    color: #cccccc;
    margin-bottom: 1.5rem;
  }}

  .source-links {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    margin-bottom: 2rem;
  }}

  .source-link {{
    padding: 0.55rem 0.8rem;
    border-radius: 999px;
    background: #333;
  }}

  .grid {{
    display: grid;
    grid-template-columns:
      repeat(auto-fit, minmax(340px, 1fr));
    gap: 1.25rem;
  }}

  .card {{
    padding: 1rem;
    border: 1px solid #444;
    border-radius: 12px;
    background: #242424;
  }}

  .heading {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.8rem;
  }}

  .status {{
    padding: 0.35rem 0.65rem;
    border-radius: 999px;
    font-weight: bold;
  }}

  .approved {{
    background: #176b37;
  }}

  .eligible {{
    background: #275d91;
  }}

  .review {{
    background: #7a5b12;
  }}

  img {{
    display: block;
    width: 100%;
    height: 280px;
    object-fit: contain;
    background: #000;
    border-radius: 8px;
  }}

  h2 {{
    font-size: 1.05rem;
    line-height: 1.35;
  }}

  dl {{
    display: grid;
    grid-template-columns: 80px 1fr;
    gap: 0.35rem 0.6rem;
  }}

  dt {{
    font-weight: bold;
    color: #bbbbbb;
  }}

  dd {{
    margin: 0;
  }}

  .description {{
    color: #cccccc;
    line-height: 1.4;
  }}

  a {{
    color: #8cc8ff;
  }}

  .copy-button {{
    padding: 0.65rem 0.9rem;
    border: 0;
    border-radius: 7px;
    background: #2d7d46;
    color: white;
    font-weight: bold;
    cursor: pointer;
  }}

  .copy-button:hover {{
    background: #359653;
  }}

  pre {{
    overflow-x: auto;
    white-space: pre-wrap;
    padding: 0.75rem;
    background: #111;
    color: #d7ffd7;
    border-radius: 6px;
  }}
</style>
</head>
<body>
<h1>{escape(artist_name)} — Artist Photo Research</h1>

<p class="summary">
  {len(records)} usable unique candidates.
  {len(approved_urls)} previously approved.
  {rejected_count} results rejected for size, format, or license.
  {identity_review_count} identity-mismatched results hidden.
  No candidate is downloaded from this page.
</p>

<div class="source-links">
  {picryl_links}
</div>

<div class="grid">
  {"".join(cards)}
</div>

<script>
function copyCommand(button) {{
  const command = button.dataset.command;
  const textarea = document.createElement("textarea");

  textarea.value = command;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";

  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);

  const originalText = button.textContent;
  button.textContent = "Copied!";

  setTimeout(() => {{
    button.textContent = originalText;
  }}, 1500);
}}
</script>

</body>
</html>
"""

    output_directory = WORK_ROOT / artist_slug
    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = output_directory / "review.html"
    destination.write_text(
        page,
        encoding="utf-8",
    )

    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a visual Wikimedia and PICRYL research "
            "page for one premium artist."
        )
    )
    parser.add_argument(
        "--artist-id",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--query",
        action="append",
        help=(
            "Custom search query. Repeat for multiple queries. "
            "Defaults to five standard artist searches."
        ),
    )

    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(
            encoding="utf-8",
            errors="replace",
        )

    args = parse_args()
    artist = load_artist(args.artist_id)

    queries = (
        args.query
        if args.query
        else default_queries(
            artist.artist_name.strip()
        )
    )

    destination = build_page(
        artist_id=args.artist_id,
        queries=queries,
        limit=args.limit,
    )

    print()
    print(f"Review page: {destination}")


if __name__ == "__main__":
    main()