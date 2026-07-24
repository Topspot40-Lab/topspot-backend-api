from __future__ import annotations

import re
from pathlib import Path

OUTPUT_DIR = Path("backend/scripts/catalogs/output")
GUIDE_OUTPUT = OUTPUT_DIR / "guide_catalog.html"

GUIDE_PAGES = [
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
        return f"<section class='catalog-page'><h1>Missing page: {relative_path}</h1></section>"

    html_text = path.read_text(encoding="utf-8")
    body = extract_body(html_text)

    return f"""
<section class="catalog-page" data-source="{relative_path}">
{body}
</section>
"""


def generate_guide_catalog_html() -> Path:
    sections = "\n".join(read_page(page) for page in GUIDE_PAGES)

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>TopSpot40 Guide Catalog Version 1</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            color: #111;
            background: white;
        }}

        .catalog-page {{
            max-width: 1000px;
            margin: 32px auto;
            padding: 0 24px;
            page-break-after: always;
            break-after: page;
        }}

        .catalog-page:last-child {{
            page-break-after: auto;
            break-after: auto;
        }}

        .nav {{
            display: none;
        }}

        a {{
            color: #0645ad;
            text-decoration: none;
        }}

        img {{
            max-width: 100%;
        }}

        @media print {{
            body {{
                margin: 0;
            }}

            .catalog-page {{
                max-width: none;
                margin: 0.5in;
                padding: 0;
                page-break-after: always;
                break-after: page;
            }}

            .card,
            .stat,
            .genre-card,
            .note,
            .quote {{
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

    GUIDE_OUTPUT.write_text(page, encoding="utf-8")
    return GUIDE_OUTPUT


def main() -> None:
    output_path = generate_guide_catalog_html()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()