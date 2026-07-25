from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Decade, Genre, DecadeGenre, TrackRanking

OUTPUT_DIR = Path("backend/scripts/catalogs/output")

DECADE_ORDER = ["1950s", "1960s", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s"]


def generate_nostalgia_library_index() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    decade_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"programs": 0, "tracks": 0})

    with Session(engine) as session:
        rows = session.exec(
            select(
                Decade.decade_name,
                Decade.slug,
                Decade.description,
                DecadeGenre.id,
            )
            .join(DecadeGenre, DecadeGenre.decade_id == Decade.id)
        ).all()

        for decade_name, decade_slug, decade_description, decade_genre_id in rows:
            track_count = len(
                session.exec(
                    select(TrackRanking.id)
                    .where(TrackRanking.decade_genre_id == decade_genre_id)
                ).all()
            )

            decade_counts[decade_name]["programs"] += 1
            decade_counts[decade_name]["tracks"] += track_count
            decade_counts[decade_name]["description"] = decade_description or ""
            decade_counts[decade_name]["slug"] = decade_slug or decade_name

    total_programs = sum(item["programs"] for item in decade_counts.values())
    total_tracks = sum(item["tracks"] for item in decade_counts.values())

    decade_cards = []

    for decade_name in DECADE_ORDER:
        item = decade_counts.get(decade_name)

        if not item:
            continue

        decade_cards.append(
            f"""
            <div class="decade-card">
                <h2>
                    <a href="nostalgia/{html.escape(item["slug"])}.html">
                        {html.escape(decade_name)}
                    </a>
                </h2>
                <p>{html.escape(item.get("description", "") or "A decade of TopSpot40 nostalgia programs organized by genre.")}</p>
                <div class="stats">
                    {item["programs"]} programs • {item["tracks"]} tracks
                </div>
            </div>
            """
        )

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Nostalgia Library - TopSpot40 Catalog</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 32px auto;
            max-width: 1100px;
            padding: 0 24px;
        }}

        .nav {{
            margin-bottom: 24px;
            font-size: 15px;
        }}

        .nav a {{
            color: #0645ad;
            text-decoration: none;
            margin-right: 14px;
        }}

        h1 {{
            font-size: 46px;
            margin-bottom: 8px;
            text-transform: uppercase;
        }}

        .subtitle {{
            font-size: 19px;
            line-height: 1.4;
            max-width: 900px;
            color: #333;
            margin-bottom: 24px;
        }}

        .summary {{
            font-size: 18px;
            font-weight: bold;
            margin-bottom: 30px;
        }}

        .decade-card {{
            border-top: 1px solid #ccc;
            padding: 18px 0;
        }}

        .decade-card h2 {{
            font-size: 28px;
            margin: 0 0 6px 0;
        }}

        .decade-card h2 a {{
            color: #111;
            text-decoration: none;
        }}

        .decade-card h2 a:hover {{
            text-decoration: underline;
        }}

        .decade-card p {{
            font-size: 16px;
            line-height: 1.35;
            margin: 6px 0;
        }}

        .stats {{
            font-weight: bold;
            margin-top: 8px;
        }}

        .footer {{
            margin-top: 40px;
            border-top: 1px solid #ccc;
            padding-top: 14px;
            color: #555;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="nav">
        <a href="index.html">TopSpot40 Catalog</a>
    </div>

    <h1>Nostalgia Library</h1>

    <div class="subtitle">
        Explore TopSpot40 nostalgia programs organized by decade and genre,
        from the 1950s through the 2020s.
    </div>

    <div class="summary">
        {len(decade_cards)} decades • {total_programs} programs • {total_tracks} tracks
    </div>

    {"".join(decade_cards)}

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "nostalgia_index.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_nostalgia_library_index()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()