from __future__ import annotations

import csv
import html
from pathlib import Path

from sqlalchemy import text

from backend.database import engine

OUTPUT_DIR = Path("backend/scripts/catalogs/output")
CSV_OUT = OUTPUT_DIR / "collection_replacement_report.csv"
HTML_OUT = OUTPUT_DIR / "collection_replacement_report.html"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sql = text("""
        with bad_tracks as (
            select
                c.id as collection_id,
                c.name as collection_name,
                c.slug,
                ctr.id as bad_ranking_id,
                ctr.ranking as bad_rank,
                t.id as bad_track_id,
                t.track_name as bad_track,
                a.artist_name as bad_artist
            from collection_track_ranking ctr
            join collection c on c.id = ctr.collection_id
            join track t on t.id = ctr.track_id
            join artist a on a.id = t.artist_id
            where t.spotify_track_id is null
        ),
        candidates as (
            select
                c.id as collection_id,
                ctr.id as candidate_ranking_id,
                ctr.ranking as candidate_rank,
                t.id as candidate_track_id,
                t.track_name as candidate_track,
                a.artist_name as candidate_artist,
                t.spotify_track_id,
                row_number() over (
                    partition by c.id
                    order by ctr.ranking
                ) as candidate_order
            from collection_track_ranking ctr
            join collection c on c.id = ctr.collection_id
            join track t on t.id = ctr.track_id
            join artist a on a.id = t.artist_id
            where t.spotify_track_id is not null
              and ctr.ranking > 40
        )
        select
            b.collection_name,
            b.slug,
            b.collection_id,
            b.bad_ranking_id,
            b.bad_rank,
            b.bad_track_id,
            b.bad_track,
            b.bad_artist,
            c.candidate_ranking_id,
            c.candidate_rank,
            c.candidate_track_id,
            c.candidate_track,
            c.candidate_artist,
            c.spotify_track_id
        from bad_tracks b
        left join candidates c
            on c.collection_id = b.collection_id
           and c.candidate_order = 1
        order by b.collection_name, b.bad_rank
    """)

    with engine.begin() as conn:
        rows = conn.execute(sql).mappings().all()

    fieldnames = [
        "collection_name",
        "slug",
        "collection_id",
        "bad_ranking_id",
        "bad_rank",
        "bad_track_id",
        "bad_track",
        "bad_artist",
        "candidate_ranking_id",
        "candidate_rank",
        "candidate_track_id",
        "candidate_track",
        "candidate_artist",
        "spotify_track_id",
    ]

    with CSV_OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    html_rows = "\n".join(
        f"""
        <tr>
            <td>{html.escape(str(r["collection_name"]))}<br><small>{html.escape(str(r["slug"]))}</small></td>
            <td>{r["bad_rank"]}</td>
            <td>{r["bad_track_id"]}</td>
            <td>{html.escape(str(r["bad_track"]))}</td>
            <td>{html.escape(str(r["bad_artist"]))}</td>
            <td>{r["candidate_rank"] or ""}</td>
            <td>{r["candidate_track_id"] or ""}</td>
            <td>{html.escape(str(r["candidate_track"] or ""))}</td>
            <td>{html.escape(str(r["candidate_artist"] or ""))}</td>
        </tr>
        """
        for r in rows
    )

    HTML_OUT.write_text(f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Collection Replacement Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 32px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
        th {{ background: #222; color: white; position: sticky; top: 0; }}
        tr:nth-child(even) {{ background: #f5f5f5; }}
        small {{ color: #666; }}
    </style>
</head>
<body>
    <h1>Collection Replacement Report</h1>
    <p>Missing Spotify tracks with suggested replacement candidates from rank 41+ in the same collection.</p>
    <p>Total rows: {len(rows)}</p>
    <table>
        <tr>
            <th>Collection</th>
            <th>Bad Rank</th>
            <th>Bad Track ID</th>
            <th>Bad Track</th>
            <th>Bad Artist</th>
            <th>Candidate Rank</th>
            <th>Candidate Track ID</th>
            <th>Candidate Track</th>
            <th>Candidate Artist</th>
        </tr>
        {html_rows}
    </table>
</body>
</html>
""", encoding="utf-8")

    print("Done.")
    print(f"Rows: {len(rows)}")
    print(f"CSV:  {CSV_OUT}")
    print(f"HTML: {HTML_OUT}")


if __name__ == "__main__":
    main()