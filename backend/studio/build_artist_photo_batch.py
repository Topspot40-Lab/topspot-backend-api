from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from backend.studio.build_artist_photo_review_page import (
    WORK_ROOT,
    approved_page_urls,
    build_page,
    default_queries,
)
from backend.studio.create_historical_directories import (
    load_premium_artists,
)
from backend.studio.documentary import slugify


REFRESH_CHECKPOINT = WORK_ROOT / "refresh_checkpoint.txt"


SUMMARY_PATTERN = re.compile(
    r"(\d+) usable unique candidates\.\s*"
    r"(\d+) previously approved\.\s*"
    r"(\d+) results rejected[^.]*\.\s*"
    r"(\d+) identity-mismatched results hidden\.",
    re.DOTALL,
)


@dataclass(frozen=True)
class ReviewSummary:
    usable: int = 0
    approved: int = 0
    rejected: int = 0
    hidden: int = 0
    eligible: int = 0
    review: int = 0

    @property
    def status(self) -> str:
        if self.approved:
            return "APPROVED"
        if self.eligible:
            return "READY"
        if self.review or self.usable:
            return "REVIEW / AI FALLBACK"
        return "NO PHOTO / AI FALLBACK"


def read_summary(path: Path) -> ReviewSummary:
    if not path.exists():
        return ReviewSummary()

    text = path.read_text(encoding="utf-8")
    match = SUMMARY_PATTERN.search(text)

    if not match:
        return ReviewSummary()

    usable, approved, rejected, hidden = (
        int(value) for value in match.groups()
    )

    return ReviewSummary(
        usable=usable,
        approved=approved,
        rejected=rejected,
        hidden=hidden,
        eligible=text.count('class="status eligible"'),
        review=text.count('class="status review"'),
    )


def build_index(artists) -> Path:
    rows: list[str] = []

    for artist in artists:
        name = artist.artist_name.strip()
        slug = slugify(name)
        page = WORK_ROOT / slug / "review.html"
        summary = read_summary(page)
        summary = replace(
            summary,
            approved=len(approved_page_urls(slug)),
        )
        status_class = summary.status.split()[0].casefold()

        if page.exists():
            link = f'{slug}/review.html'
            name_cell = (
                f'<a href="{html.escape(link)}">'
                f'{html.escape(name)}</a>'
            )
        else:
            name_cell = html.escape(name)

        rows.append(
            "<tr>"
            f"<td>{artist.id}</td>"
            f"<td>{name_cell}</td>"
            f'<td class="{status_class}">'
            f"{html.escape(summary.status)}</td>"
            f"<td>{summary.usable}</td>"
            f"<td>{summary.eligible}</td>"
            f"<td>{summary.approved}</td>"
            f"<td>{summary.rejected}</td>"
            f"<td>{summary.hidden}</td>"
            "</tr>"
        )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TopSpot Artist Photo Research</title>
<style>
body {{
  margin: 0;
  padding: 2rem;
  background: #171717;
  color: #f3f3f3;
  font-family: Arial, sans-serif;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  background: #242424;
}}
th, td {{
  padding: 0.65rem;
  border-bottom: 1px solid #444;
  text-align: left;
}}
th {{ position: sticky; top: 0; background: #111; }}
a {{ color: #8cc8ff; }}
.approved {{ color: #72df91; font-weight: bold; }}
.ready {{ color: #8cc8ff; font-weight: bold; }}
.review {{ color: #f1c75b; font-weight: bold; }}
.no {{ color: #bbbbbb; font-weight: bold; }}
</style>
</head>
<body>
<h1>TopSpot40 Artist Photo Research</h1>
<p>{len(artists)} premium artists. Research pages only; nothing is approved automatically.</p>
<table>
<thead>
<tr>
<th>ID</th><th>Artist</th><th>Status</th><th>Usable</th>
<th>Eligible</th><th>Approved</th><th>Rejected</th><th>Hidden</th>
</tr>
</thead>
<tbody>{''.join(rows)}</tbody>
</table>
</body>
</html>
"""

    destination = WORK_ROOT / "index.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding="utf-8")
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build ranked photo research pages in resumable batches."
    )
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--results-per-query", type=int, default=15)
    parser.add_argument("--start-after", default="")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Rebuild all pages, resuming from the refresh checkpoint.",
    )
    parser.add_argument(
        "--restart-refresh",
        action="store_true",
        help="Discard an existing checkpoint and restart the refresh.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    artists = load_premium_artists()
    pending = artists

    if args.restart_refresh and not args.refresh:
        raise SystemExit("--restart-refresh requires --refresh")

    if args.restart_refresh and REFRESH_CHECKPOINT.exists():
        REFRESH_CHECKPOINT.unlink()

    checkpoint_name = ""

    if args.refresh and REFRESH_CHECKPOINT.exists():
        checkpoint_name = REFRESH_CHECKPOINT.read_text(
            encoding="utf-8"
        ).strip()

    start_after = args.start_after or checkpoint_name

    if start_after:
        marker = start_after.casefold().strip()
        pending = [
            artist
            for artist in pending
            if artist.artist_name.casefold().strip() > marker
        ]

    if not args.refresh:
        pending = [
            artist
            for artist in pending
            if not (
                WORK_ROOT
                / slugify(artist.artist_name.strip())
                / "review.html"
            ).exists()
        ]

    selected = pending[: max(args.batch_size, 0)]

    print()
    print("TOPSPOT STUDIO — ARTIST PHOTO BATCH")
    print("=" * 70)
    print(f"Premium artists: {len(artists)}")
    print(f"Pending:         {len(pending)}")
    print(f"This batch:      {len(selected)}")

    if checkpoint_name:
        print(f"Resuming after:  {checkpoint_name}")

    print()

    completed = 0
    failed = 0

    for number, artist in enumerate(selected, start=1):
        name = artist.artist_name.strip()
        print(f"[{number}/{len(selected)}] {name} (ID {artist.id})")

        try:
            build_page(
                artist_id=artist.id,
                queries=default_queries(name),
                limit=args.results_per_query,
            )
            completed += 1

            if args.refresh:
                REFRESH_CHECKPOINT.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                REFRESH_CHECKPOINT.write_text(
                    name,
                    encoding="utf-8",
                )
        except Exception as exc:
            failed += 1
            print(f"FAILED: {type(exc).__name__}: {exc}")

            if args.refresh:
                print(
                    "Refresh stopped. Run the same command "
                    "to resume from the checkpoint."
                )
                break

    index = build_index(artists)

    print()
    print("=" * 70)
    print(f"Completed: {completed}")
    print(f"Failed:    {failed}")
    print(f"Dashboard: {index}")

    refresh_finished = (
        args.refresh
        and failed == 0
        and completed == len(pending)
    )

    if refresh_finished and REFRESH_CHECKPOINT.exists():
        REFRESH_CHECKPOINT.unlink()
        print("Refresh:   complete; checkpoint removed")
    elif args.refresh and REFRESH_CHECKPOINT.exists():
        checkpoint = REFRESH_CHECKPOINT.read_text(
            encoding="utf-8"
        ).strip()
        print(f"Checkpoint: {checkpoint}")


if __name__ == "__main__":
    main()