from __future__ import annotations

import html
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine

OUTPUT_DIR = Path("backend/scripts/catalogs/output/artists")

GENRES = [
    ("country", "Country"),
    ("pop", "Pop"),
    ("rock", "Rock"),
    ("rnb_soul", "R&B Soul"),
    ("latin_global", "Latin Global"),
    ("blues_jazz", "Blues Jazz"),
    ("folk_acoustic", "Folk Acoustic"),
]


def generate_featured_artist_index() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        rows = session.exec(text("""
            select
                g.slug,
                count(distinct ag.artist_id) as artist_count
            from artist_genre ag
            join genre g on g.id = ag.genre_id
            join artist_story ast on ast.artist_id = ag.artist_id
            where ast.language_code = 'en'
              and ast.tts_key is not null
              and g.slug <> 'tv_themes'
            group by g.slug
        """)).all()

        story_stats = session.exec(text("""
            select
                count(distinct artist_id) as artist_count,
                sum(duration_seconds) as total_seconds,
                avg(duration_seconds) as avg_seconds
            from artist_story
            where language_code = 'en'
              and tts_key is not null
        """)).first()

    count_by_genre = {slug: count for slug, count in rows}

    unique_artists = story_stats.artist_count or 0
    total_hours = (story_stats.total_seconds or 0) / 3600
    avg_minutes = (story_stats.avg_seconds or 0) / 60

    cards = []

    for slug, name in GENRES:
        count = count_by_genre.get(slug, 0)

        cards.append(
            f"""
            <div class="genre-card">
                <h2>
                    <a href="{html.escape(slug)}.html">{html.escape(name)}</a>
                </h2>
                <p>Explore featured TopSpot artists with artist stories and curated tracks in {html.escape(name)}.</p>
                <div class="stats">
                    {count} featured artists
                </div>
            </div>
            """
        )

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Featured Artists - TopSpot40 Catalog</title>
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

        .genre-card {{
            border-top: 1px solid #ccc;
            padding: 18px 0;
        }}

        .genre-card h2 {{
            font-size: 28px;
            margin: 0 0 6px 0;
        }}

        .genre-card h2 a {{
            color: #111;
            text-decoration: none;
        }}

        .genre-card h2 a:hover {{
            text-decoration: underline;
        }}

        .genre-card p {{
            font-size: 16px;
            line-height: 1.35;
            margin: 6px 0;
        }}

        .stats {{
            font-weight: bold;
            margin-top: 8px;
        }}

        .note {{
            margin-top: 24px;
            padding: 12px 14px;
            background: #f4f4f4;
            border-left: 4px solid #777;
            font-size: 15px;
            line-height: 1.4;
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
    </div>

    <h1>Featured Artists</h1>

    <div class="subtitle">
        Explore TopSpot40 featured artists organized by genre. Featured artists have
        narrated artist stories and curated TopSpot track appearances.
    </div>

    <div class="summary">
        {unique_artists} featured artists • {total_hours:.1f} hours of narrated artist stories • {avg_minutes:.1f} min average story
    </div>

    {"".join(cards)}

    <div class="note">
        TV Themes are handled separately because they are usually organized by show,
        theme, composer, or performer rather than by featured artist.
    </div>

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "index.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_featured_artist_index()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()
