from __future__ import annotations

import html
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine

OUTPUT_DIR = Path("backend/scripts/catalogs/output")


def generate_bb_king_story_page() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        row = session.exec(text("""
            select
                a.artist_name,
                ast.title,
                ast.story_text,
                ast.duration_seconds
            from artist a
            join artist_story ast on ast.artist_id = a.id
            where a.id = 896
              and ast.language_code = 'en'
        """)).first()

    if not row:
        raise SystemExit("B.B. King story not found")

    artist_name, title, story_text, duration_seconds = row
    minutes = round((duration_seconds or 0) / 60)

    story_paragraphs = "\n".join(
        f"<p>{html.escape(paragraph.strip())}</p>"
        for paragraph in story_text.split("\n")
        if paragraph.strip()
    )

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>B.B. King Artist Story</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 32px auto; max-width: 1000px; padding: 0 24px; }}
        .nav {{ margin-bottom: 24px; font-size: 15px; }}
        .nav a {{ color: #0645ad; text-decoration: none; margin-right: 14px; }}
        h1 {{ font-size: 46px; margin-bottom: 8px; text-transform: uppercase; }}
        .subtitle {{ font-size: 20px; line-height: 1.4; color: #555; margin-bottom: 30px; }}
        h2 {{ font-size: 28px; margin-top: 30px; border-top: 1px solid #ccc; padding-top: 18px; }}
        p {{ font-size: 17px; line-height: 1.55; }}
        .note {{ margin: 22px 0; padding: 14px 18px; background: #f4f4f4; border-left: 4px solid #777; font-size: 17px; line-height: 1.45; }}
        .footer {{ margin-top: 40px; border-top: 1px solid #ccc; padding-top: 14px; color: #555; font-size: 14px; }}
    </style>
</head>
<body>
    <div class="nav">
        <a href="index.html">TopSpot40 Catalog</a>
        <a href="artists/index.html">Featured Artists</a>
    </div>

    <h1>{html.escape(artist_name)} Artist Story</h1>

    <div class="subtitle">
        Complete featured artist biography example • {minutes} minute narrated story
    </div>

    <div class="note">
        This complete artist story is included as an example of the narrated biography content available in TopSpot40.
        Artist stories are available in English, Spanish, and Portuguese.
    </div>

    <h2>{html.escape(title or artist_name)}</h2>

    {story_paragraphs}

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "bb_king_artist_story.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_bb_king_story_page()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()