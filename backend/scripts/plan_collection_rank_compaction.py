"""Read-only plan for filling Collection rank gaps with tracks from the tail.

Run from the backend repository root:
    python -m backend.scripts.plan_collection_rank_compaction --output collection-gap-plan.json

The output is a reviewable snapshot. This command never changes the database,
generates speech, or uploads audio. Keep the output private if intro text is private.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_GAPS = {
    "Civil War Songs": [22, 31, 37, 38, 41],
    "Patriotic Favorites": [7, 10, 14],
    "Railroad & Train Songs": [34, 38, 40],
    "Western Heritage Favorites": [22],
    "Bluegrass Favorites": [16, 23, 43],
    "Cowboy Songs & Western Favorites": [24, 41],
    "Crooner Classics": [43],
    "Southern Gospel Favorites": [30, 42, 44],
    "Traditional Hymns": [34, 35, 42],
    "African-American Heritage Favorites": [12],
    "Celtic Favorites": [30],
    "German Heritage Favorites": [19, 21, 22],
    "Italian Favorites": [22],
    "Easy Listening": [36],
    "Motown Magic": [42],
    "One-Hit Wonders": [28],
    "Stage & Screen: Movie Themes": [26, 33, 36],
}

LANGUAGES = ("en", "es", "pt-BR")


def compact_mapping(ranks: list[int]) -> tuple[list[tuple[int, int]], list[int]]:
    """Return (old rank, new rank) moves and missing ranks past the new end.

    Only tracks above the final count move. All existing ranks at or below the
    final count stay in place. This preserves every track and shortens the list.
    """
    if not ranks or len(set(ranks)) != len(ranks) or min(ranks) < 1:
        raise ValueError("Ranking must contain unique positive integers")
    count = len(ranks)
    occupied = set(ranks)
    gaps = [rank for rank in range(1, count + 1) if rank not in occupied]
    sources = sorted(rank for rank in ranks if rank > count)
    if len(gaps) != len(sources):
        raise ValueError("Cannot pair missing positions with tail tracks")
    # Keep relative order among the tail tracks, where possible.
    return list(zip(sources, gaps)), list(range(count + 1, max(ranks) + 1))


def load_rows(connection):
    from sqlalchemy import text

    rankings = connection.execute(text("""
        SELECT c.id AS collection_id, c.name AS collection_name, c.slug,
               ctr.id AS ranking_id, ctr.track_id, ctr.ranking AS rank,
               ctr.intro AS en_intro, t.track_name, t.spotify_track_id,
               a.artist_name
        FROM collection c
        JOIN collection_track_ranking ctr ON ctr.collection_id = c.id
        JOIN track t ON t.id = ctr.track_id
        JOIN artist a ON a.id = t.artist_id
        ORDER BY c.name, ctr.ranking
    """)).mappings().all()
    locales = connection.execute(text("""
        SELECT l.collection_track_ranking_id AS ranking_id, l.lang,
               l.intro_text, l.tts_key
        FROM collection_track_ranking_locale l
        JOIN collection_track_ranking ctr ON ctr.id = l.collection_track_ranking_id
    """)).mappings().all()
    by_id = {}
    for locale in locales:
        by_id.setdefault(locale["ranking_id"], {})[locale["lang"]] = dict(locale)
    return [dict(row, locales=by_id.get(row["ranking_id"], {})) for row in rankings]


def build_plan(rows):
    by_name = {}
    for row in rows:
        by_name.setdefault(row["collection_name"], []).append(row)
    if missing := EXPECTED_GAPS.keys() - by_name.keys():
        raise ValueError(f"Collections absent from DB: {sorted(missing)}")

    programs = []
    for name, expected in EXPECTED_GAPS.items():
        items = by_name[name]
        ranks = [item["rank"] for item in items]
        observed = [rank for rank in range(1, max(ranks) + 1) if rank not in ranks]
        if observed != expected:
            raise ValueError(f"{name}: current gaps {observed}; September 25 snapshot {expected}. Re-audit before proceeding")
        mapping, trailing = compact_mapping(ranks)
        source_by_rank = {item["rank"]: item for item in items}
        moves = []
        for old_rank, new_rank in mapping:
            row = source_by_rank[old_rank]
            locales = row["locales"]
            problems = []
            if not row["spotify_track_id"]:
                problems.append("Missing Spotify track ID")
            if not row["en_intro"]:
                problems.append("Missing English intro text")
            for lang in LANGUAGES[1:]:
                if lang not in locales or not locales[lang]["intro_text"]:
                    problems.append(f"Missing {lang} intro text")
            moves.append({
                "ranking_id": row["ranking_id"], "track_id": row["track_id"],
                "old_rank": old_rank, "new_rank": new_rank,
                "track": row["track_name"], "artist": row["artist_name"],
                "spotify_track_id": row["spotify_track_id"],
                "intros_before": {"en": row["en_intro"], **{
                    lang: locales.get(lang, {}).get("intro_text") for lang in LANGUAGES[1:]
                }},
                "audio_before": {lang: locales.get(lang, {}).get("tts_key") for lang in LANGUAGES[1:]},
                "audio_after": {lang: f"collections-intros/{row['slug']}_{new_rank:02d}.mp3" for lang in LANGUAGES},
                "review_flags": problems,
            })
        programs.append({
            "collection": name, "slug": items[0]["slug"],
            "collection_id": items[0]["collection_id"], "track_count": len(items),
            "old_max_rank": max(ranks), "new_max_rank": len(items),
            "old_gaps": observed, "trailing_gaps_after_compaction": trailing,
            "moves": moves,
        })
    return {"created_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": "Review only; no DB or audio changes", "programs": programs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from backend.database import engine
    with engine.connect() as connection:
        plan = build_plan(load_rows(connection))
    args.output.write_text(json.dumps(plan, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    for program in plan["programs"]:
        print(f"{program['collection']}: {len(program['moves'])} moves; end at #{program['new_max_rank']}")
        for move in program["moves"]:
            print(f"  #{move['old_rank']} -> #{move['new_rank']}: {move['track']} — {move['artist']}")
            for flag in move["review_flags"]:
                print(f"    REVIEW: {flag}")
    print(f"Saved review plan: {args.output}")


if __name__ == "__main__":
    main()
