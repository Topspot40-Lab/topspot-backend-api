from __future__ import annotations

import re
from pathlib import Path

OUTPUT_DIR = Path("backend/scripts/catalogs/output")
MASTER_OUTPUT = OUTPUT_DIR / "master_catalog.html"


FRONT_PAGES = [
    "cover.html",
    "welcome.html",
    "table_of_contents.html",
    "about_topspot40.html",
    "at_a_glance.html",
    "why_topspot40_is_different.html",
    "four_ways_to_listen.html",
    "using_topspot40.html",
    "listening_experience.html",
    "vision_for_topspot40.html",
    "artists/index.html",
    "bb_king_artist_story.html",
    "nostalgia_index.html",
]

MIDDLE_PAGES = [
    "collections_index.html",
]

END_PAGES = [
    "invitation_to_discover.html",
]


def extract_body(html_text: str) -> str:
    match = re.search(r"<body[^>]*>(.*?)</body>", html_text, flags=re.S | re.I)
    if not match:
        return html_text
    return match.group(1).strip()


def read_page(relative_path: str) -> str:
    path = OUTPUT_DIR / relative_path
    if not path.exists():
        print(f"WARNING: missing page: {path}")
        return f"<h1>Missing page: {relative_path}</h1>"

    html_text = path.read_text(encoding="utf-8")
    body = extract_body(html_text)

    return f"""
<section class="catalog-page" data-source="{relative_path}">
{body}
</section>
"""


def nostalgia_pages() -> list[str]:
    folder = OUTPUT_DIR / "nostalgia"
    if not folder.exists():
        return []

    return [
        str(path.relative_to(OUTPUT_DIR)).replace("\\", "/")
        for path in sorted(folder.glob("*.html"))
        if path.name != "index.html"
    ]


def collection_pages() -> list[str]:
    folder = OUTPUT_DIR / "collections"
    if not folder.exists():
        return []

    return [
        str(path.relative_to(OUTPUT_DIR)).replace("\\", "/")
        for path in sorted(folder.glob("*.html"))
        if path.name != "index.html"
    ]


def generate_master_catalog_html() -> Path:
    all_pages: list[str] = []
    all_pages.extend(FRONT_PAGES)
    all_pages.extend(nostalgia_pages())
    all_pages.extend(MIDDLE_PAGES)
    all_pages.extend(collection_pages())
    all_pages.extend(END_PAGES)

    sections = "\n".join(read_page(page) for page in all_pages)

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>TopSpot40 Complete Catalog Version 1</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            color: #111;
            background: white;
        }}

        .catalog-page {{
            max-width: 1100px;
            margin: 32px auto;
            padding: 0 24px;
            page-break-after: always;
            break-after: page;
        }}

        .catalog-page:last-child {{
            page-break-after: auto;
            break-after: auto;
        }}

        a {{
            color: #0645ad;
            text-decoration: none;
        }}

        img {{
            max-width: 100%;
        }}

        .nav {{
            display: none;
        }}

        @media print {{
            body {{
                margin: 0;
            }}

            .catalog-page {{
                max-width: none;
                margin: 0.35in;
                padding: 0;
                page-break-after: always;
                break-after: page;
            }}

            .card,
            .stat,
            .genre-card {{
                page-break-inside: avoid;
                break-inside: avoid;
            }}

            a {{
                color: #111;
                text-decoration: none;
            }}
        }}
    </style>
</head>
<body>
{sections}
</body>
</html>
"""

    MASTER_OUTPUT.write_text(page, encoding="utf-8")
    return MASTER_OUTPUT


def main() -> None:
    output_path = generate_master_catalog_html()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()