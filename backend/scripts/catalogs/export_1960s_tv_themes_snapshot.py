"""Export a non-secret, read-only rollback snapshot for catalog 64.

This utility deliberately performs no INSERT, UPDATE, DELETE, Storage, TTS, or
external-service operation.  The committed result is a review artifact, not a
database backup containing credentials.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Artist, Track, TrackLocale, TrackRanking, TrackRankingLocale

CATALOG_ID = 64
DEFAULT_OUTPUT = Path(__file__).parent / "rollback_snapshots" / "1960s-tv-themes.catalog-64.prep.v1.json"


def _json(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _columns(row: Any) -> dict[str, Any]:
    return {column.name: _json(getattr(row, column.name)) for column in row.__table__.columns}


def export_snapshot(session: Session) -> dict[str, Any]:
    rows = session.exec(
        select(TrackRanking, Track)
        .join(Track, Track.id == TrackRanking.track_id)
        .where(TrackRanking.decade_genre_id == CATALOG_ID)
        .order_by(TrackRanking.ranking)
    ).all()
    records = []
    for ranking, track in rows:
        artist = session.get(Artist, track.artist_id) if track.artist_id is not None else None
        ranking_locales = session.exec(
            select(TrackRankingLocale).where(TrackRankingLocale.track_ranking_id == ranking.id)
        ).all()
        track_locales = session.exec(select(TrackLocale).where(TrackLocale.track_id == track.id)).all()
        records.append({
            "ranking": _columns(ranking),
            "track": _columns(track),
            "artist": _columns(artist) if artist else None,
            "ranking_locales": sorted((_columns(row) for row in ranking_locales), key=lambda row: row["language_code"]),
            "track_locales": sorted((_columns(row) for row in track_locales), key=lambda row: row["language_code"]),
        })
    return {
        "schema_version": 1,
        "catalog_id": CATALOG_ID,
        "purpose": "read-only rollback/reference snapshot; contains no credentials or audio bytes",
        "record_count": len(records),
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    with Session(engine) as session:
        snapshot = export_snapshot(session)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"catalog_id": CATALOG_ID, "record_count": snapshot["record_count"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
