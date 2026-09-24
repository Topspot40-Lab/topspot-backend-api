"""Dry-run-by-default backfill for selected ranked tracks' Spotify durations."""
from __future__ import annotations

import argparse
import json
from typing import Any, Iterable

from sqlalchemy import update
from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Track, TrackRanking

PREVIOUSLY_BACKFILLED_RANKING_IDS = (3840, 3841, 3499, 3842, 3843, 3844, 3845, 3846, 3516, 3847, 3848, 3849, 3850, 3539, 3540)
ADDITIONAL_TV_THEMES_RANKING_IDS = tuple(range(3809, 3828)) + (3570,)
TARGET_RANKING_IDS = PREVIOUSLY_BACKFILLED_RANKING_IDS + ADDITIONAL_TV_THEMES_RANKING_IDS
SPOTIFY_SOURCE = "Spotify Web API /v1/tracks (stored canonical spotify_track_id)"
EXCLUDED_SPOTIFY_TRACK_IDS = frozenset({"6fHq9tL4dpxoE0wIgXchEG"})


def load_candidates(session: Session) -> list[dict[str, Any]]:
    rows = session.exec(select(TrackRanking, Track).join(Track, Track.id == TrackRanking.track_id).where(TrackRanking.id.in_(TARGET_RANKING_IDS))).all()
    by_ranking_id = {ranking.id: {"ranking_id": ranking.id, "track_id": track.id, "spotify_track_id": track.spotify_track_id, "current_duration_ms": track.duration_ms} for ranking, track in rows}
    missing = [ranking_id for ranking_id in TARGET_RANKING_IDS if ranking_id not in by_ranking_id]
    if missing:
        raise ValueError(f"missing target rankings: {missing}")
    return [by_ranking_id[ranking_id] for ranking_id in TARGET_RANKING_IDS]


def candidates_requiring_spotify_metadata(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Limit Spotify lookups to still-null, supported target records."""
    return [
        candidate for candidate in candidates
        if candidate["current_duration_ms"] is None
        and candidate["spotify_track_id"] not in EXCLUDED_SPOTIFY_TRACK_IDS
    ]


def fetch_spotify_durations(spotify_track_ids: Iterable[str]) -> dict[str, int]:
    """Fetch canonical IDs through the project's existing Spotipy client."""
    from backend.services.spotify.spotify_lookup import sp
    ids = list(dict.fromkeys(spotify_track_ids))
    durations: dict[str, int] = {}
    for offset in range(0, len(ids), 50):
        for track in sp.tracks(ids[offset : offset + 50])["tracks"]:
            if not track or track["id"] not in ids or not isinstance(track.get("duration_ms"), int) or track["duration_ms"] <= 0:
                raise ValueError("Spotify returned an invalid track or duration")
            durations[track["id"]] = track["duration_ms"]
    if set(durations) != set(ids):
        raise ValueError("Spotify did not return every requested canonical track")
    return durations


def build_review_rows(candidates: list[dict[str, Any]], durations: dict[str, int]) -> list[dict[str, Any]]:
    return [{**candidate, "proposed_duration_ms": durations[candidate["spotify_track_id"]], "source": SPOTIFY_SOURCE} for candidate in candidates]


def apply_null_only_backfill(session: Session, rows: list[dict[str, Any]]) -> int:
    updated = 0
    for row in rows:
        result = session.execute(update(Track).where(Track.id == row["track_id"]).where(Track.spotify_track_id == row["spotify_track_id"]).where(Track.duration_ms.is_(None)).values(duration_ms=row["proposed_duration_ms"]))
        updated += result.rowcount
    session.commit()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write only rows whose duration_ms remains NULL")
    args = parser.parse_args()
    with Session(engine) as session:
        candidates = candidates_requiring_spotify_metadata(load_candidates(session))
        durations = fetch_spotify_durations(row["spotify_track_id"] for row in candidates) if candidates else {}
        rows = build_review_rows(candidates, durations)
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", "rows": rows}, indent=2))
        if args.apply:
            print(json.dumps({"updated": apply_null_only_backfill(session, rows)}))


if __name__ == "__main__":
    main()
