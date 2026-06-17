from __future__ import annotations

from pathlib import Path
import shutil

OUTPUT_DIR = Path("backend/scripts/catalogs/output")
ASSET_DIR = OUTPUT_DIR / "assets"

# Put your uploaded image here if needed:
# backend/scripts/catalogs/output/assets/old_dog_new_tracks.png
IMAGE_FILENAME = "old_dog_new_tracks.png"


def generate_cover_page() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    image_path = ASSET_DIR / IMAGE_FILENAME

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>TopSpot40 Catalog Cover</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 32px auto;
            max-width: 1000px;
            padding: 0 24px;
            text-align: center;
        }}

        .cover-image {{
            max-width: 520px;
            width: 80%;
            margin: 20px auto 28px auto;
            display: block;
            border-radius: 8px;
        }}

        h1 {{
            font-size: 60px;
            margin: 8px 0 8px 0;
            letter-spacing: 1px;
        }}

        .subtitle {{
            font-size: 26px;
            color: #444;
            margin-bottom: 18px;
        }}

        .tagline {{
            font-size: 30px;
            font-weight: bold;
            margin: 26px 0;
            font-style: italic;
        }}

        .version {{
            font-size: 18px;
            color: #555;
            margin-bottom: 18px;
        }}

        .author {{
            font-size: 20px;
            line-height: 1.4;
            margin-bottom: 28px;
        }}

        .stats {{
            border-top: 1px solid #ccc;
            border-bottom: 1px solid #ccc;
            padding: 16px 0;
            font-size: 17px;
            line-height: 1.5;
            color: #333;
        }}

        .footer {{
            margin-top: 34px;
            color: #555;
            font-size: 14px;
        }}
    </style>
</head>
<body>

    <img class="cover-image" src="assets/{IMAGE_FILENAME}" alt="TopSpot40 Old Dog New Tracks">

    <h1>TOPSPOT40</h1>

    <div class="subtitle">
        Music Discovery Through the Decades
    </div>

    <div class="tagline">
        Discovery Never Ends
    </div>

    <div class="version">
        Version 1 • June 2026
    </div>

    <div class="author">
        Gary W. Steele<br>
        Founder
    </div>

    <div class="stats">
        Version 1 • June 2026<br><br>
    
        Gary W. Steele<br>
        Founder
    </div>

<div class="footer">
    4,425+ Songs Linked Through Spotify • 1,943 Artists • 329 Featured Artists<br>
    64 Nostalgia Programs • 52 Collections<br>
    English • Spanish • Portuguese<br><br>

    TopSpot40.com — Old Dog, New Tracks
</div>

</body>
</html>
"""

    output_path = OUTPUT_DIR / "cover.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_cover_page()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()
