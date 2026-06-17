from __future__ import annotations

from pathlib import Path

OUTPUT_DIR = Path("backend/scripts/catalogs/output")


def generate_at_a_glance_page() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    page = """<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>TopSpot40 At A Glance</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 32px auto;
            max-width: 1100px;
            padding: 0 24px;
        }

        .nav {
            margin-bottom: 24px;
            font-size: 15px;
        }

        .nav a {
            color: #0645ad;
            text-decoration: none;
            margin-right: 14px;
        }

        h1 {
            font-size: 46px;
            margin-bottom: 8px;
            text-transform: uppercase;
        }

        .subtitle {
            font-size: 20px;
            line-height: 1.4;
            color: #555;
            margin-bottom: 30px;
        }

        h2 {
            font-size: 28px;
            margin-top: 34px;
            border-top: 1px solid #ccc;
            padding-top: 18px;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin: 18px 0 28px 0;
        }

        .stat {
            border: 1px solid #ccc;
            border-radius: 12px;
            padding: 18px;
            text-align: center;
            background: #fafafa;
        }

        .stat-number {
            font-size: 34px;
            font-weight: bold;
        }

        .stat-label {
            font-size: 15px;
            color: #555;
            margin-top: 6px;
        }

        p {
            font-size: 17px;
            line-height: 1.45;
        }

        .note {
            margin-top: 18px;
            padding: 14px 18px;
            background: #f4f4f4;
            border-left: 4px solid #777;
            font-size: 16px;
            line-height: 1.45;
        }

        .footer {
            margin-top: 40px;
            border-top: 1px solid #ccc;
            padding-top: 14px;
            color: #555;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="nav">
        <a href="index.html">TopSpot40 Catalog</a>
    </div>

    <h1>TopSpot40 At A Glance</h1>

    <div class="subtitle">
        A quick look at the scale, structure, and storytelling behind TopSpot40.
    </div>

    <h2>Music Library</h2>
    <div class="stats-grid">
        <div class="stat">
            <div class="stat-number">4,425+</div>
            <div class="stat-label">Tracks</div>
        </div>
        <div class="stat">
            <div class="stat-number">1,943</div>
            <div class="stat-label">Total Artists</div>
        </div>
        <div class="stat">
            <div class="stat-number">1950s–2020s</div>
            <div class="stat-label">Music Across the Decades</div>
        </div>
    </div>

    <h2>Listening Experiences</h2>
    <div class="stats-grid">
        <div class="stat">
            <div class="stat-number">64</div>
            <div class="stat-label">Nostalgia Programs</div>
        </div>
        <div class="stat">
            <div class="stat-number">52</div>
            <div class="stat-label">Curated Collections</div>
        </div>
        <div class="stat">
            <div class="stat-number">9</div>
            <div class="stat-label">Collection Groups</div>
        </div>
    </div>

    <h2>Featured Artist Storytelling</h2>
    <div class="stats-grid">
        <div class="stat">
            <div class="stat-number">329</div>
            <div class="stat-label">Featured Artists</div>
        </div>
        <div class="stat">
            <div class="stat-number">110+ Hours</div>
            <div class="stat-label">Narrated Artist Stories</div>
        </div>
        <div class="stat">
            <div class="stat-number">3</div>
            <div class="stat-label">Languages</div>
        </div>
    </div>

    <div class="note">
        Featured Artist stories are available in English, Spanish, and Portuguese.
        The narration library represents more than 110 hours of artist-story content
        across the three supported languages.
    </div>

    <h2>Genres</h2>
    <div class="stats-grid">
        <div class="stat"><div class="stat-number">Country</div><div class="stat-label">Genre</div></div>
        <div class="stat"><div class="stat-number">Pop</div><div class="stat-label">Genre</div></div>
        <div class="stat"><div class="stat-number">Rock</div><div class="stat-label">Genre</div></div>
        <div class="stat"><div class="stat-number">R&B Soul</div><div class="stat-label">Genre</div></div>
        <div class="stat"><div class="stat-number">Latin Global</div><div class="stat-label">Genre</div></div>
        <div class="stat"><div class="stat-number">Blues Jazz</div><div class="stat-label">Genre</div></div>
        <div class="stat"><div class="stat-number">Folk Acoustic</div><div class="stat-label">Genre</div></div>
        <div class="stat"><div class="stat-number">TV Themes</div><div class="stat-label">Genre</div></div>
    </div>

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "at_a_glance.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_at_a_glance_page()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()