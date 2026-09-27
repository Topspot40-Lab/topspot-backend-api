"""Read-only live DB check before applying a reviewed Collection gap repair.

    python -m backend.scripts.check_collection_gap_preflight \
        --plan collection-gap-reviewed.json --output collection-gap-preflight.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from backend.scripts.stage_collection_gap_intros import read_plan


def inspect(plan: dict, connection) -> dict:
    problems = []
    artist_checks = []
    for program in plan["programs"]:
        rows = connection.execute(text("""
            SELECT ctr.id, ctr.ranking, ctr.intro, ctr.track_id, t.spotify_track_id,
                   a.artist_name
              FROM collection_track_ranking ctr
              JOIN track t ON t.id = ctr.track_id
              JOIN artist a ON a.id = t.artist_id
             WHERE ctr.collection_id = :cid ORDER BY ctr.ranking
        """), {"cid": program["collection_id"]}).mappings().all()
        ranks = [row["ranking"] for row in rows]
        observed_gaps = [r for r in range(1, max(ranks, default=0) + 1) if r not in ranks]
        if len(rows) != program["track_count"] or observed_gaps != program["old_gaps"] or max(ranks, default=0) != program["old_max_rank"]:
            problems.append(f"{program['collection']}: ranking list changed since plan")
        by_id = {row["id"]: row for row in rows}
        for move in program["moves"]:
            rid = move["ranking_id"]
            row = by_id.get(rid)
            if row is None:
                problems.append(f"Ranking {rid} disappeared")
                continue
            if (row["ranking"], row["track_id"], row["spotify_track_id"], row["intro"]) != (
                move["old_rank"], move["track_id"], move["spotify_track_id"], move["intros_before"]["en"]
            ):
                problems.append(f"Ranking {rid} differs from reviewed snapshot")
            locales = connection.execute(text("""
                SELECT lang, intro_text, tts_key FROM collection_track_ranking_locale
                 WHERE collection_track_ranking_id = :rid
            """), {"rid": rid}).mappings().all()
            by_lang = {loc["lang"]: loc for loc in locales}
            for lang in ("es", "pt-BR"):
                loc = by_lang.get(lang)
                if not loc or (loc["intro_text"], loc["tts_key"]) != (move["intros_before"][lang], move["audio_before"][lang]):
                    problems.append(f"Ranking {rid}: {lang} locale changed since review")
            correction = move.get("artist_correction_required")
            if correction:
                matches = connection.execute(text("""
                    SELECT id, artist_name FROM artist
                     WHERE lower(artist_name) = lower(:name) ORDER BY id
                """), {"name": correction["new_artist"]}).mappings().all()
                collection_uses = connection.execute(text("""
                    SELECT c.name, ctr.ranking, ctr.intro
                      FROM collection_track_ranking ctr JOIN collection c ON c.id=ctr.collection_id
                     WHERE ctr.track_id=:tid ORDER BY c.name, ctr.ranking
                """), {"tid": move["track_id"]}).mappings().all()
                nostalgia_uses = connection.execute(text("""
                    SELECT count(*) FROM track_ranking WHERE track_id=:tid
                """), {"tid": move["track_id"]}).scalar_one()
                artist_checks.append({
                    "ranking_id": rid, "track_id": move["track_id"],
                    "database_artist": row["artist_name"],
                    "spotify_artist": correction["new_artist"],
                    "candidate_artist_rows": [dict(m) for m in matches],
                    "collection_uses": [dict(u) for u in collection_uses],
                    "nostalgia_use_count": nostalgia_uses,
                })
                if row["artist_name"].casefold() != correction["old_artist"].casefold():
                    problems.append(f"Ranking {rid}: current artist changed")
    return {"status": "ready_for_audio_staging" if not problems else "needs_review",
            "problems": problems, "artist_checks": artist_checks,
            "collections": len(plan["programs"]),
            "moved_tracks": sum(len(p["moves"]) for p in plan["programs"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from backend.database import engine
    with engine.connect() as connection:
        result = inspect(read_plan(args.plan), connection)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{result['status']}: {result['moved_tracks']} moves; {len(result['problems'])} snapshot conflicts")
    for check in result["artist_checks"]:
        print(f"Artist mismatch at ranking {check['ranking_id']}: DB {check['database_artist']}; Spotify {check['spotify_artist']}")
        print(f"Track used by {len(check['collection_uses'])} Collections and {check['nostalgia_use_count']} Nostalgia rankings")
    print(f"Saved {args.output}")
    if result["problems"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
