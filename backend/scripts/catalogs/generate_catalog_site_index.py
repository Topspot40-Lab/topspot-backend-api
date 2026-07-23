from __future__ import annotations

from pathlib import Path

OUTPUT_DIR = Path("backend/scripts/catalogs/output")


def generate_catalog_site_index() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    page = """<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>TopSpot40 Catalog</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 32px auto;
            max-width: 1100px;
            padding: 0 24px;
        }

        h1 {
            font-size: 52px;
            margin-bottom: 6px;
        }

        .subtitle {
            font-size: 22px;
            color: #555;
            margin-bottom: 18px;
        }

        .intro {
            font-size: 18px;
            line-height: 1.45;
            max-width: 900px;
            margin-bottom: 28px;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 14px;
            margin-bottom: 34px;
        }

        .stat {
            border: 1px solid #ccc;
            border-radius: 10px;
            padding: 14px;
            text-align: center;
        }

        .stat-number {
            font-size: 28px;
            font-weight: bold;
        }

        .stat-label {
            font-size: 14px;
            color: #555;
            margin-top: 4px;
        }

        .card {
            border: 1px solid #ccc;
            border-radius: 12px;
            padding: 22px;
            margin-bottom: 20px;
        }

        .card h2 {
            margin-top: 0;
            font-size: 28px;
        }

        .card p {
            font-size: 17px;
            line-height: 1.4;
        }

        a.button {
            display: inline-block;
            margin-top: 8px;
            padding: 10px 16px;
            border: 1px solid #333;
            border-radius: 8px;
            text-decoration: none;
            color: #111;
            font-weight: bold;
        }

        .footer {
            margin-top: 36px;
            border-top: 1px solid #ccc;
            padding-top: 14px;
            color: #555;
            font-size: 14px;
        }

        @media print {
            body {
                margin: 0.25in;
                max-width: none;
            }

            .stats-grid {
                grid-template-columns: repeat(4, 1fr);
                gap: 10px;
            }

            .card {
                page-break-inside: avoid;
            }
        }
    </style>
</head>
<body>
    <h1>TopSpot40 Catalog</h1>
    <div class="subtitle">Music discovery through the decades</div>

    <div class="intro">
        Explore the TopSpot40 music catalog, including nostalgia programs by decade and genre,
        curated specialty collections, featured artists, and narrated music discovery experiences.
    </div>

    <p style="font-size:16px; color:#555; max-width:900px;">
        Spotify provides the licensed music service. TopSpot40 links listeners to songs and adds
        rankings, artist biographies, narration, music history, curated collections, and
        guided music discovery.
    </p>

    <div class="stats-grid">
        <div class="stat">
        <div class="stat-number">4,425+</div>
        <div class="stat-label">Songs Linked Through Spotify</div>
        </div>
<div class="stat">
    <div class="stat-number">64</div>
    <div class="stat-label">Nostalgia Programs</div>
</div>

<div class="stat">
    <div class="stat-number">52</div>
    <div class="stat-label">Curated Collections</div>
</div>

<div class="stat">
    <div class="stat-number">1,943</div>
    <div class="stat-label">Artists</div>
</div>

<div class="stat">
    <div class="stat-number">329</div>
    <div class="stat-label">Featured Artists</div>
</div>

<div class="stat">
    <div class="stat-number">8</div>
    <div class="stat-label">Decades</div>
</div>

<div class="stat">
    <div class="stat-number">8</div>
    <div class="stat-label">Genres</div>
</div>

<div class="stat">
    <div class="stat-number">9</div>
    <div class="stat-label">Collection Groups</div>
</div>

<div class="stat">
    <div class="stat-number">3</div>
    <div class="stat-label">Languages</div>
</div>
    </div>

    <div class="card">
        <h2>Start Here</h2>
        <p>Begin with the cover, welcome page, and table of contents for a guided introduction to the TopSpot40 Catalog.</p>
        <a class="button" href="cover.html">Cover</a>
        <a class="button" href="welcome.html">Welcome</a>
        <a class="button" href="table_of_contents.html">Table of Contents</a>
    </div>

    <div class="card">
        <h2>About TopSpot40</h2>
        <p>Learn the story behind TopSpot40, including its radio-inspired roots, the meaning of the name, Patty's Rule, multilingual storytelling, and the personal journey behind the project.</p>
        <a class="button" href="about_topspot40.html">Read About TopSpot40</a>
    </div>

    <div class="card">
        <h2>TopSpot40 At A Glance</h2>
        <p>View the scale of the catalog, including curated track entries, artists, featured artists, nostalgia programs, collections, languages, and narrated artist-story content.</p>
        <a class="button" href="at_a_glance.html">View At A Glance</a>
    </div>

    <div class="card">
        <h2>Why TopSpot40 Is Different</h2>
        <p>See how TopSpot40 differs from a streaming service by focusing on music discovery, storytelling, artist biographies, historical context, and emotional connection.</p>
        <a class="button" href="why_topspot40_is_different.html">Why It Is Different</a>
    </div>

    <div class="card">
        <h2>Four Ways To Listen</h2>
        <p>Explore four discovery experiences: Nostalgia Programs, Collections, Artist Spotlight, and Radio-Inspired Discovery.</p>
        <a class="button" href="four_ways_to_listen.html">Explore Listening Modes</a>
    </div>

    <div class="card">
        <h2>Using TopSpot40</h2>
        <p>Understand Spotify links, account availability, supported languages, and the discovery context TopSpot40 provides.</p>
        <a class="button" href="using_topspot40.html">Using TopSpot40</a>
    </div>

    <div class="card">
        <h2>TopSpot40 Listening Experience</h2>
        <p>See examples of how TopSpot40 combines narration, song details, artist stories, and public Spotify song links into a richer discovery experience.</p>
        <a class="button" href="listening_experience.html">View Listening Experience</a>
    </div>

    <div class="card">
        <h2>A Vision For TopSpot40</h2>
        <p>Read about the larger vision for TopSpot40, including music and memory, older adults, Winter Texans, assisted living communities, multilingual discovery, and lifelong learning.</p>
        <a class="button" href="vision_for_topspot40.html">Read The Vision</a>
    </div>

    <div class="card">
        <h2>Featured Artists</h2>
        <p>Explore featured artists with narrated artist stories, curated track groups, and artist-focused listening experiences.</p>
        <a class="button" href="artists/index.html">Browse Featured Artists</a>
        <a class="button" href="bb_king_artist_story.html">B.B. King Story Example</a>
    </div>

    <div class="card">
        <h2>Nostalgia Library</h2>
        <p>Browse 64 decade-and-genre programs from the 1950s through the 2020s, organized by country, pop, rock, R&amp;B soul, Latin global, blues jazz, folk acoustic, and TV themes.</p>
        <a class="button" href="nostalgia_index.html">Browse Nostalgia Programs</a>
    </div>

    <div class="card">
        <h2>Collection Library</h2>
        <p>Browse 52 curated specialty collections including heritage favorites, railroad songs, patriotic favorites, Motown, Disney, crooners, hymns, legends, classical music, and more.</p>
        <a class="button" href="collections_index.html">Browse Collections</a>
    </div>

    <div class="card">
        <h2>An Invitation To Discover</h2>
        <p>Close the catalog with a personal note from Gary W. Steele about curiosity, discovery, and the journey behind TopSpot40.</p>
        <a class="button" href="invitation_to_discover.html">Read The Closing Note</a>
    </div>

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "index.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_catalog_site_index()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()
