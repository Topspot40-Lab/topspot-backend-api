from __future__ import annotations

from pathlib import Path

OUTPUT_DIR = Path("backend/scripts/catalogs/output")


def generate_using_topspot40_page() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    page = """<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Using TopSpot40</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 32px auto; max-width: 1000px; padding: 0 24px; }
        .nav { margin-bottom: 24px; font-size: 15px; }
        .nav a { color: #0645ad; text-decoration: none; margin-right: 14px; }
        h1 { font-size: 46px; margin-bottom: 8px; text-transform: uppercase; }
        .subtitle { font-size: 20px; line-height: 1.4; color: #555; margin-bottom: 30px; }
        h2 { font-size: 28px; margin-top: 30px; border-top: 1px solid #ccc; padding-top: 18px; }
        p, li { font-size: 17px; line-height: 1.5; }
        .note { margin: 22px 0; padding: 14px 18px; background: #f4f4f4; border-left: 4px solid #777; font-size: 17px; line-height: 1.45; }
        .footer { margin-top: 40px; border-top: 1px solid #ccc; padding-top: 14px; color: #555; font-size: 14px; }
    </style>
</head>
<body>
    <div class="nav">
        <a href="index.html">TopSpot40 Catalog</a>
    </div>

    <h1>Using TopSpot40</h1>

    <div class="subtitle">
        Important information about Spotify links, languages, and the TopSpot40 discovery experience.
    </div>

    <h2>Listening on Spotify</h2>
    <p>
        TopSpot40 is a music discovery and storytelling platform. When a listener selects a song,
        TopSpot40 opens the song's public Spotify page in the Spotify app or website.
        TopSpot40 does not host, distribute, stream, or control music playback.
    </p>

    <p>
        Spotify provides the licensed music experience and determines playback availability,
        advertisements, account requirements, and other service restrictions.
        TopSpot40 provides rankings, artist biographies, narrated stories, music history,
        curated collections, and discovery context.
    </p>

    <div class="note">
        TopSpot40 guides listeners to music on Spotify but does not require Spotify authorization,
        store Spotify access tokens, or control a listener's Spotify account or playback device.
    </div>

    <h2>Spotify Accounts and Availability</h2>
    <p>
        TopSpot40 does not require a Spotify Premium subscription. A listener may use Spotify
        according to the account options, availability, and restrictions offered by Spotify.
    </p>

    <h2>Spotify Terms of Service</h2>
    <p>
        Listeners use Spotify directly and remain responsible for complying with Spotify's
        Terms of Service and applicable policies. TopSpot40 does not replace, bypass,
        or modify Spotify's service.
    </p>

    <h2>Supported Languages</h2>
    <p>
        TopSpot40 includes narrated content in English, Spanish, and Portuguese. Artist stories and discovery content
        are designed to help listeners experience the same music history and storytelling across all three supported languages.
    </p>

    <ul>
        <li>English</li>
        <li>Spanish</li>
        <li>Portuguese</li>
    </ul>

    <h2>What TopSpot40 Adds</h2>
    <p>
        TopSpot40 adds a storytelling and discovery layer around ranked songs and curated collections. Listeners may hear
        narrated introductions, song details, artist biographies, historical background, collection introductions,
        and radio-style transitions.
    </p>

    <ul>
        <li>Ranked nostalgia programs</li>
        <li>Curated themed collections</li>
        <li>Featured artist biographies</li>
        <li>Artist Spotlight listening experiences</li>
        <li>Radio-inspired narration and guided discovery</li>
        <li>Music history and cultural context</li>
    </ul>

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "using_topspot40.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_using_topspot40_page()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()