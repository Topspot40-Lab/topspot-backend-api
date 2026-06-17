from __future__ import annotations

import html
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine

OUTPUT_DIR = Path("backend/scripts/catalogs/output")


def title_case(value: str | None) -> str:
    if not value:
        return ""
    return value.title()


def make_box(label: str, text_value: str | None) -> str:
    if not text_value:
        text_value = "Not available."

    return f"""
    <div class="text-box">
        <div class="box-label">{html.escape(label)}</div>
        <p>{html.escape(text_value)}</p>
    </div>
    """


def generate_listening_experience_page() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        nostalgia = session.exec(text("""
            select
                tr.ranking,
                dg.slug,
                t.track_name,
                a.artist_name,
                tr.intro,
                t.detail,
                a.artist_description
            from track_ranking tr
            join decade_genre dg on dg.id=tr.decade_genre_id
            join track t on t.id=tr.track_id
            join artist a on a.id=t.artist_id
            where tr.id=2
        """)).first()

        collection = session.exec(text("""
            select
                ctr.ranking,
                c.slug,
                c.name,
                t.track_name,
                a.artist_name,
                ctr.intro,
                t.detail,
                a.artist_description
            from collection_track_ranking ctr
            join collection c on c.id=ctr.collection_id
            join track t on t.id=ctr.track_id
            join artist a on a.id=t.artist_id
            where ctr.id=2172
        """)).first()

        spotlight = session.exec(text("""
            select
                a.artist_name,
                t.track_name,
                ast.story_text,
                ast.duration_seconds,
                t.short_detail
            from artist a
            join artist_story ast on ast.artist_id=a.id
            join track t on t.artist_id=a.id
            where a.id=896
              and t.id=1505
              and ast.language_code='en'
        """)).first()

    nostalgia_html = ""
    if nostalgia:
        ranking, dg_slug, track_name, artist_name, intro, detail, artist_description = nostalgia
        nostalgia_html = f"""
        <section class="example">
            <h2>Nostalgia Program Example</h2>
            <div class="example-meta">
                1980s Country • Rank #{ranking}
            </div>
            <h3>{html.escape(title_case(track_name))}</h3>
            <div class="artist-name">{html.escape(artist_name)}</div>

            {make_box("Intro", intro)}
            {make_box("Song Detail", detail)}
            {make_box("Artist Text", artist_description)}

            <div class="play-box">Then Spotify track playback begins.</div>
        </section>
        """

    collection_html = ""
    if collection:
        ranking, collection_slug, collection_name, track_name, artist_name, intro, detail, artist_description = collection
        collection_html = f"""
        <section class="example">
            <h2>Collection Program Example</h2>
            <div class="example-meta">
                {html.escape(collection_name)} • Rank #{ranking}
            </div>
            <h3>{html.escape(title_case(track_name))}</h3>
            <div class="artist-name">{html.escape(artist_name)}</div>

            {make_box("Collection Intro", intro)}
            {make_box("Song Detail", detail)}
            {make_box("Artist Text", artist_description)}

            <div class="play-box">Then Spotify track playback begins.</div>
        </section>
        """

    spotlight_html = ""
    if spotlight:
        artist_name, track_name, story_text, duration_seconds, short_detail = spotlight
        minutes = round((duration_seconds or 0) / 60)
        story_preview = story_text[:1200].strip() + "..."

        spotlight_html = f"""
        <section class="example">
            <h2>Artist Spotlight Example</h2>
            <div class="example-meta">
                {html.escape(artist_name)} • {minutes} minute artist story
            </div>
            <h3>{html.escape(title_case(track_name))}</h3>
            <div class="artist-name">{html.escape(artist_name)}</div>

            {make_box("Artist Bio Opening", story_preview)}
            {make_box("Short Song Detail", short_detail)}

            <div class="play-box">Then Spotify track playback begins.</div>
        </section>
        """

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>TopSpot40 Listening Experience</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 32px auto;
            max-width: 1100px;
            padding: 0 24px;
        }}

        .nav {{
            margin-bottom: 24px;
            font-size: 15px;
        }}

        .nav a {{
            color: #0645ad;
            text-decoration: none;
            margin-right: 14px;
        }}

        h1 {{
            font-size: 46px;
            margin-bottom: 8px;
            text-transform: uppercase;
        }}

        .subtitle {{
            font-size: 19px;
            line-height: 1.4;
            max-width: 900px;
            color: #333;
            margin-bottom: 30px;
        }}

        .example {{
            border-top: 2px solid #333;
            padding-top: 22px;
            margin-top: 34px;
        }}

        .example h2 {{
            font-size: 30px;
            margin-bottom: 6px;
        }}

        .example-meta {{
            font-size: 16px;
            font-weight: bold;
            color: #555;
            margin-bottom: 12px;
        }}

        .example h3 {{
            font-size: 28px;
            margin: 4px 0;
        }}

        .artist-name {{
            font-size: 18px;
            margin-bottom: 18px;
            color: #333;
        }}

        .text-box {{
            border: 1px solid #ccc;
            border-radius: 10px;
            padding: 14px 16px;
            margin: 14px 0;
            background: #fafafa;
        }}

        .box-label {{
            font-weight: bold;
            text-transform: uppercase;
            font-size: 13px;
            color: #555;
            margin-bottom: 6px;
            letter-spacing: .04em;
        }}

        .text-box p {{
            font-size: 16px;
            line-height: 1.45;
            margin: 0;
        }}

        .play-box {{
            margin-top: 16px;
            padding: 12px 16px;
            border-left: 4px solid #555;
            background: #f0f0f0;
            font-weight: bold;
        }}

        .footer {{
            margin-top: 40px;
            border-top: 1px solid #ccc;
            padding-top: 14px;
            color: #555;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="nav">
        <a href="index.html">TopSpot40 Catalog</a>
    </div>

    <h1>TopSpot40 Listening Experience</h1>

    <div class="subtitle">
        TopSpot40 combines Spotify playback with original narration, artist biographies,
        music history, and storytelling. These examples show how TopSpot40 adds context
        before the music begins.
    </div>

    {nostalgia_html}
    {collection_html}
    {spotlight_html}

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "listening_experience.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_listening_experience_page()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()