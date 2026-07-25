from __future__ import annotations

import html
from pathlib import Path

from sqlmodel import Session, select
from backend.services.supabase_storage import object_exists_cached

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

ITEMS = ["Intro", "D Long", "D Short", "Artist"]

def verified_audio_key(bucket: str, key: str | None) -> str | None:
    if not key:
        return None

    return key if object_exists_cached(bucket, key) else None


def decade_genre_intro_key(slug: str, ranking: int) -> str:
    filename_slug = slug.replace("-", "_")
    return f"intro/{filename_slug}_{ranking:02d}.mp3"


def add_count(counts: dict, lang: str, item: str, text_value: object, audio_value: object) -> None:
    counts[lang][item]["text_total"] += 1
    counts[lang][item]["audio_total"] += 1
    if text_value:
        counts[lang][item]["text_ok"] += 1
    if audio_value:
        counts[lang][item]["audio_ok"] += 1


def pct(ok: int, total: int) -> float:
    return 100.0 if total == 0 else round((ok / total) * 100, 1)


def css_class(value: float) -> str:
    if value >= 100:
        return "good"
    if value >= 90:
        return "warn"
    return "bad"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        programs = session.exec(
            select(DecadeGenre).order_by(DecadeGenre.slug)
        ).all()

        summary_rows = []

        grand_counts = {
            label: {
                item: {"text_ok": 0, "text_total": 0, "audio_ok": 0, "audio_total": 0}
                for item in ITEMS
            }
            for _code, label in LANGUAGES
        }

        for program in programs:
            rows = session.exec(
                select(TrackRanking, Track, Artist)
                .join(Track, TrackRanking.track_id == Track.id)
                .join(Artist, Track.artist_id == Artist.id)
                .where(TrackRanking.decade_genre_id == program.id)
                .order_by(TrackRanking.ranking)
            ).all()

            ranking_ids = [ranking.id for ranking, _, _ in rows]
            track_ids = [track.id for _, track, _ in rows]
            artist_ids = list({artist.id for _, _, artist in rows})

            intro_locales = session.exec(
                select(TrackRankingLocale).where(
                    TrackRankingLocale.track_ranking_id.in_(ranking_ids)
                )
            ).all() if ranking_ids else []

            track_locales = session.exec(
                select(TrackLocale).where(TrackLocale.track_id.in_(track_ids))
            ).all() if track_ids else []

            artist_locales = session.exec(
                select(ArtistLocale).where(ArtistLocale.artist_id.in_(artist_ids))
            ).all() if artist_ids else []

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

            program_counts = {
                label: {
                    item: {"text_ok": 0, "text_total": 0, "audio_ok": 0, "audio_total": 0}
                    for item in ITEMS
                }
                for _code, label in LANGUAGES
            }

            for ranking, track, artist in rows:
                for lang_code, label in LANGUAGES:
                    intro_locale = intro_by_key.get((ranking.id, lang_code))
                    track_locale = track_locale_by_key.get((track.id, lang_code))
                    artist_locale = artist_locale_by_key.get((artist.id, lang_code))

                    if lang_code == "en":
                        intro_text = getattr(ranking, "intro", None)
                        intro_mp3 = verified_audio_key(
                            "audio-en",
                            decade_genre_intro_key(
                                program.slug,
                                ranking.ranking,
                            ),
                        )

                        detail_long_text = getattr(track, "detail", None)
                        detail_long_filename = build_detail_filename(track.spotify_track_id)
                        detail_long_key = (
                            key_for("detail", detail_long_filename)
                            if detail_long_filename
                            else None
                        )
                        detail_long_mp3 = verified_audio_key("audio-en", detail_long_key)

                        detail_short_text = getattr(track, "short_detail", None)
                        detail_short_mp3 = verified_audio_key(
                            "audio-en",
                            getattr(track, "short_detail_tts_key", None),
                        )

                        artist_text = getattr(artist, "artist_description", None)
                        artist_filename = build_artist_filename(artist.spotify_artist_id)
                        artist_key = (
                            key_for("artist", artist_filename)
                            if artist_filename
                            else None
                        )
                        artist_mp3 = verified_audio_key("audio-en", artist_key)
                    else:
                        intro_text = getattr(intro_locale, "intro_text", None)
                        bucket = "audio-es" if lang_code == "es" else "audio-ptbr"

                        intro_mp3 = verified_audio_key(
                            bucket,
                            getattr(intro_locale, "tts_key", None),
                        )

                        detail_long_text = getattr(track_locale, "detail_text", None)
                        detail_long_mp3 = verified_audio_key(
                            bucket,
                            getattr(track_locale, "tts_key", None),
                        )

                        detail_short_text = getattr(track_locale, "short_detail_text", None)
                        detail_short_mp3 = verified_audio_key(
                            bucket,
                            getattr(track_locale, "short_detail_tts_key", None),
                        )

                        artist_text = getattr(artist_locale, "artist_description_text", None)
                        artist_mp3 = verified_audio_key(
                            bucket,
                            getattr(artist_locale, "tts_key", None),
                        )

                    pairs = {
                        "Intro": (intro_text, intro_mp3),
                        "D Long": (detail_long_text, detail_long_mp3),
                        "D Short": (detail_short_text, detail_short_mp3),
                        "Artist": (artist_text, artist_mp3),
                    }

                    for item, (text_value, audio_value) in pairs.items():
                        add_count(program_counts, label, item, text_value, audio_value)
                        add_count(grand_counts, label, item, text_value, audio_value)

            lang_scores = {}
            total_ok = 0
            total_possible = 0

            for _code, label in LANGUAGES:
                lang_ok = 0
                lang_total = 0

                for item in ITEMS:
                    c = program_counts[label][item]
                    lang_ok += c["text_ok"] + c["audio_ok"]
                    lang_total += c["text_total"] + c["audio_total"]

                lang_scores[label] = pct(lang_ok, lang_total)
                total_ok += lang_ok
                total_possible += lang_total

            overall = pct(total_ok, total_possible)

            summary_rows.append({
                "name": program.slug,
                "slug": program.slug,
                "tracks": len(rows),
                "scores": lang_scores,
                "overall": overall,
            })

    summary_rows.sort(key=lambda row: row["overall"])

    cards = []
    for _code, label in LANGUAGES:
        lines = []
        for item in ITEMS:
            c = grand_counts[label][item]
            lines.append(f"""
                <div class="summary-line">
                    <strong>{item}</strong>
                    T {c["text_ok"]}/{c["text_total"]}
                    A {c["audio_ok"]}/{c["audio_total"]}
                </div>
            """)

        cards.append(f"""
            <div class="summary-card">
                <h3>{label}</h3>
                {''.join(lines)}
            </div>
        """)

    table_rows = []
    for row in summary_rows:
        en = row["scores"]["English"]
        es = row["scores"]["Spanish"]
        pt = row["scores"]["Portuguese"]
        overall = row["overall"]

        table_rows.append(f"""
            <tr>
                <td>
                    <a href="nostalgia_qa_{html.escape(row["slug"])}.html">
                        {html.escape(row["name"])}
                    </a>
                    <div class="slug">{html.escape(row["slug"])}</div>
                </td>
                <td>{row["tracks"]}</td>
                <td class="{css_class(en)}">{en}%</td>
                <td class="{css_class(es)}">{es}%</td>
                <td class="{css_class(pt)}">{pt}%</td>
                <td class="{css_class(overall)}"><strong>{overall}%</strong></td>
            </tr>
        """)

    page = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Nostalgia QA Summary</title>
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
            color: #555;
            margin-bottom: 22px;
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
            min-width: 230px;
        }}
        .summary-card h3 {{
            margin: 0 0 8px;
        }}
        .summary-line {{
            font-family: Consolas, monospace;
            font-size: 14px;
            line-height: 1.6;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 9px;
            text-align: left;
        }}
        th {{
            background: #222;
            color: white;
        }}
        tr:nth-child(even) {{
            background: #f2f2f2;
        }}
        a {{
            color: #0645ad;
            text-decoration: none;
            font-weight: bold;
        }}
        .slug {{
            font-size: 12px;
            color: #666;
            margin-top: 3px;
        }}
        .good {{
            background: #d9f2d9;
        }}
        .warn {{
            background: #fff3cd;
        }}
        .bad {{
            background: #f8d7da;
        }}
    </style>
</head>
<body>
    <h1>Nostalgia QA Summary</h1>
    <div class="subtitle">
        Worst nostalgia programs appear first. Click a program name to open its drill-down QA page.
    </div>

    <div class="summary">
        {''.join(cards)}
    </div>

    <table>
        <thead>
            <tr>
                <th>Program</th>
                <th>Tracks</th>
                <th>English</th>
                <th>Spanish</th>
                <th>Portuguese</th>
                <th>Overall</th>
            </tr>
        </thead>
        <tbody>
            {''.join(table_rows)}
        </tbody>
    </table>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "nostalgia_qa_summary.html"
    output_path.write_text(page, encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()