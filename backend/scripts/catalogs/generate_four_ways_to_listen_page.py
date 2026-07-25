from __future__ import annotations

from pathlib import Path

OUTPUT_DIR = Path("backend/scripts/catalogs/output")


def generate_four_ways_to_listen_page() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    page = """<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Four Ways to Listen</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 32px auto; max-width: 1000px; padding: 0 24px; }
        .nav { margin-bottom: 24px; font-size: 15px; }
        .nav a { color: #0645ad; text-decoration: none; margin-right: 14px; }
        h1 { font-size: 46px; margin-bottom: 8px; text-transform: uppercase; }
        .subtitle { font-size: 20px; line-height: 1.4; color: #555; margin-bottom: 30px; }
        h2 { font-size: 28px; margin-top: 30px; border-top: 1px solid #ccc; padding-top: 18px; }
        p, li { font-size: 17px; line-height: 1.5; }
        .quote, .note { margin: 22px 0; padding: 14px 18px; background: #f4f4f4; border-left: 4px solid #777; font-size: 18px; line-height: 1.45; }
        .quote { font-style: italic; }
        .footer { margin-top: 40px; border-top: 1px solid #ccc; padding-top: 14px; color: #555; font-size: 14px; }
    </style>
</head>
<body>
    <div class="nav">
        <a href="index.html">TopSpot40 Catalog</a>
    </div>

    <h1>Four Ways to Listen</h1>

    <div class="subtitle">
        TopSpot40 offers four distinct listening experiences, each designed to help listeners discover music in a different way.
    </div>

    <h2>1. Nostalgia Programs</h2>
    <p>
        Nostalgia Programs recreate the experience of classic countdown radio by organizing music by decade and genre.
        Each program contains ranked songs, narrated introductions, artist information, historical context, and public Spotify song links.
    </p>
    <p>Examples include:</p>
    <ul>
        <li>1950s Country</li>
        <li>1960s Rock</li>
        <li>1970s Pop</li>
        <li>1980s Country</li>
        <li>1990s Latin Global</li>
        <li>2000s R&amp;B Soul</li>
    </ul>

    <h2>2. Collections</h2>
    <p>
        Collections organize music around themes, traditions, cultures, historical topics, and shared experiences.
        Unlike Nostalgia Programs, Collections are not limited to a single decade or genre. Instead, they bring together songs connected by a common story.
    </p>
    <p>Examples include:</p>
    <ul>
        <li>Railroad &amp; Train Songs</li>
        <li>Traditional Hymns</li>
        <li>Patriotic Favorites</li>
        <li>Great American Songbook</li>
        <li>Mexican-American Favorites</li>
        <li>Cowboy Songs &amp; Western Favorites</li>
    </ul>

    <h2>3. Artist Spotlight</h2>
    <p>
        Artist Spotlight focuses on individual artists. Featured Artists include narrated biographies, historical background,
        career highlights, and curated track selections designed to tell the story of an artist's life and music.
    </p>
    <p>
        TopSpot40 includes more than 329 Featured Artists with narrated biographies available in English, Spanish, and Portuguese.
    </p>
    <p>Examples include:</p>
    <ul>
        <li>B.B. King</li>
        <li>Johnny Cash</li>
        <li>Selena</li>
        <li>Willie Nelson</li>
        <li>Loretta Lynn</li>
        <li>Frank Sinatra</li>
    </ul>

    <h2>4. Radio-Inspired Discovery</h2>
    <p>
        Radio-Inspired Discovery combines narration, artist information, storytelling, rankings, and public Spotify song links into a guided discovery experience.
        The goal is to recreate some of the magic of traditional radio while listeners choose when to continue to each song in Spotify.
    </p>

    <div class="quote">
        TopSpot40 is not designed to help people listen to more music.
        It is designed to help people connect more deeply with the music they already love.
    </div>

    <div class="note">
        Spotify provides the licensed music service. TopSpot40 links listeners to songs and adds rankings,
        artist biographies, storytelling, music history, and music discovery.
    </div>

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "four_ways_to_listen.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_four_ways_to_listen_page()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()