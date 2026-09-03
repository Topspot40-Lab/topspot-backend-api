"""Apply-only, transaction-safe primitive for the approved catalog-64 plan.

This module deliberately has no CLI.  Calling code must separately obtain
production authorization and pass an already-open database session.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json

CATALOG_ID = 64
REPLACED_RANKS = frozenset((4, 21, 37, 38))
REPLACED_SOURCE_RANKS = frozenset((4, 21, 44, 45))
NEW_RANKS = frozenset((1, 2, 5, 9, 14, 17, 20, 27, 28, 30, 31))
RETAINED_RANKS = frozenset((3, 6, 7, 8, 10, 11, 12, 13, 15, 16, 18, 19, 22, 23, 24, 25, 26, 29, 32, 33, 34, 35, 36))
RETAINED_SOURCE_RANKS = frozenset((3, 6, 7, 8, 10, 11, 12, 13, 15, 16, 18, 19, 22, 23, 24, 25, 26, 29, 33, 34, 36, 40, 41))
FINAL_RANKS = tuple(range(1, 39))
PLAN_PATH = Path(__file__).parent / "review_manifests" / "1960s-tv-themes.production-plan.v1.json"


def load_entries() -> list[dict]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    entries = plan["approved_entries"]
    if plan["catalog_id"] != CATALOG_ID or tuple(row["proposed_rank"] for row in entries) != FINAL_RANKS:
        raise ValueError("apply refused: approved catalog-64 plan is incomplete or renumbered")
    if set(row["proposed_rank"] for row in entries if row.get("addition")) != NEW_RANKS:
        raise ValueError("apply refused: new-track set differs from the approved plan")
    return entries


def apply_catalog_64(session: Any, entries: list[dict] | None = None) -> None:
    """Replace only bad/catalog-missing selections; rollback every failure.

    Correct retained Track and Artist rows are neither mutated nor recreated.
    Ranking deletions are limited by ``decade_genre_id == 64``.
    """
    from sqlmodel import select
    from backend.models.dbmodels import Artist, Track, TrackRanking

    entries = entries or load_entries()
    by_rank = {entry["proposed_rank"]: entry for entry in entries}
    if len(by_rank) != 38 or tuple(sorted(by_rank)) != FINAL_RANKS:
        raise ValueError("apply refused: exact 38-rank bundle required")
    try:
        current = session.exec(select(TrackRanking, Track).join(Track).where(TrackRanking.decade_genre_id == CATALOG_ID)).all()
        current_by_rank = {ranking.ranking: (ranking, track) for ranking, track in current}
        if len(current_by_rank) != len(current):
            raise ValueError("apply refused: duplicate catalog-64 ranks require a separately reviewed snapshot")
        # Retained rows must already be correct.  This prevents a broad rewrite
        # from silently recreating a row that should have been preserved.
        for source_rank in RETAINED_SOURCE_RANKS:
            ranking_track = current_by_rank.get(source_rank)
            entry = next(item for item in entries if item["source_rank"] == source_rank)
            if ranking_track is None or ranking_track[1].spotify_track_id != entry["spotify_track_id"]:
                raise ValueError(f"apply refused: retained source rank {source_rank} is not the reviewed Track row")

        desired_tracks: dict[int, Any] = {}
        for rank in FINAL_RANKS:
            entry = by_rank[rank]
            if entry["source_rank"] in RETAINED_SOURCE_RANKS:
                desired_tracks[rank] = current_by_rank[entry["source_rank"]][1]
                continue
            artist = session.exec(select(Artist).where(Artist.artist_name == entry["artist"])).first()
            if artist is None:
                artist = Artist(artist_name=entry["artist"])
                session.add(artist); session.flush()
            if artist.id is None:
                raise ValueError(f"apply refused: artist id missing for rank {rank}")
            track = Track(track_name=entry["track_name"], artist_display_name=entry["artist"], spotify_track_id=entry["spotify_track_id"], artist_id=artist.id, source_type="TV", source_title=entry["program"], source_role="THEME", version_notes=entry["qualification"])
            session.add(track); session.flush()
            if track.id is None or track.artist_id is None:
                raise ValueError(f"apply refused: track identity missing for rank {rank}")
            desired_tracks[rank] = track

        # Preserve the original ranking row at each surviving rank where one
        # exists; delete only excluded catalog-64 rows, then fill open ranks.
        for source_rank, (ranking, _) in current_by_rank.items():
            if source_rank not in RETAINED_SOURCE_RANKS | REPLACED_SOURCE_RANKS:
                session.delete(ranking)
        session.flush()
        # Move surviving rows out of the target range before renumbering, so a
        # database uniqueness constraint can never observe an intermediate
        # collision (for example old 33 becoming new 32).
        for source_rank in RETAINED_SOURCE_RANKS | REPLACED_SOURCE_RANKS:
            current_by_rank[source_rank][0].ranking = source_rank + 100
            session.add(current_by_rank[source_rank][0])
        session.flush()
        for rank in FINAL_RANKS:
            entry = by_rank[rank]
            existing = current_by_rank.get(entry["source_rank"])
            if existing is None:
                session.add(TrackRanking(track_id=desired_tracks[rank].id, decade_genre_id=CATALOG_ID, ranking=rank))
            else:
                existing[0].ranking = rank
                if entry["source_rank"] in REPLACED_SOURCE_RANKS:
                    existing[0].track_id = desired_tracks[rank].id
                session.add(existing[0])
        session.flush()
        final_rows = session.exec(
            select(TrackRanking, Track)
            .join(Track)
            .where(TrackRanking.decade_genre_id == CATALOG_ID)
        ).all()
        final_by_rank = {ranking.ranking: track for ranking, track in final_rows}
        if len(final_rows) != 38 or tuple(sorted(final_by_rank)) != FINAL_RANKS:
            raise ValueError("apply refused: catalog-64 post-apply sequence is not exactly the approved 38 rows")
        if any(track.artist_id is None for track in final_by_rank.values()):
            raise ValueError("apply refused: a final catalog-64 Track has no artist_id")
        session.commit()
    except Exception:
        session.rollback()
        raise
