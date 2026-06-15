from __future__ import annotations

import argparse
import html
from collections import Counter
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import (
    Collection,
    CollectionCategory,
    CollectionTrackRanking,
)
from backend.models.dbmodels import Track, Artist

OUTPUT_DIR = Path("backend/scripts/catalogs/output")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a simple HTML catalog page for one TopSpot40 collection."
    )
    parser.add_argument(
        "--slug",
        default="railroad_train_songs",
        help="Collection slug to generate.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        collection = session.exec(
            select(Collection).where(Collection.slug == args.slug)
        ).first()

        if not collection:
            raise SystemExit(f"Collection not found: {args.slug}")

        category_name = "Uncategorized"
        if collection.category_id:
            category = session.get(CollectionCategory, collection.category_id)
            if category:
                category_name = category.name

        rows = session.exec(
            select(
                CollectionTrackRanking.ranking,
                Track.track_name,
                Track.artist_display_name,
                Artist.artist_name,
            )
            .join(Track, CollectionTrackRanking.track_id == Track.id)
            .join(Artist, Track.artist_id == Artist.id)
            .where(CollectionTrackRanking.collection_id == collection.id)
            .order_by(CollectionTrackRanking.ranking)
        ).all()

    artist_counts = Counter(
        artist_display_name or artist_name or "Unknown Artist"
        for _, _, artist_display_name, artist_name in rows
    )
    featured_artists = artist_counts.most_common(8)

    tracks_html = "\n".join(
        f"<li><span class='track-title'>{html.escape(track_name)}</span> "
        f"<span class='artist-name'>— {html.escape(artist_display_name or artist_name or 'Unknown Artist')}</span></li>"
        for ranking, track_name, artist_display_name, artist_name in rows
    )

    featured_html = "\n".join(
        f"<span class='featured-artist'>{html.escape(artist)} ({count})</span>"
        for artist, count in featured_artists
    )

    output_path = OUTPUT_DIR / f"{collection.slug}.html"

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>{html.escape(collection.name)} - TopSpot40 Catalog</title>
    
<style>
    body {{
        font-family: Arial, sans-serif;
        margin: 24px auto;
        max-width: 1500px;
        padding: 0 20px;
    }}

    .group-line {{
        font-size: 18px;
        font-weight: bold;
        color: #555;
        margin-bottom: 12px;
    }}

    .collection-name {{
        font-size: 42px;
        font-weight: bold;
        margin-bottom: 16px;
        text-transform: uppercase;
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
            margin: 0.25in;
            max-width: none;
            padding: 0;
        }}

        .group-line {{
            font-size: 16px;
            margin-bottom: 8px;
        }}

        .collection-name {{
            font-size: 36px;
            margin-bottom: 10px;
        }}

        .description {{
            font-size: 13px;
            margin-bottom: 8px;
        }}

        .featured-artists-line {{
            font-size: 14px;
        }}

        .track-list {{
            font-size: 15px;
            line-height: 1.2;
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

<div class="group-line">
    Collection Group: {html.escape(category_name)}
</div>

<div class="collection-name">
    {html.escape(collection.name).upper()}
</div>

    <p class="description">{html.escape(collection.intro or "")}</p>

    <h3>Featured Artists</h3>
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
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()
