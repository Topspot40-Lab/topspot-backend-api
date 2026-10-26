"""Safely remove only excess Collection ranking rows from a PostgreSQL catalog.

The command writes a full JSON rollback snapshot before opening its deleting
transaction.  It deliberately neither issues nor permits DELETE statements
against ``track`` or ``artist``.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text


TARGET_SQL = text("""
    SELECT c.id AS collection_id, c.name AS collection_name, c.slug AS collection_slug,
           ctr.id AS ranking_row_id, ctr.ranking, ctr.track_id,
           t.track_name AS track_title, a.artist_name AS artist,
           (SELECT count(*) FROM track_ranking tr WHERE tr.track_id = ctr.track_id) AS nostalgia_uses,
           (SELECT count(*) FROM collection_track_ranking other_ctr
             WHERE other_ctr.track_id = ctr.track_id AND other_ctr.id <> ctr.id) AS other_collection_uses,
           (SELECT count(*) FROM collection_track_ranking_locale ctrl
             WHERE ctrl.collection_track_ranking_id = ctr.id) AS locale_rows
      FROM collection_track_ranking ctr
      JOIN collection c ON c.id = ctr.collection_id
      JOIN track t ON t.id = ctr.track_id
      JOIN artist a ON a.id = t.artist_id
     WHERE ctr.ranking >= :minimum_rank
     ORDER BY c.slug, ctr.ranking, ctr.id
""")


def postgres_url(env_path: Path) -> str:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("POSTGRES_URL="):
            return line.split("=", 1)[1].strip()
    raise ValueError(f"POSTGRES_URL not found in {env_path}")


def jsonable_rows(rows):
    return [dict(row) for row in rows]


def run(env_path: Path, snapshot_dir: Path, minimum_rank: int = 900) -> tuple[Path, dict]:
    if minimum_rank != 900:
        raise ValueError("This approved cleanup is fixed at Collection ranking >= 900.")
    engine = create_engine(postgres_url(env_path), pool_pre_ping=True)
    with engine.connect() as connection:
        audited_rows = connection.execute(TARGET_SQL, {"minimum_rank": minimum_rank}).mappings().all()
        ranking_ids = [row["ranking_row_id"] for row in audited_rows]
        locale_rows = connection.execute(text("""
            SELECT ctrl.* FROM collection_track_ranking_locale ctrl
             WHERE ctrl.collection_track_ranking_id = ANY(:ranking_ids)
             ORDER BY ctrl.collection_track_ranking_id, ctrl.id
        """), {"ranking_ids": ranking_ids}).mappings().all() if ranking_ids else []
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"collection-ranking-ge-900-{timestamp}.rollback.json"
    snapshot = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scope": "collection_track_ranking rows with ranking >= 900 only",
        "minimum_rank": minimum_rank,
        "audited_count": len(audited_rows),
        "affected_collections": dict(sorted(Counter(row["collection_slug"] for row in audited_rows).items())),
        "rows": jsonable_rows(audited_rows),
        "dependent_collection_ranking_locale_rows": jsonable_rows(locale_rows),
        "verification_note": "Track and artist tables are never deleted or updated by this command.",
    }
    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, default=lambda value: value.isoformat()),
        encoding="utf-8",
    )

    with engine.begin() as connection:
        locked_rows = connection.execute(text("""
            SELECT id, track_id FROM collection_track_ranking
             WHERE ranking >= :minimum_rank ORDER BY id FOR UPDATE
        """), {"minimum_rank": minimum_rank}).mappings().all()
        locked_ids = [row["id"] for row in locked_rows]
        if sorted(locked_ids) != sorted(ranking_ids):
            raise RuntimeError("Collection ranking rows changed after the audit; transaction rolled back.")
        existing_tracks = connection.execute(text("""
            SELECT id FROM track WHERE id = ANY(:track_ids) ORDER BY id
        """), {"track_ids": sorted({row["track_id"] for row in audited_rows})}).scalars().all() if audited_rows else []
        if set(existing_tracks) != {row["track_id"] for row in audited_rows}:
            raise RuntimeError("An audited underlying track is missing; transaction rolled back.")
        result = connection.execute(text("""
            DELETE FROM collection_track_ranking WHERE ranking >= :minimum_rank
        """), {"minimum_rank": minimum_rank})
        if result.rowcount != len(audited_rows):
            raise RuntimeError(f"Deleted {result.rowcount} rows but audited {len(audited_rows)}; transaction rolled back.")
        remaining = connection.execute(text("""
            SELECT count(*) FROM collection_track_ranking WHERE ranking >= :minimum_rank
        """), {"minimum_rank": minimum_rank}).scalar_one()
        if remaining != 0:
            raise RuntimeError(f"{remaining} excess Collection ranking rows remain; transaction rolled back.")
        surviving_tracks = connection.execute(text("""
            SELECT count(*) FROM track WHERE id = ANY(:track_ids)
        """), {"track_ids": sorted({row["track_id"] for row in audited_rows})}).scalar_one() if audited_rows else 0
        if surviving_tracks != len({row["track_id"] for row in audited_rows}):
            raise RuntimeError("Underlying track verification failed; transaction rolled back.")
    report = {
        "snapshot_path": str(snapshot_path), "audited_count": len(audited_rows),
        "deleted_count": len(audited_rows), "remaining_rank_ge_900": 0,
        "underlying_tracks_verified": len({row["track_id"] for row in audited_rows}),
        "affected_collections": snapshot["affected_collections"],
    }
    return snapshot_path, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--snapshot-dir", type=Path, default=Path(os.environ.get("TEMP", ".")) / "topspot40-rollback-snapshots")
    args = parser.parse_args()
    _snapshot, report = run(args.env, args.snapshot_dir)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
