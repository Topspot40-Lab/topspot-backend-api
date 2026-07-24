from __future__ import annotations

import argparse
import html
from collections import Counter
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Decade, Genre, DecadeGenre, Track, TrackRanking, Artist

OUTPUT_DIR = Path("backend/scripts/catalogs/output/nostalgia")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an HTML catalog page for one TopSpot40 nostalgia decade-genre program."
    )
    parser.add_argument(
        "--slug",
        default="1950s-country",
        help="Decade-genre slug to generate, such as 1950s_country.",
    )
    return parser.parse_args()


def generate_decade_genre_page(slug: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        decade_genre = session.exec(
            select(DecadeGenre).where(DecadeGenre.slug == slug)
        ).first()

        if not decade_genre:
            raise SystemExit(f"DecadeGenre not found: {slug}")

        decade = session.get(Decade, decade_genre.decade_id)
        genre = session.get(Genre, decade_genre.genre_id)

        rows = session.exec(
            select(
                TrackRanking.ranking,
                Track.track_name,
                Track.artist_display_name,
                Artist.artist_name,
                Track.year_released,
            )
            .join(Track, TrackRanking.track_id == Track.id)
            .join(Artist, Track.artist_id == Artist.id)
            .where(TrackRanking.decade_genre_id == decade_genre.id)
            .order_by(TrackRanking.ranking)
        ).all()

    artist_counts = Counter(
        artist_display_name or artist_name or "Unknown Artist"
        for _, _, artist_display_name, artist_name, _ in rows
    )

    featured_artists = artist_counts.most_common(8)

    years = [
        year
        for _, _, _, _, year in rows
        if year
    ]

    year_range = ""
    if years:
        year_range = f" • {min(years)}–{max(years)}"


    tracks_html = "\n".join(
        f"<li><span class='track-title'>{html.escape(track_name)}</span> "
        f"<span class='artist-name'>— {html.escape(artist_display_name or artist_name or 'Unknown Artist')}</span></li>"
        for _, track_name, artist_display_name, artist_name, _ in rows
    )

    featured_html = "\n".join(
        f"<span class='featured-artist'>{html.escape(artist)} ({count})</span>"
        for artist, count in featured_artists
    )

    title = f"{decade.decade_name} {genre.genre_name}"
    artist_total = len(artist_counts)
    track_total = len(rows)

    description = genre.description or f"A TopSpot40 nostalgia program featuring {title} favorites."

    output_path = OUTPUT_DIR / f"{decade_genre.slug}.html"

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>{html.escape(title)} - TopSpot40 Catalog</title>

<style>
    body {{
        font-family: Arial, sans-serif;
        margin: 24px auto;
        max-width: 1500px;
        padding: 0 20px;
    }}

    .nav {{
        margin-bottom: 18px;
        font-size: 15px;
    }}

    .nav a {{
        color: #0645ad;
        text-decoration: none;
        margin-right: 14px;
    }}

    .program-line {{
        font-size: 18px;
        font-weight: bold;
        color: #555;
        margin-bottom: 12px;
    }}

    .program-name {{
        font-size: 42px;
        font-weight: bold;
        margin-bottom: 10px;
        text-transform: uppercase;
    }}

    .stats {{
        font-size: 18px;
        font-weight: bold;
        margin-bottom: 16px;
    }}

    .description {{
        font-size: 16px;
        line-height: 1.35;
        max-width: 1200px;
        margin-bottom: 18px;
    }}

    h3 {{
        margin-bottom: 8px;
    }}

    .featured-artists-line {{
        font-size: 15px;
        line-height: 1.4;
        margin-bottom: 20px;
    }}

    .featured-artist::after {{
        content: " • ";
        color: #888;
    }}

    .featured-artist:last-child::after {{
        content: "";
    }}

    .track-list {{
        columns: 2;
        column-gap: 48px;
        font-size: 15px;
        line-height: 1.25;
    }}

    .track-list li {{
        break-inside: avoid;
        margin-bottom: 2px;
    }}

    .track-title {{
        font-weight: bold;
    }}

    .artist-name {{
        color: #333;
    }}

    @media print {{
        body {{
            margin: 0.15in;
            max-width: none;
            padding: 0;
        }}

        .nav {{
            display: none;
        }}

        .program-line {{
            font-size: 16px;
            margin-bottom: 8px;
        }}

        .program-name {{
            font-size: 36px;
            margin-bottom: 8px;
        }}

        .stats {{
            font-size: 15px;
            margin-bottom: 8px;
        }}

        .description {{
            font-size: 12px;
            line-height: 1.15;
            margin-bottom: 8px;
        }}

        .featured-artists-line {{
            font-size: 14px;
        }}

        .track-list {{
            font-size: 14px;
            line-height: 1.1;
            column-gap: 40px;
        }}

        h3 {{
            margin-top: 6px;
            margin-bottom: 4px;
        }}
    }}
</style>
</head>
<body>

<div class="nav">
    <a href="../index.html">TopSpot40 Catalog</a>
    <a href="../nostalgia_index.html">Nostalgia Library</a>
    <a href="{html.escape(decade.slug or decade.decade_name)}.html">{html.escape(decade.decade_name)}</a>
</div>

<div class="program-line">
    Nostalgia Program: {html.escape(decade.decade_name)} / {html.escape(genre.genre_name)}
</div>

<div class="program-name">
    {html.escape(title).upper()}
</div>

<div class="stats">
    {track_total} tracks • {artist_total} artists{year_range}
</div>

<p class="description">{html.escape(description)}</p>

<h3>Top Artists in This Program</h3>
<div class="featured-artists-line">
    {featured_html}
</div>

<h3>Track List</h3>
<ol class="track-list">
    {tracks_html}
</ol>

</body>
</html>
"""

    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    args = parse_args()
    output_path = generate_decade_genre_page(args.slug)
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()