from __future__ import annotations

from pathlib import Path
from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine

OUTPUT_DIR = Path("backend/scripts/catalogs/output")
OUTPUT_FILE = OUTPUT_DIR / "demo_catalog_print.html"

SHOWCASE_ARTISTS = [
    141, 514, 162, 1086, 1, 2, 20, 799, 1915, 1924, 896, 1770
]


def h(value) -> str:
    import html
    return html.escape(str(value or ""))


def display_name(value: str | None) -> str:
    if not value:
        return ""
    return value.title().replace("B.B.", "B.B.").replace("D.J.", "D.J.")


def short_text(value: str | None, length: int = 420) -> str:
    if not value:
        return ""
    return value[:length] + ("..." if len(value) > length else "")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        artists = session.execute(
            text("""
                SELECT
                    a.id,
                    a.artist_name,
                    a.artist_description,
                    COUNT(DISTINCT t.id) AS track_count,
                    COUNT(DISTINCT tr.id) AS nostalgia_count,
                    COUNT(DISTINCT ctr.id) AS collection_count,
                    COUNT(DISTINCT ast.id) AS story_count
                FROM artist a
                LEFT JOIN track t ON t.artist_id = a.id
                LEFT JOIN track_ranking tr ON tr.track_id = t.id
                LEFT JOIN collection_track_ranking ctr ON ctr.track_id = t.id
                LEFT JOIN artist_story ast
                    ON ast.artist_id = a.id
                   AND ast.language_code = 'en'
                WHERE a.id = ANY(:artist_ids)
                GROUP BY a.id, a.artist_name, a.artist_description
                ORDER BY a.artist_name
            """),
            {"artist_ids": SHOWCASE_ARTISTS},
        ).all()

    parts = [
        "<!doctype html>",
        "<html>",
        "<head>",
        '<meta charset="utf-8">',
        "<title>TopSpot40 Demo Catalog</title>",
        """
<style>
@media print {
    .page { page-break-after: always; }
}

body {
    font-family: Arial, sans-serif;
    margin: 0;
    color: #222;
}

.page {
    width: 8.5in;
    min-height: 11in;
    box-sizing: border-box;
    padding: 0.65in;
}

.cover {
    display: flex;
    flex-direction: column;
    justify-content: center;
    text-align: center;
}

.cover-logo {
    width: 420px;
    max-width: 90%;
    margin: 0 auto 26px;
    display: block;
}

.cover-subtitle {
    font-size: 25px;
    margin-bottom: 26px;
}

.cover-tagline {
    font-size: 34px;
    font-style: italic;
    font-weight: bold;
    margin-bottom: 28px;
}

.cover-version {
    font-size: 18px;
    color: #666;
    margin-bottom: 22px;
}

.cover-founder {
    font-size: 20px;
    line-height: 1.5;
}

h1 {
    font-size: 36px;
    margin-top: 0;
}

h2 {
    font-size: 26px;
    margin-top: 0;
}

p {
    font-size: 15px;
    line-height: 1.5;
}

.artist-card {
    border: 1px solid #ccc;
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 14px;
}

.artist-card h3 {
    margin: 0 0 6px;
    font-size: 22px;
}

.meta {
    font-size: 14px;
    color: #555;
    margin-bottom: 8px;
}

.small {
    font-size: 13px;
    color: #666;
}

.footer {
    margin-top: 28px;
    font-size: 12px;
    color: #777;
    border-top: 1px solid #ddd;
    padding-top: 8px;
}
</style>
""",
        "</head>",
        "<body>",
    ]

    parts.append("""
<section class="page cover">
    <img src="assets/old_dog_new_tracks.png" alt="TopSpot40 Old Dog New Tracks" class="cover-logo">

    <div class="cover-subtitle">
        Music Discovery Through the Decades
    </div>

    <div class="cover-tagline">
        Discovery Never Ends
    </div>

    <div class="cover-version">
        Version 1 • June 2026
    </div>

    <div class="cover-founder">
        Gary W. Steele<br>
        Founder
    </div>
</section>
""")

    parts.append("""
<section class="page">
    <h1>How to Use This Demo Catalog</h1>
    <p>
        TopSpot40 is a music discovery system built around ranked programs,
        narrated song introductions, artist stories, and curated specialty collections.
    </p>
    <p>
        This short demo catalog shows how the printed guide can introduce users to
        the larger TopSpot40 listening experience.
    </p>
    <p>
        The full online version can include playable artist stories, track detail narration,
        collection pages, nostalgia pages, and future QR codes for instant listening.
    </p>
    <div class="footer">TopSpot40 Demo Catalog</div>
</section>
""")

    parts.append("""
<section class="page">
    <h1>Featured Artist Showcase</h1>
    <p>
        These artists demonstrate the range of TopSpot40: country, rock, pop,
        crooners, blues, Mexican-American favorites, and heritage music.
    </p>
""")

    for artist in artists:
        story_text = "Story Available" if artist.story_count else "No Story Yet"

        parts.append(f"""
<div class="artist-card">
    <h3>{h(display_name(artist.artist_name))}</h3>
    <div class="meta">
        {artist.track_count} Tracks •
        {artist.nostalgia_count} Nostalgia Appearances •
        {artist.collection_count} Collection Appearances •
        {story_text}
    </div>
    <p>{h(short_text(artist.artist_description))}</p>
    <div class="small">Online artist page: artists/{artist.id}.html</div>
</div>
""")

    parts.append("""
    <div class="footer">Featured Artist Showcase</div>
</section>
""")

    parts.append("""
<section class="page">
    <h1>Sample Nostalgia Programs</h1>
    <p>
        The full catalog will include one page for every decade and genre combination,
        such as 1950s Country, 1960s Rock, 1970s Pop, and more.
    </p>
    <h2>Example Pages</h2>
    <ul>
        <li>1950s Country</li>
        <li>1960s Rock</li>
        <li>1970s Pop</li>
        <li>1980s Country</li>
    </ul>
    <div class="footer">Nostalgia Library Preview</div>
</section>
""")

    parts.append("""
<section class="page">
    <h1>Sample Collections</h1>
    <p>
        Collections organize music around themes, heritage, moods, artists, and cultural memory.
    </p>
    <h2>Example Collections</h2>
    <ul>
        <li>Railroad & Train Songs</li>
        <li>Mexican-American Favorites</li>
        <li>Great American Songbook</li>
        <li>Patriotic Favorites</li>
        <li>Traditional Hymns</li>
    </ul>
    <div class="footer">Collection Library Preview</div>
</section>
""")

    parts.append("</body></html>")

    OUTPUT_FILE.write_text("\n".join(parts), encoding="utf-8")
    print(f"Generated: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()