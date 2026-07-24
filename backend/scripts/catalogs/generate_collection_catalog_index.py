from __future__ import annotations

import html
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import Collection, CollectionCategory

OUTPUT_DIR = Path("backend/scripts/catalogs/output")


def generate_collection_index() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        rows = session.exec(
            select(
                CollectionCategory.sort_order,
                CollectionCategory.name,
                Collection.slug,
                Collection.name,
            )
            .join(Collection, Collection.category_id == CollectionCategory.id)
            .order_by(
                CollectionCategory.sort_order,
                CollectionCategory.name,
                Collection.name,
            )
        ).all()

    sections = []
    current_group = None

    for _, group_name, slug, collection_name in rows:
        if group_name != current_group:
            if current_group is not None:
                sections.append("</ul>")
            current_group = group_name
            sections.append(f"<h2>{html.escape(group_name)}</h2>")
            sections.append("<ul>")

        sections.append(
            f'<li><a href="{html.escape(slug)}.html">{html.escape(collection_name)}</a></li>'
        )

    if current_group is not None:
        sections.append("</ul>")

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>TopSpot40 Collection Catalog</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 32px auto;
            max-width: 1000px;
            padding: 0 24px;
        }}

        h1 {{
            font-size: 42px;
            margin-bottom: 4px;
        }}

        .subtitle {{
            font-size: 18px;
            color: #555;
            margin-bottom: 28px;
        }}

        h2 {{
            border-bottom: 1px solid #ccc;
            padding-bottom: 4px;
            margin-top: 28px;
        }}

        li {{
            font-size: 18px;
            margin-bottom: 8px;
        }}

        a {{
            color: #0645ad;
            text-decoration: none;
        }}

        a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <h1>TopSpot40 Collection Catalog</h1>
    <div class="subtitle">Printable collection sheets grouped by music category</div>

    {"".join(sections)}
</body>
</html>
"""

    output_path = OUTPUT_DIR / "index.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_collection_index()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()
