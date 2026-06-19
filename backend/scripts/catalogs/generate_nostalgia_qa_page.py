from __future__ import annotations

import argparse
import html
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import (
    DecadeGenre,
    TrackRanking,
    TrackRankingLocale,
    Artist,
    ArtistLocale,
    Track,
    TrackLocale,
)

from backend.services.radio_runtime import (
    build_artist_filename,
    build_detail_filename,
    key_for,
)

OUTPUT_DIR = Path("backend/scripts/catalogs/output")

LANGUAGES = [
    ("en", "English"),
    ("es", "Spanish"),
    ("pt-BR", "Portuguese"),
]


def mark(value: object) -> str:
    return "✅" if value else "❌"


def audio_mark(value: object, unknown: bool = False) -> str:
    if value:
        return "✅"
    return "?" if unknown else "❌"


def qa_block(
        intro_text: object,
        intro_mp3: object,
        detail_long_text: object,
        detail_long_mp3: object,
        detail_short_text: object,
        detail_short_mp3: object,
        artist_text: object,
        artist_mp3: object,
        detail_long_audio_unknown: bool = False,
) -> str:
    return f"""
    <div class="qa-line"><span class="qa-label">Intro</span> T{mark(intro_text)} A{audio_mark(intro_mp3)}</div>
    <div class="qa-line"><span class="qa-label">D Long</span> T{mark(detail_long_text)} A{audio_mark(detail_long_mp3, detail_long_audio_unknown)}</div>
    <div class="qa-line"><span class="qa-label">D Short</span> T{mark(detail_short_text)} A{audio_mark(detail_short_mp3)}</div>
    <div class="qa-line"><span class="qa-label">Artist</span> T{mark(artist_text)} A{audio_mark(artist_mp3)}</div>
    """


def count_pair(text_value: object, audio_value: object, counts: dict, lang: str, item: str) -> None:
    counts[lang][item]["text_total"] += 1
    counts[lang][item]["audio_total"] += 1

    if text_value:
        counts[lang][item]["text_ok"] += 1

    if audio_value:
        counts[lang][item]["audio_ok"] += 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", default="1980s-country")
    return parser.parse_args()


def collection_intro_key(collection_slug: str, ranking: int) -> str:
    return f"collections-intros/{collection_slug}_{ranking:02d}.mp3"

def decade_genre_intro_key(slug: str) -> str:
    return f"decade-genre-intro/{slug}.mp3"


def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        decade_genre = session.exec(
            select(DecadeGenre).where(DecadeGenre.slug == args.slug)
        ).first()

        if not decade_genre:
            raise SystemExit(f"DecadeGenre not found: {args.slug}")

        rows = session.exec(
            select(TrackRanking, Track, Artist)
            .join(Track, TrackRanking.track_id == Track.id)
            .join(Artist, Track.artist_id == Artist.id)
            .where(TrackRanking.decade_genre_id == decade_genre.id)
            .order_by(TrackRanking.ranking)
        ).all()

        ranking_ids = [ranking.id for ranking, _, _ in rows]
        track_ids = [track.id for _, track, _ in rows]
        artist_ids = list({artist.id for _, _, artist in rows})

        intro_locales = session.exec(
            select(TrackRankingLocale).where(
                TrackRankingLocale.track_ranking_id.in_(ranking_ids)
            )
        ).all()

        track_locales = session.exec(
            select(TrackLocale).where(TrackLocale.track_id.in_(track_ids))
        ).all()

        artist_locales = session.exec(
            select(ArtistLocale).where(ArtistLocale.artist_id.in_(artist_ids))
        ).all()

    intro_by_key = {
        (row.track_ranking_id, row.language_code): row
        for row in intro_locales
    }

    track_locale_by_key = {
        (row.track_id, row.language_code): row
        for row in track_locales
    }

    artist_locale_by_key = {
        (row.artist_id, row.language_code): row
        for row in artist_locales
    }

    summary_counts = {
        label: {
            "Intro": {"text_ok": 0, "text_total": 0, "audio_ok": 0, "audio_total": 0},
            "D Long": {"text_ok": 0, "text_total": 0, "audio_ok": 0, "audio_total": 0},
            "D Short": {"text_ok": 0, "text_total": 0, "audio_ok": 0, "audio_total": 0},
            "Artist": {"text_ok": 0, "text_total": 0, "audio_ok": 0, "audio_total": 0},
        }
        for _code, label in LANGUAGES
    }

    table_rows = []

    for ranking, track, artist in rows:
        language_cells = []
        row_has_failure = False
        failure_languages = set()

        for lang_code, label in LANGUAGES:
            intro_locale = intro_by_key.get((ranking.id, lang_code))
            track_locale = track_locale_by_key.get((track.id, lang_code))
            artist_locale = artist_locale_by_key.get((artist.id, lang_code))

            if lang_code == "en":
                intro_text = getattr(ranking, "intro", None)

                detail_long_text = getattr(track, "detail", None)

                detail_long_filename = build_detail_filename(track.spotify_track_id)
                detail_long_mp3 = (
                    key_for("detail", detail_long_filename)
                    if detail_long_filename
                    else None
                )

                detail_short_text = getattr(track, "short_detail", None)
                detail_short_mp3 = getattr(track, "short_detail_tts_key", None)

                artist_text = getattr(artist, "artist_description", None)

                artist_filename = build_artist_filename(artist.spotify_artist_id)
                artist_mp3 = (
                    key_for("artist", artist_filename)
                    if artist_filename
                    else None
                )

                detail_long_audio_unknown = False
            else:
                intro_text = getattr(intro_locale, "intro_text", None)

                detail_long_text = getattr(track_locale, "detail_text", None)
                detail_long_mp3 = getattr(track_locale, "tts_key", None)

                detail_short_text = getattr(track_locale, "short_detail_text", None)
                detail_short_mp3 = getattr(track_locale, "short_detail_tts_key", None)

                artist_text = getattr(artist_locale, "artist_description_text", None)
                artist_mp3 = getattr(artist_locale, "tts_key", None)

                detail_long_audio_unknown = False

            if lang_code == "en":
                intro_mp3 = decade_genre_intro_key(decade_genre.slug)
            else:
                intro_mp3 = getattr(intro_locale, "tts_key", None)

            count_pair(intro_text, intro_mp3, summary_counts, label, "Intro")
            count_pair(detail_long_text, detail_long_mp3, summary_counts, label, "D Long")
            count_pair(detail_short_text, detail_short_mp3, summary_counts, label, "D Short")
            count_pair(artist_text, artist_mp3, summary_counts, label, "Artist")

            if (
                    not intro_text
                    or not intro_mp3
                    or not detail_long_text
                    or not detail_long_mp3
                    or not detail_short_text
                    or not detail_short_mp3
                    or not artist_text
                    or not artist_mp3
            ):
                row_has_failure = True
                failure_languages.add(label)

            language_cells.append(
                f"<td>{qa_block(intro_text, intro_mp3, detail_long_text, detail_long_mp3, detail_short_text, detail_short_mp3, artist_text, artist_mp3, detail_long_audio_unknown)}</td>"
            )

        table_rows.append(f"""
        <tr class="qa-row"
            data-failure="{str(row_has_failure).lower()}"
            data-failure-languages="{','.join(sorted(failure_languages))}">
            <td>{ranking.ranking}</td>
            <td>{html.escape(track.track_name or "")}</td>
            <td>{html.escape(artist.artist_name or "")}</td>
            <td class="small">{html.escape(track.spotify_track_id or "")}</td>
            {"".join(language_cells)}
        </tr>
        """)

    summary_cards = []

    for _code, label in LANGUAGES:
        rows_html = []

        for item in ["Intro", "D Long", "D Short", "Artist"]:
            c = summary_counts[label][item]
            rows_html.append(f"""
                <div class="summary-line">
                    <strong>{item}</strong>
                    T {c["text_ok"]}/{c["text_total"]}
                    A {c["audio_ok"]}/{c["audio_total"]}
                </div>
            """)

        summary_cards.append(f"""
            <div class="summary-card">
                <h3>{label}</h3>
                {"".join(rows_html)}
            </div>
        """)

    summary_html = f"""
    <div class="summary">
        {"".join(summary_cards)}
    </div>
    """

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>QA - {html.escape(decade_genre.slug)}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 30px;
            background: #f7f7f7;
        }}
        h1 {{
            margin-bottom: 4px;
        }}
        .subtitle {{
            margin-bottom: 24px;
            color: #555;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px;
            vertical-align: top;
        }}
        th {{
            background: #222;
            color: white;
            text-align: left;
        }}
        tr:nth-child(even) {{
            background: #f2f2f2;
        }}
        .small {{
            font-size: 12px;
            color: #555;
        }}
        .qa-line {{
            font-family: Consolas, monospace;
            font-size: 13px;
            white-space: nowrap;
            line-height: 1.5;
        }}
        
        .qa-label {{
            display: inline-block;
            width: 58px;
        }}
        
        .legend {{
            margin: 12px 0 16px;
            font-size: 14px;
            color: #444;
        }}
        .summary {{
            display: flex;
            gap: 16px;
            margin-bottom: 24px;
        }}
        .summary-card {{
            background: white;
            border: 1px solid #ddd;
            padding: 12px 16px;
            min-width: 220px;
        }}
        .summary-card h3 {{
            margin: 0 0 8px;
        }}
        .summary-line {{
            font-family: Consolas, monospace;
            font-size: 14px;
            line-height: 1.6;
        }}
    </style>
</head>
<body>
    <h1>Nostalgia QA</h1>
    <div class="subtitle">{html.escape(decade_genre.slug)} — {html.escape(decade_genre.slug)}</div>

    <div class="legend">
        T = Text &nbsp;&nbsp; A = Audio
    </div>

    {summary_html}

    <div style="margin-bottom:12px;">
        <label>
            <input type="checkbox" id="showFailuresOnly">
            Show Failures Only
        </label>
    </div>
    
<div style="margin-bottom:12px;">
    <label>
        Failure Language:
        <select id="failureLanguage">
            <option value="all">All</option>
            <option value="English">English</option>
            <option value="Spanish">Spanish</option>
            <option value="Portuguese">Portuguese</option>
        </select>
    </label>
</div>    
    

    <table>
        <thead>
            <tr>
                <th>Rank</th>
                <th>Track</th>
                <th>Artist</th>
                <th>Spotify ID</th>
                <th>English</th>
                <th>Spanish</th>
                <th>Portuguese</th>
            </tr>
        </thead>
        <tbody>
            {"".join(table_rows)}
        </tbody>
    </table>

<script>
function applyFilters() {{
    const failuresOnly =
        document.getElementById('showFailuresOnly').checked;

    const failureLanguage =
        document.getElementById('failureLanguage').value;

    document.querySelectorAll('tr.qa-row').forEach(row => {{
        const isFailure =
            row.getAttribute('data-failure') === 'true';

        const failureLanguages =
            row.getAttribute('data-failure-languages') || '';

        const matchesFailure =
            !failuresOnly || isFailure;

        const matchesLanguage =
            failureLanguage === 'all'
            || failureLanguages.includes(failureLanguage);

        row.style.display =
            matchesFailure && matchesLanguage ? '' : 'none';
    }});
}}

document.getElementById('showFailuresOnly')
    .addEventListener('change', applyFilters);

document.getElementById('failureLanguage')
    .addEventListener('change', applyFilters);
</script>

</body>
</html>
"""

    output_path = OUTPUT_DIR / f"nostalgia_qa_{decade_genre.slug}.html"
    output_path.write_text(page, encoding="utf-8")

    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()
