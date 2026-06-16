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
            max-width: 1000px;
            padding: 0 24px;
        }

        h1 {
            font-size: 46px;
            margin-bottom: 6px;
        }

        .subtitle {
            font-size: 20px;
            color: #555;
            margin-bottom: 32px;
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
    </style>
</head>
<body>
    <h1>TopSpot40 Catalog</h1>
    <div class="subtitle">Music discovery through the decades</div>

    <div class="card">
        <h2>Collection Library</h2>
        <p>Browse specialty music collections including heritage favorites, railroad songs, patriotic favorites, Motown, Disney, crooners, hymns, and more.</p>
        <a class="button" href="collections_index.html">Browse Collections</a>
    </div>

    <div class="card">
        <h2>Nostalgia Library</h2>
        <p>Browse decade-and-genre programs from the 1950s through the 2020s.</p>
        <a class="button" href="nostalgia_index.html">Browse Nostalgia Programs</a>
    </div>

    <div class="card">
        <h2>Featured Artists</h2>
        <p>Explore featured artists with TopSpot artist stories and curated track groups.</p>
        <a class="button" href="artists/index.html">Browse Featured Artists</a>
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
