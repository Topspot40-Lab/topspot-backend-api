from __future__ import annotations

from pathlib import Path

OUTPUT_DIR = Path("backend/scripts/catalogs/output")


def generate_invitation_to_discover_page() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    page = """<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>An Invitation To Discover</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 32px auto; max-width: 1000px; padding: 0 24px; }
        .nav { margin-bottom: 24px; font-size: 15px; }
        .nav a { color: #0645ad; text-decoration: none; margin-right: 14px; }
        h1 { font-size: 46px; margin-bottom: 8px; text-transform: uppercase; }
        .subtitle { font-size: 20px; line-height: 1.4; color: #555; margin-bottom: 30px; }
        p { font-size: 17px; line-height: 1.6; }
        .quote {
            margin: 24px 0;
            padding: 16px 20px;
            background: #f4f4f4;
            border-left: 4px solid #777;
            font-size: 22px;
            font-style: italic;
            text-align: center;
        }
        .signature {
            margin-top: 40px;
            font-size: 18px;
            line-height: 1.5;
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

<h1>An Invitation To Discover</h1>

<div class="subtitle">
    A personal note from the creator of TopSpot40.
</div>

<p>
Thank you for taking the time to explore TopSpot40.
</p>

<p>
What began as a software project eventually became something much more personal. Along the way, I discovered artists, cultures, musical traditions, and stories that I might never have encountered otherwise. Every collection seemed to open another door. Every artist biography led to another artist. Every song revealed another piece of history waiting to be explored.
</p>

<p>
When I started this journey, I was inspired by memories of listening to radio programs as a young boy growing up on an Indiana farm. I hoped to recreate some of the anticipation, storytelling, and excitement that made those experiences so memorable.
</p>

<p>
What I found instead was something even more meaningful. Music has an extraordinary ability to connect people across generations, cultures, languages, and life experiences. A familiar song can bring back a forgotten memory. An artist biography can create a new appreciation for music we have heard for decades. A collection can introduce us to traditions and stories that expand our understanding of the world.
</p>

<p>
TopSpot40 has taught me that curiosity does not have an age limit. Whether we are eighteen or eighty, there is always something new to discover.
</p>

<p>
My hope is that this project encourages listeners not only to enjoy the music they already know, but also to remain curious about the artists, stories, cultures, and history behind it.
</p>

<div class="quote">
Discovery Never Ends.
</div>

<p>
Thank you for joining me on this journey.
</p>

<div class="signature">
Gary W. Steele<br>
Founder, TopSpot40
</div>

<div class="footer">
TopSpot40.com — Music Discovery Through the Decades
</div>

</body>
</html>
"""

    output_path = OUTPUT_DIR / "invitation_to_discover.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_invitation_to_discover_page()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()