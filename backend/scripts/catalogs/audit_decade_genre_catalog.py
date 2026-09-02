"""Read-only catalog review report for a single nostalgia program.

This module intentionally contains no mutation SQL and no storage mutation calls.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

# Load configuration before importing modules that instantiate Supabase clients.
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

LANGUAGES = ("en", "es", "pt-BR")
BUCKETS = {"en": "audio-en", "es": "audio-es", "pt-BR": "audio-ptbr"}
OUTPUT_DIR = Path("backend/scripts/catalogs/output/catalog_audits")


def word_count(value: object) -> int:
    return len(value.split()) if isinstance(value, str) and value.strip() else 0


def length_warnings(intro_words: int, long_words: int, short_words: int) -> list[str]:
    warnings = []
    if intro_words and not 6 <= intro_words <= 30:
        warnings.append("intro outside flexible 6–30-word review range")
    if short_words and not 15 <= short_words <= 55:
        warnings.append("short detail outside flexible 15–55-word review range")
    if long_words and not 55 <= long_words <= 140:
        warnings.append("long detail outside flexible 55–140-word review range")
    return warnings


def expected_audio_keys(row: dict[str, Any], lang: str) -> dict[str, str | None]:
    """Return existing QA-compatible bucket/key locations; do not create anything."""
    if lang == "en":
        slug = row["program_slug"].replace("-", "_")
        return {
            "intro_mp3": f"intro/{slug}_{row['ranking']:02d}.mp3",
            "long_detail_mp3": f"detail/{row['spotify_track_id']}.mp3" if row.get("spotify_track_id") else None,
            "short_detail_mp3": row.get("short_detail_tts_key"),
            "artist_mp3": f"artist/{row['spotify_artist_id']}.mp3" if row.get("spotify_artist_id") else None,
        }
    suffix = "es" if lang == "es" else "ptbr"
    return {
        "intro_mp3": row.get(f"intro_tts_key_{suffix}"),
        "long_detail_mp3": row.get(f"detail_tts_key_{suffix}"),
        "short_detail_mp3": row.get(f"short_detail_tts_key_{suffix}"),
        "artist_mp3": row.get(f"artist_tts_key_{suffix}"),
    }


def decision_by_rank(manifest: dict[str, Any]) -> dict[int, str]:
    return {int(item["rank"]): item["decision"] for item in manifest.get("rank_decisions", [])}


def build_report(
    program: dict[str, Any], rows: list[dict[str, Any]], manifest: dict[str, Any],
    object_exists: Callable[[str, str], bool],
) -> dict[str, Any]:
    """Build a serializable report from read-only query results and storage checks."""
    ranks = [row["ranking"] for row in rows]
    counts = Counter(ranks)
    duplicates = sorted(rank for rank, count in counts.items() if count > 1)
    present = set(ranks)
    internal_missing = list(range(min(present), max(present) + 1)) if present else []
    internal_missing = [rank for rank in internal_missing if rank not in present]
    decisions = decision_by_rank(manifest)
    report_rows = []

    for row in rows:
        row = dict(row)
        languages: dict[str, Any] = {}
        for lang in LANGUAGES:
            suffix = "" if lang == "en" else ("es" if lang == "es" else "ptbr")
            intro = row.get("intro") if lang == "en" else row.get(f"intro_text_{suffix}")
            long_detail = row.get("detail") if lang == "en" else row.get(f"detail_text_{suffix}")
            short_detail = row.get("short_detail") if lang == "en" else row.get(f"short_detail_text_{suffix}")
            artist_description = row.get("artist_description") if lang == "en" else row.get(f"artist_description_text_{suffix}")
            texts = {
                "intro_text": bool(intro), "long_detail_text": bool(long_detail),
                "short_detail_text": bool(short_detail), "artist_description_text": bool(artist_description),
            }
            keys = expected_audio_keys(row, lang)
            audio = {name: bool(key and object_exists(BUCKETS[lang], key)) for name, key in keys.items()}
            languages[lang] = {
                "texts": texts, "audio": audio, "audio_keys": keys,
                "word_counts": {"intro": word_count(intro), "long_detail": word_count(long_detail),
                                "short_detail": word_count(short_detail), "artist_description": word_count(artist_description)},
                "length_review_warnings": length_warnings(word_count(intro), word_count(long_detail), word_count(short_detail)),
            }
        missing_source = not any(row.get(field) for field in ("source_type", "source_title", "years_on_air", "source_role", "version_notes"))
        suspicious_source = missing_source or not row.get("source_type") or not row.get("source_title")
        valid_artist = bool(row.get("artist_id"))
        usable = valid_artist and bool(row.get("spotify_track_id")) and bool(row.get("spotify_artist_id"))
        report_rows.append({
            "rank": row["ranking"], "track_id": row.get("track_id"), "track_name": row.get("track_name"),
            "artist_id": row.get("artist_id"), "artist_name": row.get("artist_name"),
            "spotify_track_id_present": bool(row.get("spotify_track_id")),
            "spotify_artist_id_present": bool(row.get("spotify_artist_id")),
            "missing_artist_association": not valid_artist, "currently_playable": usable,
            "source_metadata": {field: row.get(field) for field in ("source_type", "source_title", "years_on_air", "source_role", "version_notes")},
            "source_metadata_suspicious": suspicious_source,
            "shared_with_other_programs": int(row.get("track_program_count") or 0) > 1,
            "shared_program_count": int(row.get("track_program_count") or 0),
            "artist_shared_elsewhere": int(row.get("artist_program_count") or 0) > 1,
            "artist_program_count": int(row.get("artist_program_count") or 0),
            "gary_decision": decisions.get(row["ranking"], "unreviewed/incomplete"), "languages": languages,
        })
    return {
        "schema_version": "catalog-review-report/v1", "generated_at": datetime.now(UTC).isoformat(),
        "read_only": True, "program": program, "manifest_version": manifest.get("manifest_version"),
        "rank_sequence": {"current": ranks, "internal_missing": internal_missing, "duplicate_ranks": duplicates},
        "counts": {"database_rows": len(rows), "currently_playable_rows": sum(row["currently_playable"] for row in report_rows),
                   "incomplete_rows": sum(not row["currently_playable"] for row in report_rows)},
        "rows": report_rows,
    }


def load_catalog_rows(session: Any, slug: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from sqlalchemy import text
    program = session.execute(text("SELECT id, slug FROM public.decade_genre WHERE slug = :slug"), {"slug": slug}).mappings().first()
    if not program:
        raise ValueError(f"DecadeGenre not found: {slug}")
    sql = text("""
        WITH target AS (SELECT id, slug FROM public.decade_genre WHERE id = :program_id),
        track_usage AS (SELECT tr.track_id, count(DISTINCT tr.decade_genre_id) AS track_program_count FROM public.track_ranking tr GROUP BY tr.track_id),
        artist_usage AS (SELECT t.artist_id, count(DISTINCT tr.decade_genre_id) AS artist_program_count FROM public.track_ranking tr JOIN public.track t ON t.id = tr.track_id WHERE t.artist_id IS NOT NULL GROUP BY t.artist_id)
        SELECT tr.ranking, tr.track_id, tr.intro, t.track_name, t.spotify_track_id, t.artist_id, t.detail, t.short_detail, t.short_detail_tts_key,
               t.source_type, t.source_title, t.years_on_air, t.source_role, t.version_notes,
               a.artist_name, a.spotify_artist_id, a.artist_description, COALESCE(tu.track_program_count, 0) AS track_program_count, COALESCE(au.artist_program_count, 0) AS artist_program_count,
               ies.intro_text AS intro_text_es, ies.tts_key AS intro_tts_key_es, ipt.intro_text AS intro_text_ptbr, ipt.tts_key AS intro_tts_key_ptbr,
               tles.detail_text AS detail_text_es, tles.short_detail_text AS short_detail_text_es, tles.tts_key AS detail_tts_key_es, tles.short_detail_tts_key AS short_detail_tts_key_es,
               tlpt.detail_text AS detail_text_ptbr, tlpt.short_detail_text AS short_detail_text_ptbr, tlpt.tts_key AS detail_tts_key_ptbr, tlpt.short_detail_tts_key AS short_detail_tts_key_ptbr,
               ales.artist_description_text AS artist_description_text_es, ales.tts_key AS artist_tts_key_es, alpt.artist_description_text AS artist_description_text_ptbr, alpt.tts_key AS artist_tts_key_ptbr,
               target.slug AS program_slug
        FROM public.track_ranking tr JOIN target ON target.id = tr.decade_genre_id
        LEFT JOIN public.track t ON t.id = tr.track_id LEFT JOIN public.artist a ON a.id = t.artist_id
        LEFT JOIN track_usage tu ON tu.track_id = tr.track_id LEFT JOIN artist_usage au ON au.artist_id = t.artist_id
        LEFT JOIN public.track_ranking_locale ies ON ies.track_ranking_id = tr.id AND ies.language_code = 'es'
        LEFT JOIN public.track_ranking_locale ipt ON ipt.track_ranking_id = tr.id AND ipt.language_code = 'pt-BR'
        LEFT JOIN public.track_locale tles ON tles.track_id = t.id AND tles.language_code = 'es'
        LEFT JOIN public.track_locale tlpt ON tlpt.track_id = t.id AND tlpt.language_code = 'pt-BR'
        LEFT JOIN public.artist_locale ales ON ales.artist_id = a.id AND ales.language_code = 'es'
        LEFT JOIN public.artist_locale alpt ON alpt.artist_id = a.id AND alpt.language_code = 'pt-BR'
        ORDER BY tr.ranking
    """)
    rows = [dict(row) for row in session.execute(sql, {"program_id": program["id"]}).mappings()]
    return dict(program), rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only decade/genre catalog audit.")
    parser.add_argument("slug")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    from sqlmodel import Session
    from backend.database import engine
    from backend.services.supabase_storage import object_exists_cached
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    with Session(engine) as session:
        program, rows = load_catalog_rows(session, args.slug)
    report = build_report(program, rows, manifest, object_exists_cached)
    output = args.output or OUTPUT_DIR / f"catalog_audit_{args.slug}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
