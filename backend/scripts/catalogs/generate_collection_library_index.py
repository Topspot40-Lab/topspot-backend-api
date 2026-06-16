from __future__ import annotations

import html
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import (
    Collection,
    CollectionCategory,
    CollectionTrackRanking,
)

OUTPUT_DIR = Path("backend/scripts/catalogs/output")


def generate_collection_library_index() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        categories = session.exec(
            select(CollectionCategory)
            .order_by(CollectionCategory.sort_order, CollectionCategory.name)
        ).all()

        group_cards = []
        total_collections = 0
        total_tracks = 0

        for category in categories:
            collections = session.exec(
                select(Collection)
                .where(Collection.category_id == category.id)
                .order_by(Collection.name)
            ).all()

            collection_ids = [collection.id for collection in collections]
            track_count = 0

            if collection_ids:
                track_count = len(
                    session.exec(
                        select(CollectionTrackRanking.id)
                        .where(CollectionTrackRanking.collection_id.in_(collection_ids))
                    ).all()
                )

            total_collections += len(collections)
            total_tracks += track_count

            special_note = ""
            if category.slug == "music_legends":
                special_note = """
                <div class="special-note">
                    Music Legends collections feature one defining recording from each artist,
                    creating a survey of influential performers across major TopSpot genres.
                </div>
                """

            group_cards.append(
                f"""
                <div class="group-card">
                    <h2>
                        <a href="collection-groups/{html.escape(category.slug)}.html">
                            {html.escape(category.name)}
                        </a>
                    </h2>
                    <p>{html.escape(category.intro or "")}</p>
                    <div class="stats">
                        {len(collections)} collections • {track_count} tracks
                    </div>
                    {special_note}
                </div>
                """
            )

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Collection Library - TopSpot40 Catalog</title>
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

        .group-card {{
            border-top: 1px solid #ccc;
            padding: 18px 0;
        }}

        .group-card h2 {{
            font-size: 28px;
            margin: 0 0 6px 0;
        }}

        .group-card h2 a {{
            color: #111;
            text-decoration: none;
        }}

        .group-card h2 a:hover {{
            text-decoration: underline;
        }}

        .group-card p {{
            font-size: 16px;
            line-height: 1.35;
            margin: 6px 0;
        }}

        .stats {{
            font-weight: bold;
            margin-top: 8px;
        }}

        .special-note {{
            margin-top: 10px;
            padding: 10px 12px;
            background: #f4f4f4;
            border-left: 4px solid #777;
            font-size: 15px;
            line-height: 1.35;
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

    <h1>Collection Library</h1>

    <div class="subtitle">
        Explore curated TopSpot40 collections organized by heritage, tradition,
        musical trends, legendary artists, stage and screen favorites, classical music,
        and specialty listening experiences.
    </div>

    <div class="summary">
        {len(categories)} collection groups • {total_collections} collections • {total_tracks} tracks
    </div>

    {"".join(group_cards)}

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "collections_index.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_collection_library_index()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()