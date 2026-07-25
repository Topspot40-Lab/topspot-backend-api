from __future__ import annotations

import html
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Decade, Genre, DecadeGenre, TrackRanking

OUTPUT_DIR = Path("backend/scripts/catalogs/output/nostalgia")

DECADE_ORDER = ["1950s", "1960s", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s"]
GENRE_ORDER = ["country", "pop", "rock", "rnb_soul", "latin_global", "blues_jazz", "folk_acoustic", "tv_themes"]


def generate_decade_pages() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []

    with Session(engine) as session:
        decades = session.exec(select(Decade)).all()
        genres = session.exec(select(Genre)).all()

        decade_by_name = {d.decade_name: d for d in decades}
        genre_by_slug = {g.slug: g for g in genres}

        for decade_name in DECADE_ORDER:
            decade = decade_by_name.get(decade_name)

            if not decade:
                continue

            program_cards = []
            total_tracks = 0
            program_count = 0

            for genre_slug in GENRE_ORDER:
                genre = genre_by_slug.get(genre_slug)

                if not genre:
                    continue

                decade_genre = session.exec(
                    select(DecadeGenre)
                    .where(DecadeGenre.decade_id == decade.id)
                    .where(DecadeGenre.genre_id == genre.id)
                ).first()

                if not decade_genre:
                    continue

                track_count = len(
                    session.exec(
                        select(TrackRanking.id)
                        .where(TrackRanking.decade_genre_id == decade_genre.id)
                    ).all()
                )

                total_tracks += track_count
                program_count += 1

                program_cards.append(
                    f"""
                    <div class="program-card">
                        <h2>
                            <a href="{html.escape(decade_genre.slug or '')}.html">
                                {html.escape(decade.decade_name)} {html.escape(genre.genre_name)}
                            </a>
                        </h2>
                        <p>{html.escape(genre.description or "A TopSpot40 nostalgia program organized by genre.")}</p>
                        <div class="stats">
                            {track_count} tracks
                        </div>
                    </div>
                    """
                )

            page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>{html.escape(decade.decade_name)} - TopSpot40 Catalog</title>
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

        .program-card {{
            border-top: 1px solid #ccc;
            padding: 18px 0;
        }}

        .program-card h2 {{
            font-size: 28px;
            margin: 0 0 6px 0;
        }}

        .program-card h2 a {{
            color: #111;
            text-decoration: none;
        }}

        .program-card h2 a:hover {{
            text-decoration: underline;
        }}

        .program-card p {{
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
        <a href="../index.html">TopSpot40 Catalog</a>
        <a href="../nostalgia_index.html">Nostalgia Library</a>
    </div>

    <h1>{html.escape(decade.decade_name)}</h1>

    <div class="subtitle">
        {html.escape(decade.description or "A decade of TopSpot40 nostalgia programs organized by genre.")}
    </div>

    <div class="summary">
        {program_count} programs • {total_tracks} tracks
    </div>

    {"".join(program_cards)}

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

            output_path = OUTPUT_DIR / f"{decade.slug or decade.decade_name}.html"
            output_path.write_text(page, encoding="utf-8")
            created.append(output_path)
            print(f"Created: {output_path}")

    return created


def main() -> None:
    pages = generate_decade_pages()
    print()
    print(f"Done. Generated {len(pages)} decade page(s).")


if __name__ == "__main__":
    main()