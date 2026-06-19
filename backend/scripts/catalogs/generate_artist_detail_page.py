from __future__ import annotations

import argparse
import html
import os
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine

OUTPUT_DIR = Path("backend/scripts/catalogs/output/artists")


def h(value) -> str:
    return html.escape(str(value or ""))


def audio_url(bucket: str | None, key: str | None) -> str | None:
    supabase_url = os.getenv("SUPABASE_URL")
    if not supabase_url or not bucket or not key:
        return None
    return f"{supabase_url.rstrip('/')}/storage/v1/object/public/{bucket}/{key}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artist-id", type=int, default=141)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        artist = session.execute(
            text("""
                SELECT id, artist_name, artist_description
                FROM artist
                WHERE id = :artist_id
            """),
            {"artist_id": args.artist_id},
        ).first()

        if not artist:
            raise SystemExit(f"Artist not found: {args.artist_id}")

        story = session.execute(
            text("""
                SELECT title, story_text, story_type, duration_seconds, tts_bucket, tts_key
                FROM artist_story
                WHERE artist_id = :artist_id
                  AND language_code = 'en'
                ORDER BY duration_seconds DESC
                LIMIT 1
            """),
            {"artist_id": args.artist_id},
        ).first()

        tracks = session.execute(
            text("""
                SELECT id, track_name, year_released, detail, short_detail
                FROM track
                WHERE artist_id = :artist_id
                ORDER BY track_name
            """),
            {"artist_id": args.artist_id},
        ).all()

        nostalgia = session.execute(
            text("""
                SELECT
                    t.track_name,
                    tr.ranking,
                    tr.intro,
                    dg.slug AS program_slug
                FROM track_ranking tr
                JOIN track t ON t.id = tr.track_id
                JOIN decade_genre dg ON dg.id = tr.decade_genre_id
                WHERE t.artist_id = :artist_id
                ORDER BY dg.slug, tr.ranking
            """),
            {"artist_id": args.artist_id},
        ).all()

        collections = session.execute(
            text("""
                SELECT
                    t.track_name,
                    ctr.ranking,
                    ctr.intro,
                    c.name AS collection_name,
                    c.slug AS collection_slug
                FROM collection_track_ranking ctr
                JOIN track t ON t.id = ctr.track_id
                JOIN collection c ON c.id = ctr.collection_id
                WHERE t.artist_id = :artist_id
                ORDER BY c.name, ctr.ranking
            """),
            {"artist_id": args.artist_id},
        ).all()

    story_audio = audio_url(story.tts_bucket, story.tts_key) if story else None

    html_parts = [
        "<!doctype html>",
        "<html>",
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{h(artist.artist_name)} - TopSpot40 Artist</title>",
        """
<style>
body {
    font-family: Arial, sans-serif;
    margin: 32px auto;
    max-width: 1200px;
    padding: 0 24px;
    line-height: 1.5;
}
.nav {
    margin-bottom: 24px;
}
.nav a {
    color: #0645ad;
    text-decoration: none;
    margin-right: 16px;
}
h1 {
    font-size: 46px;
    margin-bottom: 4px;
}
.subtitle {
    font-size: 18px;
    color: #555;
    margin-bottom: 28px;
}
.card {
    border: 1px solid #ddd;
    border-radius: 12px;
    padding: 18px 22px;
    margin-bottom: 22px;
    background: #fafafa;
}
.stat-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
    margin-bottom: 24px;
}
.stat {
    border: 1px solid #ddd;
    border-radius: 10px;
    padding: 14px;
    background: white;
}
.stat .num {
    font-size: 28px;
    font-weight: bold;
}
.stat .label {
    color: #555;
}
details {
    border: 1px solid #ddd;
    border-radius: 10px;
    padding: 12px 16px;
    margin-bottom: 12px;
    background: white;
}
summary {
    cursor: pointer;
    font-weight: bold;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 12px;
}
th, td {
    border-bottom: 1px solid #ddd;
    padding: 8px;
    text-align: left;
    vertical-align: top;
}
th {
    background: #f0f0f0;
}
.audio {
    margin: 10px 0;
}
.small {
    color: #666;
    font-size: 14px;
}
.text-block {
    white-space: pre-wrap;
}
</style>
""",
        "</head>",
        "<body>",
        '<div class="nav">',
        '<a href="../index.html">← Catalog Home</a>',
        '<a href="../featured_artists.html">Featured Artists</a>',
        "</div>",
        f"<h1>{h(artist.artist_name)}</h1>",
        '<div class="subtitle">TopSpot40 Featured Artist Detail Page</div>',
        '<div class="stat-grid">',
        f'<div class="stat"><div class="num">{len(tracks)}</div><div class="label">Tracks</div></div>',
        f'<div class="stat"><div class="num">{len(nostalgia)}</div><div class="label">Nostalgia Appearances</div></div>',
        f'<div class="stat"><div class="num">{len(collections)}</div><div class="label">Collection Appearances</div></div>',
        f'<div class="stat"><div class="num">{"Yes" if story else "No"}</div><div class="label">Artist Story</div></div>',
        "</div>",
    ]

    html_parts.append('<div class="card">')
    html_parts.append("<h2>Artist Story</h2>")
    if story:
        minutes = round((story.duration_seconds or 0) / 60, 1)
        html_parts.append(f"<h3>{h(story.title)}</h3>")
        html_parts.append(f'<p class="small">Type: {h(story.story_type)} • Duration: {minutes} minutes</p>')
        if story_audio:
            html_parts.append(f'<div class="audio"><audio controls src="{h(story_audio)}"></audio></div>')
        else:
            html_parts.append('<p class="small">No artist story MP3 URL available.</p>')
        html_parts.append('<details open><summary>Story Text</summary>')
        html_parts.append(f'<div class="text-block">{h(story.story_text)}</div>')
        html_parts.append("</details>")
    else:
        html_parts.append("<p>No English artist story found.</p>")
    html_parts.append("</div>")

    html_parts.append('<div class="card">')
    html_parts.append("<h2>Artist Description</h2>")
    html_parts.append(
        f'<div class="text-block">{h(artist.artist_description)}</div>'
        if artist.artist_description
        else "<p>No artist description found.</p>"
    )
    html_parts.append("</div>")

    html_parts.append('<div class="card">')
    html_parts.append("<h2>Track Detail Review</h2>")
    for track in tracks:
        html_parts.append("<details>")
        html_parts.append(
            f"<summary>{h(track.track_name)}"
            + (f" ({h(track.year_released)})" if track.year_released else "")
            + "</summary>"
        )
        html_parts.append("<h4>Detail Text</h4>")
        html_parts.append(f'<div class="text-block">{h(track.detail) if track.detail else "<em>Missing</em>"}</div>')
        html_parts.append("<h4>Short Detail Text</h4>")
        html_parts.append(f'<div class="text-block">{h(track.short_detail) if track.short_detail else "<em>Missing</em>"}</div>')
        html_parts.append("</details>")
    html_parts.append("</div>")

    html_parts.append('<div class="card">')
    html_parts.append("<h2>Nostalgia Program Appearances</h2>")
    if nostalgia:
        html_parts.append("<table>")
        html_parts.append("<tr><th>Program</th><th>Rank</th><th>Track</th><th>Intro</th></tr>")
        for row in nostalgia:
            program = str(row.program_slug or "").replace("_", " ").title()
            html_parts.append(
                "<tr>"
                f"<td>{h(program)}</td>"
                f"<td>#{h(row.ranking)}</td>"
                f"<td>{h(row.track_name)}</td>"
                f"<td>{h(row.intro)}</td>"
                "</tr>"
            )
        html_parts.append("</table>")
    else:
        html_parts.append("<p>No nostalgia appearances found.</p>")
    html_parts.append("</div>")

    html_parts.append('<div class="card">')
    html_parts.append("<h2>Collection Appearances</h2>")
    if collections:
        html_parts.append("<table>")
        html_parts.append("<tr><th>Collection</th><th>Rank</th><th>Track</th><th>Intro</th></tr>")
        for row in collections:
            html_parts.append(
                "<tr>"
                f"<td>{h(row.collection_name)}</td>"
                f"<td>#{h(row.ranking)}</td>"
                f"<td>{h(row.track_name)}</td>"
                f"<td>{h(row.intro)}</td>"
                "</tr>"
            )
        html_parts.append("</table>")
    else:
        html_parts.append("<p>No collection appearances found.</p>")
    html_parts.append("</div>")

    html_parts.append("</body></html>")

    output_path = OUTPUT_DIR / f"{artist.id}.html"
    output_path.write_text("\n".join(html_parts), encoding="utf-8")

    print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()