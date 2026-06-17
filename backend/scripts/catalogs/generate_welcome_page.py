from __future__ import annotations

from pathlib import Path

OUTPUT_DIR = Path("backend/scripts/catalogs/output")


def generate_welcome_page() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    page = """<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Welcome to TopSpot40</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 32px auto; max-width: 1000px; padding: 0 24px; }
        .nav { margin-bottom: 24px; font-size: 15px; }
        .nav a { color: #0645ad; text-decoration: none; margin-right: 14px; }
        h1 { font-size: 46px; margin-bottom: 8px; text-transform: uppercase; }
        .subtitle { font-size: 20px; line-height: 1.4; color: #555; margin-bottom: 30px; }
        p { font-size: 18px; line-height: 1.6; }
        .quote {
            margin: 28px 0;
            padding: 16px 20px;
            background: #f4f4f4;
            border-left: 4px solid #777;
            font-size: 22px;
            font-style: italic;
            text-align: center;
        }
        .signature { margin-top: 34px; font-size: 18px; line-height: 1.5; }
        .footer { margin-top: 40px; border-top: 1px solid #ccc; padding-top: 14px; color: #555; font-size: 14px; }
    </style>
</head>
<body>

<div class="nav">
    <a href="index.html">TopSpot40 Catalog</a>
</div>

<h1>Welcome</h1>

<div class="subtitle">
    Welcome to the TopSpot40 Catalog, Version 1.
</div>

<p>
Thank you for exploring TopSpot40.
</p>

<p>
What began as a software project eventually became a journey through music history,
artist stories, cultural traditions, memories, and lifelong discovery.
</p>

<p>
This catalog introduces the people, ideas, collections, artist stories, and listening
experiences that make TopSpot40 unique.
</p>

<p>
TopSpot40 is designed to enhance music listening through rankings, narration, artist
biographies, music history, and curated discovery experiences that integrate with Spotify playback.
</p>

<div class="quote">
Discovery Never Ends.
</div>

<p>
Whether you are revisiting old favorites or discovering something completely new,
I hope you enjoy the journey.
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

    output_path = OUTPUT_DIR / "welcome.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_welcome_page()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()