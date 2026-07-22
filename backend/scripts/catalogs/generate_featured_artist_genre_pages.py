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


def format_minutes(seconds: int | None) -> str:
    if not seconds:
        return ""
    minutes = round(seconds / 60)
    return f"{minutes} min story"


def generate_artist_genre_page(genre_slug: str, genre_name: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        with Session(engine) as session:
            stmt = text("""
                select
                    a.id as artist_id,
                    a.artist_name,
                    ast.duration_seconds,
                    count(distinct t.id) as track_count
                from artist a
                join artist_genre ag on ag.artist_id = a.id
                join genre g on g.id = ag.genre_id
                join artist_story ast on ast.artist_id = a.id
                left join track t on t.artist_id = a.id
                where g.slug = :genre_slug
                  and ast.language_code = 'en'
                  and ast.tts_key is not null
                group by a.id, a.artist_name, ast.duration_seconds
                order by lower(a.artist_name)
            """).bindparams(genre_slug=genre_slug)

            rows = session.exec(stmt).all()

    total_artists = len(rows)
    total_seconds = sum(duration_seconds or 0 for _, _, duration_seconds, _ in rows)
    total_hours = total_seconds / 3600 if total_seconds else 0
    avg_minutes = (total_seconds / total_artists / 60) if total_artists else 0

    artist_items = []

    for artist_id, artist_name, duration_seconds, track_count in rows:
        story_text = format_minutes(duration_seconds)

        stats_parts = [f"{track_count} TopSpot tracks"]
        if story_text:
            stats_parts.append(story_text)

        artist_items.append(
            f"""
            <li class="artist-item">
                <a href="{artist_id}.html">{html.escape(artist_name.title())}</a>
                <div class="artist-stats">
                    {" • ".join(stats_parts)}
                </div>
            </li>
            """
        )

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>{html.escape(genre_name)} Featured Artists - TopSpot40 Catalog</title>
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

        .artist-list {{
            columns: 2;
            column-gap: 48px;
            list-style: none;
            padding-left: 0;
        }}

        .artist-item {{
            break-inside: avoid;
            border-top: 1px solid #ccc;
            padding: 10px 0;
        }}

        .artist-item a {{
            font-size: 20px;
            font-weight: bold;
            color: #111;
            text-decoration: none;
        }}

        .artist-item a:hover {{
            text-decoration: underline;
        }}

        .artist-stats {{
            font-size: 14px;
            color: #555;
            margin-top: 4px;
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
        <a href="index.html">Featured Artists</a>
    </div>

    <h1>{html.escape(genre_name)} Featured Artists</h1>

    <div class="subtitle">
        Featured TopSpot artists in {html.escape(genre_name)} with narrated artist stories
        and curated TopSpot track appearances.
    </div>

    <div class="summary">
        {total_artists} featured artists • {total_hours:.1f} hours of artist stories • {avg_minutes:.1f} min average story
    </div>

    <ul class="artist-list">
        {"".join(artist_items)}
    </ul>

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

    output_path = OUTPUT_DIR / f"{genre_slug}.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    generated = 0

    for slug, name in GENRES:
        output_path = generate_artist_genre_page(slug, name)
        print(f"Created: {output_path}")
        generated += 1

    print()
    print(f"Done. Generated {generated} featured artist genre page(s).")


if __name__ == "__main__":
    main()