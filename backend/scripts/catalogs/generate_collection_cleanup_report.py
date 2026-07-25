from __future__ import annotations

import csv
import html
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine

OUTPUT_DIR = Path("backend/scripts/catalogs/output")
HTML_OUT = OUTPUT_DIR / "collection_cleanup_report.html"
CSV_OUT = OUTPUT_DIR / "collection_cleanup_report.csv"


def is_combo_artist(value: str | None) -> bool:
    value = value or ""
    return "," in value

def norm(value: str | None) -> str:
    return (value or "").strip().lower()

def normalize_title(value: str | None) -> str:
    value = norm(value)
    removals = [
        "when ",
        "the ",
        "a ",
        "an ",
        "theme from ",
        "theme ",
    ]
    for prefix in removals:
        if value.startswith(prefix):
            value = value[len(prefix):]

    value = value.replace("&", "and")
    value = "".join(ch for ch in value if ch.isalnum() or ch.isspace())
    value = " ".join(value.split())
    return value


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sql = text("""
        select
            c.id as collection_id,
            c.slug as collection_slug,
            c.name as collection_name,
            ctr.id as ranking_id,
            ctr.ranking,
            t.id as track_id,
            t.track_name,
            a.id as artist_id,
            a.artist_name,
            t.spotify_track_id,
            t.detail,
            t.short_detail,
            t.short_detail_tts_key,
            a.spotify_artist_id,
            a.artist_description
        from collection_track_ranking ctr
        join collection c on c.id = ctr.collection_id
        join track t on t.id = ctr.track_id
        join artist a on a.id = t.artist_id
        where ctr.ranking <= 45
        order by c.name, ctr.ranking
    """)

    rows_out = []

    with Session(engine) as session:
        rows = session.exec(sql).mappings().all()

        spotify_rows = session.exec(text("""
            select
                t.id as track_id,
                t.track_name,
                a.artist_name,
                t.spotify_track_id
            from track t
            join artist a on a.id = t.artist_id
            where t.spotify_track_id is not null
        """)).mappings().all()

        spotify_lookup = {}
        for s in spotify_rows:
            key = (normalize_title(s["track_name"]), norm(s["artist_name"]))
            spotify_lookup.setdefault(key, []).append(s)
        for row in rows:
            issues = []
            recommendation = []

            duplicate_matches = []
            if not row["spotify_track_id"]:
                duplicate_matches = spotify_lookup.get(
                    (normalize_title(row["track_name"]), norm(row["artist_name"])),
                    []
                )

                if duplicate_matches:
                    issues.append("POSSIBLE_DUPLICATE_TRACK_WITH_SPOTIFY_ID")
                    recommendation.append(
                        "Review duplicate and possibly remap collection_track_ranking.track_id"
                    )
                else:
                    issues.append("MISSING_SPOTIFY_ID")
                    recommendation.append("Search/enrich Spotify track ID")

            if row["detail"] and not row["spotify_track_id"]:
                issues.append("DETAIL_AUDIO_BLOCKED_BY_MISSING_SPOTIFY_ID")

            if row["short_detail"] and not row["short_detail_tts_key"]:
                if row["spotify_track_id"]:
                    issues.append("MISSING_SHORT_DETAIL_MP3")
                    recommendation.append("Generate short-detail MP3")
                else:
                    issues.append("SHORT_DETAIL_AUDIO_BLOCKED_BY_MISSING_SPOTIFY_ID")

            if (
                    row["artist_description"]
                    and not row["spotify_artist_id"]
                    and not is_combo_artist(row["artist_name"])
            ):
                issues.append("ARTIST_AUDIO_BLOCKED_BY_MISSING_SPOTIFY_ARTIST_ID")
                recommendation.append("Enrich artist Spotify ID or merge duplicate artist")

            if not issues:
                continue

            duplicate_text = "; ".join(
                f'{d["track_id"]}: {d["track_name"]} — {d["artist_name"]} ({d["spotify_track_id"]})'
                for d in duplicate_matches
            )

            rows_out.append({
                "collection": row["collection_name"],
                "slug": row["collection_slug"],
                "collection_id": row["collection_id"],
                "ranking": row["ranking"],
                "ranking_id": row["ranking_id"],
                "track_id": row["track_id"],
                "track": row["track_name"],
                "artist_id": row["artist_id"],
                "artist": row["artist_name"],
                "spotify_track_id": row["spotify_track_id"] or "",
                "short_detail_tts_key": row["short_detail_tts_key"] or "",
                "spotify_artist_id": row["spotify_artist_id"] or "",
                "issues": ", ".join(issues),
                "duplicate_matches": duplicate_text,
                "recommendation": "; ".join(dict.fromkeys(recommendation)),
            })

    fieldnames = [
        "collection",
        "slug",
        "collection_id",
        "ranking",
        "ranking_id",
        "track_id",
        "track",
        "artist_id",
        "artist",
        "spotify_track_id",
        "short_detail_tts_key",
        "spotify_artist_id",
        "issues",
        "duplicate_matches",
        "recommendation",
    ]

    with CSV_OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)

    html_rows = "\n".join(
        f"""
        <tr>
            <td>{html.escape(str(r["collection"]))}<br><small>{html.escape(str(r["slug"]))}</small></td>
            <td>{r["ranking"]}</td>
            <td>{r["track_id"]}</td>
            <td>{html.escape(str(r["track"]))}</td>
            <td>{html.escape(str(r["artist"]))}</td>
            <td>{html.escape(str(r["issues"]))}</td>
            <td>{html.escape(str(r["duplicate_matches"]))}</td>
            <td>{html.escape(str(r["recommendation"]))}</td>
        </tr>
        """
        for r in rows_out
    )

    HTML_OUT.write_text(f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Collection Cleanup Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 32px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
        th {{ background: #222; color: white; text-align: left; position: sticky; top: 0; }}
        tr:nth-child(even) {{ background: #f5f5f5; }}
        small {{ color: #666; }}
    </style>
</head>
<body>
    <h1>Collection Cleanup Report</h1>
    <p>English collection issues requiring cleanup.</p>
    <p>Total issue rows: {len(rows_out)}</p>
    <table>
        <tr>
            <th>Collection</th>
            <th>Rank</th>
            <th>Track ID</th>
            <th>Track</th>
            <th>Artist</th>
            <th>Issues</th>
            <th>Duplicate Matches</th>
            <th>Recommendation</th>
        </tr>
        {html_rows}
    </table>
</body>
</html>
""", encoding="utf-8")

    print("Done.")
    print(f"Rows: {len(rows_out)}")
    print(f"HTML: {HTML_OUT}")
    print(f"CSV:  {CSV_OUT}")


if __name__ == "__main__":
    main()