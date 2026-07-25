from __future__ import annotations

import re
from pathlib import Path

OUTPUT_DIR = Path("backend/scripts/catalogs/output")
OUTPUT_FILE = OUTPUT_DIR / "topspot40_print_catalog_v2.html"

SOURCE_PAGES = [
    "cover.html",
    "welcome.html",
    "table_of_contents.html",

    # PART I
    "part1_story.html",
    "about_topspot40.html",
    "at_a_glance.html",
    "why_topspot40_is_different.html",
    "vision_for_topspot40.html",

    # PART II
    "part2_artists.html",

    "artists/141.html",  # Johnny Cash
    # "artists/514.html",  # Elvis Presley
    # "artists/162.html",    # Beatles
    # "artists/1086.html",   # Frank Sinatra
    # "artists/2.html",      # George Strait
    # "artists/20.html",     # Willie Nelson
    # "artists/1.html",      # Randy Travis
    # "artists/799.html",  # Selena
    # "artists/1915.html",  # Freddy Fender
    "artists/1924.html",  # Vicente Fernández
    # "artists/1770.html",   # Linda Ronstadt
    # "artists/896.html",    # B.B. King

    "artists/index.html",

    # PART III
    "part3_nostalgia.html",

    "nostalgia/1950s-country.html",
    "nostalgia/1960s-rock.html",
    "nostalgia/1970s-pop.html",
    "nostalgia/1980s-rnb_soul.html",
    "nostalgia/1990s-country.html",
    "nostalgia/2000s-latin_global.html",

    "nostalgia_index.html",

    # PART IV
    "part4_collections.html",

    "collections/railroad_train_songs.html",
    "collections/mexican_american_favorites.html",
    "collections/great_american_songbook.html",
    "collections/patriotic_favorites.html",
    "collections/traditional_hymns.html",
    "collections/cowboy_songs_western_favorites.html",

    "collections_index.html",

    # PART V
    "part5_getting_started.html",
    "four_ways_to_listen.html",
    "using_topspot40.html",
    "listening_experience.html",
    "invitation_to_discover.html",
]


def extract_body(html_text: str, source: str = "") -> str:
    match = re.search(r"<body[^>]*>(.*?)</body>", html_text, re.DOTALL | re.IGNORECASE)
    body = match.group(1).strip() if match else html_text.strip()

    # Clean duplicate cover block from cover.html
    if source == "cover.html":
        body = re.sub(
            r'\s*<div class="stats">\s*Version 1\s*•\s*June 2026\s*<br><br>\s*Gary W\. Steele\s*<br>\s*Founder\s*</div>',
            "",
            body,
            flags=re.DOTALL | re.IGNORECASE,
        )

    return body


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    parts = [
        "<!doctype html>",
        "<html>",
        "<head>",
        '<meta charset="utf-8">',
        "<title>TopSpot40 Print Catalog V2</title>",
        """
<style>
body {
    font-family: Arial, sans-serif;
    margin: 0;
    color: #111;
    background: white;
}

@page {
    size: letter landscape;
    margin: 0.45in;
}

.catalog-page {
    width: 11in;
    min-height: 8.5in;
    box-sizing: border-box;
    padding: 0.45in;
    page-break-after: always;
    break-after: page;
}

.catalog-page:last-child {
    page-break-after: auto;
    break-after: auto;
}

.nav {
    display: none;
}

img {
    max-width: 100%;
}

a {
    color: #111;
    text-decoration: none;
}

.card,
.stat,
.genre-card,
.summary-card {
    page-break-inside: avoid;
    break-inside: avoid;
}

.footer {
    margin-top: 28px;
    font-size: 12px;
    color: #777;
    border-top: 1px solid #ddd;
    padding-top: 8px;
}

.cover-image,
.cover-logo {
    max-width: 420px;
    display: block;
    margin: 0 auto 24px;
}

.stats-grid,
.stat-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
}

.decade-grid,
.genre-grid,
.collection-grid,
.group-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 14px;
}

.artist-layout,
.showcase-layout {
    display: grid;
    grid-template-columns: 1.2fr 1fr;
    gap: 18px;
}

details {
    page-break-inside: avoid;
    break-inside: avoid;
}

audio {
    display: none;
}

/* Landscape showcase cleanup */
.catalog-page[data-source^="nostalgia/"],
.catalog-page[data-source^="collections/"] {
    padding: 0.35in;
}

.catalog-page[data-source^="nostalgia/"] body,
.catalog-page[data-source^="collections/"] body {
    max-width: none;
}

.catalog-page[data-source^="nostalgia/"] h1,
.catalog-page[data-source^="collections/"] h1 {
    font-size: 30px;
    margin-bottom: 8px;
}

.catalog-page[data-source^="nostalgia/"] p,
.catalog-page[data-source^="collections/"] p {
    max-width: none;
}

.catalog-page[data-source^="nostalgia/"] ol,
.catalog-page[data-source^="collections/"] ol,
.catalog-page[data-source^="nostalgia/"] ul,
.catalog-page[data-source^="collections/"] ul {
    columns: 2;
    column-gap: 42px;
}

.catalog-page[data-source^="nostalgia/"] li,
.catalog-page[data-source^="collections/"] li {
    break-inside: avoid;
    page-break-inside: avoid;
    margin-bottom: 3px;
}

/* Clean print text spacing */
.text-block {
    line-height: 1.45;
    font-size: 14px;
    white-space: pre-line;
}

.card {
    margin-bottom: 18px;
    padding: 12px 14px;
    border: 1px solid #ddd;
    border-radius: 10px;
}

summary {
    font-weight: bold;
    margin-bottom: 8px;
}

details {
    margin-bottom: 12px;
}

/* Hide audio blocks completely in print catalog */
.audio {
    display: none !important;
}

/* Hide repeated no-audio messages */
.small {
    line-height: 1.35;
}

.small:has(+ audio),
.audio + .small {
    display: none;
}

@media print {
    body {
        margin: 0;
    }

    .catalog-page {
        width: 11in;
        min-height: 8.5in;
        page-break-after: always;
        break-after: page;
    }
}
</style>
""",
        "</head>",
        "<body>",
    ]

    for source in SOURCE_PAGES:
        path = OUTPUT_DIR / source

        if not path.exists():
            print(f"Skipping missing page: {path}")
            continue

        html_text = path.read_text(encoding="utf-8")
        body = extract_body(html_text, source)

        parts.append(f'<section class="catalog-page" data-source="{source}">')
        parts.append(body)
        parts.append("</section>")

    parts.append("</body></html>")

    OUTPUT_FILE.write_text("\n".join(parts), encoding="utf-8")
    print(f"Generated: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
