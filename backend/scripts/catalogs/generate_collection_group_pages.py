from __future__ import annotations

import html
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import Collection, CollectionCategory

OUTPUT_DIR = Path("backend/scripts/catalogs/output/collection-groups")


def generate_group_pages() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []

    with Session(engine) as session:
        categories = session.exec(
            select(CollectionCategory)
            .order_by(CollectionCategory.sort_order, CollectionCategory.name)
        ).all()

        for category in categories:
            collections = session.exec(
                select(Collection)
                .where(Collection.category_id == category.id)
                .order_by(Collection.name)
            ).all()

            items = "\n".join(
                f"""
                <li class="collection-item">
                    <a href="../collections/{html.escape(collection.slug)}.html">
                        {html.escape(collection.name)}
                    </a>
                    <p>{html.escape(collection.intro or "")}</p>
                </li>
                """
                for collection in collections
            )

            page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>{html.escape(category.name)} - TopSpot40 Catalog</title>
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
            font-size: 44px;
            margin-bottom: 8px;
            text-transform: uppercase;
        }}

        .description {{
            font-size: 19px;
            line-height: 1.4;
            max-width: 900px;
            margin-bottom: 24px;
        }}

        .count {{
            font-weight: bold;
            margin-bottom: 24px;
        }}

        ul {{
            list-style: none;
            padding-left: 0;
        }}

        .collection-item {{
            border-top: 1px solid #ccc;
            padding: 16px 0;
        }}

        .collection-item a {{
            font-size: 24px;
            font-weight: bold;
            color: #111;
            text-decoration: none;
        }}

        .collection-item a:hover {{
            text-decoration: underline;
        }}

        .collection-item p {{
            font-size: 16px;
            line-height: 1.35;
            margin-top: 6px;
            color: #333;
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
        <a href="../collections_index.html">Collection Library</a>
    </div>

    <h1>{html.escape(category.name)}</h1>

    <div class="description">
        {html.escape(category.intro or "")}
    </div>

    <div class="count">
        {len(collections)} collection(s)
    </div>

    <ul>
        {items}
    </ul>

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

            output_path = OUTPUT_DIR / f"{category.slug}.html"
            output_path.write_text(page, encoding="utf-8")
            created.append(output_path)
            print(f"Created: {output_path}")

    return created


def main() -> None:
    pages = generate_group_pages()
    print()
    print(f"Done. Generated {len(pages)} collection group page(s).")


if __name__ == "__main__":
    main()