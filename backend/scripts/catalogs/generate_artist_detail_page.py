from __future__ import annotations

import argparse
import html
import os
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine
from collections import defaultdict

OUTPUT_DIR = Path("backend/scripts/catalogs/output/artists")
DEFAULT_AUDIO_BUCKET = "audio-en"


def h(value) -> str:
    return html.escape(str(value or ""))


def audio_url(bucket: str | None, key: str | None) -> str | None:
    supabase_url = os.getenv("SUPABASE_URL")
    if not supabase_url or not key:
        return None

    final_bucket = bucket or DEFAULT_AUDIO_BUCKET
    return f"{supabase_url.rstrip('/')}/storage/v1/object/public/{final_bucket}/{key}"


def audio_player(bucket: str | None, key: str | None, label: str) -> str:
    url = audio_url(bucket, key)
    if not url:
        return f'<p class="small">No {h(label)} MP3 available.</p>'

    return (
        f'<div class="audio">'
        f'<div class="small">{h(label)}</div>'
        f'<audio controls src="{h(url)}"></audio>'
        f"</div>"
    )


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
                SELECT
                    a.id,
                    a.artist_name,
                    a.artist_description,
                    al.artist_description_text,
                    al.tts_bucket AS artist_tts_bucket,
                    al.tts_key AS artist_tts_key
                FROM artist a
                LEFT JOIN artist_locale al
                    ON al.artist_id = a.id
                   AND al.language_code = 'en'
                WHERE a.id = :artist_id
            """),
            {"artist_id": args.artist_id},
        ).first()

        if not artist:
            raise SystemExit(f"Artist not found: {args.artist_id}")

        story = session.execute(
            text("""
                SELECT
                    title,
                    story_text,
                    story_type,
                    duration_seconds,
                    tts_bucket,
                    tts_key
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
                SELECT
                    t.id AS track_id,
                    t.track_name,
                    t.year_released,
                    t.detail,
                    t.short_detail,
                    t.short_detail_tts_key AS track_short_detail_tts_key,
                    tl.detail_text,
                    tl.tts_bucket AS detail_tts_bucket,
                    tl.tts_key AS detail_tts_key,
                    tl.short_detail_text,
                    tl.short_detail_tts_key AS locale_short_detail_tts_key
                FROM track t
                LEFT JOIN track_locale tl
                    ON tl.track_id = t.id
                   AND tl.language_code = 'en'
                WHERE t.artist_id = :artist_id
                ORDER BY t.track_name
            """),
            {"artist_id": args.artist_id},
        ).all()

        nostalgia = session.execute(
            text("""
                SELECT
                    t.track_name,
                    tr.ranking,
                    tr.intro,
                    dg.slug AS program_slug,
                    trl.intro_text,
                    trl.tts_bucket AS intro_tts_bucket,
                    trl.tts_key AS intro_tts_key
                FROM track_ranking tr
                JOIN track t ON t.id = tr.track_id
                JOIN decade_genre dg ON dg.id = tr.decade_genre_id
                LEFT JOIN track_ranking_locale trl
                    ON trl.track_ranking_id = tr.id
                   AND trl.language_code = 'en'
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
                    c.slug AS collection_slug,
                    ctrl.intro_text,
                    ctrl.tts_key AS intro_tts_key
                FROM collection_track_ranking ctr
                JOIN track t ON t.id = ctr.track_id
                JOIN collection c ON c.id = ctr.collection_id
                LEFT JOIN collection_track_ranking_locale ctrl
                    ON ctrl.collection_track_ranking_id = ctr.id
                   AND ctrl.lang = 'en'
                WHERE t.artist_id = :artist_id
                ORDER BY c.name, ctr.ranking
            """),
            {"artist_id": args.artist_id},
        ).all()

    artist_description = artist.artist_description_text or artist.artist_description

    nostalgia_groups = defaultdict(list)

    for row in nostalgia:
        nostalgia_groups[row.program_slug].append(row)

    collection_groups = defaultdict(list)

    for row in collections:
        collection_groups[row.collection_name].append(row)

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
.nav { margin-bottom: 24px; }
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
.stat .label { color: #555; }
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
th { background: #f0f0f0; }
.audio { margin: 10px 0 18px; }
audio {
    width: 100%;
    max-width: 520px;
}
.small {
    color: #666;
    font-size: 14px;
}
.text-block { white-space: pre-wrap; }
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
        html_parts.append(audio_player(story.tts_bucket, story.tts_key, "Artist Story MP3"))
        html_parts.append('<details open><summary>Story Text</summary>')
        html_parts.append(f'<div class="text-block">{h(story.story_text)}</div>')
        html_parts.append("</details>")
    else:
        html_parts.append("<p>No English artist story found.</p>")
    html_parts.append("</div>")

    html_parts.append('<div class="card">')
    html_parts.append("<h2>Artist Description</h2>")
    html_parts.append(audio_player(artist.artist_tts_bucket, artist.artist_tts_key, "Artist Description MP3"))
    html_parts.append(
        f'<div class="text-block">{h(artist_description)}</div>'
        if artist_description
        else "<p>No artist description found.</p>"
    )
    html_parts.append("</div>")

    html_parts.append('<div class="card">')
    html_parts.append("<h2>Track Detail Review</h2>")

    for track in tracks:
        detail_text = track.detail_text or track.detail
        short_detail_text = track.short_detail_text or track.short_detail
        short_detail_key = track.locale_short_detail_tts_key or track.track_short_detail_tts_key

        html_parts.append("<details>")
        html_parts.append(
            f"<summary>{h(track.track_name)}"
            + (f" ({h(track.year_released)})" if track.year_released else "")
            + "</summary>"
        )

        html_parts.append("<h4>Detail Text</h4>")
        html_parts.append(audio_player(track.detail_tts_bucket, track.detail_tts_key, "Detail MP3"))
        html_parts.append(
            f'<div class="text-block">{h(detail_text)}</div>'
            if detail_text
            else '<div class="text-block"><em>Missing</em></div>'
        )

        html_parts.append("<h4>Short Detail Text</h4>")
        html_parts.append(audio_player(DEFAULT_AUDIO_BUCKET, short_detail_key, "Short Detail MP3"))
        html_parts.append(
            f'<div class="text-block">{h(short_detail_text)}</div>'
            if short_detail_text
            else '<div class="text-block"><em>Missing</em></div>'
        )

        html_parts.append("</details>")

    html_parts.append("</div>")

    html_parts.append('<div class="card">')
    html_parts.append("<h2>Nostalgia Program Appearances</h2>")

    if nostalgia:
        nostalgia_groups = defaultdict(list)

        for row in nostalgia:
            nostalgia_groups[row.program_slug].append(row)

        for program_slug, rows in sorted(nostalgia_groups.items()):
            program = str(program_slug or "").replace("_", " ").title()

            html_parts.append("<details>")
            html_parts.append(
                f"<summary>{h(program)} ({len(rows)} tracks)</summary>"
            )

            html_parts.append("<ul>")

            for row in rows:
                html_parts.append(
                    f"<li>#{row.ranking} - {h(row.track_name)}</li>"
                )

            html_parts.append("</ul>")
            html_parts.append("</details>")

    else:
        html_parts.append("<p>No nostalgia appearances found.</p>")

    html_parts.append("</div>")

    html_parts.append('<div class="card">')
    html_parts.append("<h2>Collection Appearances</h2>")

    if collections:

        for collection_name, rows in sorted(collection_groups.items()):

            html_parts.append("<details>")
            html_parts.append(
                f"<summary>{h(collection_name)} ({len(rows)} tracks)</summary>"
            )

            html_parts.append("<ul>")

            for row in rows:
                html_parts.append(
                    f"<li>#{row.ranking} - {h(row.track_name)}</li>"
                )

            html_parts.append("</ul>")
            html_parts.append("</details>")

    else:
        html_parts.append("<p>No collection appearances found.</p>")

    html_parts.append("</div>")

    html_parts.append("</body></html>")

    output_path = OUTPUT_DIR / f"{artist.id}.html"
    output_path.write_text("\n".join(html_parts), encoding="utf-8")

    print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()