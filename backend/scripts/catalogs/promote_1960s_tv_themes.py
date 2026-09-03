"""Fail-closed production executor for the approved catalog-64 package.

This module deliberately defaults to a local, no-service dry run.  ``--execute``
is the only path that imports database or Storage clients.  It never generates
audio and it has no ElevenLabs dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Protocol

CATALOG_ID = 64
ROOT = Path(__file__).parent / "review_manifests"
PLAN = ROOT / "1960s-tv-themes.production-plan.v1.json"
DRAFTS = ROOT / "1960s-tv-themes.narration-drafts.v1.json"
STAGED = ROOT / "1960s-tv-themes.staged-media.v2.json"
REVALIDATED = ROOT / "1960s-tv-themes.staged-media.v2.revalidated.json"
ADJUDICATION = ROOT / "1960s-tv-themes.manual-adjudication.v2.json"
ADJUDICATION_COMMIT = "daf9779762cf5e72a916f8ba18a5bfcdd8ad78a2"
FINAL_RANKS = tuple(range(1, 39))
ROLLBACK_SNAPSHOT = Path(__file__).parent / "rollback_snapshots" / "1960s-tv-themes.catalog-64.prep.v1.json"


class Storage(Protocol):
    def get(self, bucket: str, key: str) -> bytes: ...
    def put(self, bucket: str, key: str, data: bytes) -> None: ...
    def remove(self, bucket: str, key: str) -> None: ...


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_key(record: dict) -> str:
    if record["kind"] == "intro":
        return f"intro/1960s_tv_themes_{record['rank']:02}.mp3"
    prefix = "short-detail" if record["kind"] == "short_detail" else "detail"
    return f"{prefix}/{record['spotify_track_id']}.mp3"


def _expected_counts(records: list[dict]) -> bool:
    return Counter((r["language"], r["kind"]) for r in records) == {
        ("en", "intro"): 38, ("es-MX", "intro"): 38, ("pt-BR", "intro"): 38,
        ("en", "short_detail"): 15, ("es-MX", "short_detail"): 15, ("pt-BR", "short_detail"): 15,
        ("en", "long_detail"): 15, ("es-MX", "long_detail"): 15, ("pt-BR", "long_detail"): 18,
    }


def load_approved_bundle() -> dict[str, Any]:
    """Validate the immutable local evidence without contacting any service."""
    plan, drafts, staged, revalidated, adjudication = map(_read, (PLAN, DRAFTS, STAGED, REVALIDATED, ADJUDICATION))
    entries, draft_rows, records = plan["approved_entries"], drafts["records"], staged["records"]
    if plan["catalog_id"] != CATALOG_ID or tuple(e["proposed_rank"] for e in entries) != FINAL_RANKS:
        raise ValueError("promotion refused: approved plan is not contiguous ranks 1..38")
    if len(records) != 207 or not _expected_counts(records):
        raise ValueError("promotion refused: staged manifest is not the exact 207-asset bundle")
    drafts_by_id = {(r["rank"], r["language"], r["kind"]): r for r in draft_rows}
    ids = {(r["rank"], r["language"], r["kind"]) for r in records}
    if len(ids) != 207 or ids != set(drafts_by_id):
        raise ValueError("promotion refused: staged identities do not exactly match committed drafts")
    stage_keys, audio_hashes = set(), set()
    for record in records:
        draft = drafts_by_id[(record["rank"], record["language"], record["kind"])]
        if record.get("text_sha256") != draft.get("text_sha256"):
            raise ValueError(f"promotion refused: draft hash mismatch for {record['staging_key']}")
        if not record.get("audio_sha256") or record["audio_sha256"] in audio_hashes:
            raise ValueError(f"promotion refused: absent or duplicate audio hash for {record['staging_key']}")
        if record["staging_key"] in stage_keys:
            raise ValueError("promotion refused: duplicate staging key")
        stage_keys.add(record["staging_key"]); audio_hashes.add(record["audio_sha256"])
    # The revalidation report is intentionally not required to be literally
    # complete: its 85 ASR false positives are accepted only when every key,
    # source-text hash, and audio hash is exactly represented in Gary's
    # committed offline adjudication.
    rev_by_key = {r["staging_key"]: r for r in revalidated["records"]}
    errors = {key: reason for key, reason in revalidated.get("errors", [])}
    automatic = adjudication.get("automatic_pass", [])
    manual = adjudication.get("manual_verified", [])
    adjudicated = automatic + manual
    if (adjudication.get("catalog_id") != CATALOG_ID or not adjudication.get("promotion_gate_pass")
            or len(automatic) != 122 or len(manual) != 85
            or adjudication.get("genuinely_incorrect_or_cross_mapped")
            or adjudication.get("regeneration_keys")):
        raise ValueError("promotion refused: committed manual-adjudication gate is not approved")
    by_key = {r["key"]: r for r in adjudicated}
    if len(by_key) != 207 or set(by_key) != stage_keys or set(errors) != {r["key"] for r in manual}:
        raise ValueError("promotion refused: adjudication does not exactly account for revalidation")
    for record in records:
        evidence, recheck = by_key[record["staging_key"]], rev_by_key.get(record["staging_key"])
        if not recheck or recheck.get("revalidated_audio_sha256") != record["audio_sha256"]:
            raise ValueError(f"promotion refused: revalidated hash differs for {record['staging_key']}")
        if evidence.get("text_sha256") != record["text_sha256"] or evidence.get("audio_sha256") != record["audio_sha256"]:
            raise ValueError(f"promotion refused: adjudication provenance differs for {record['staging_key']}")
    return {"plan": plan, "entries": entries, "drafts": drafts_by_id, "records": records}


def dry_run() -> dict[str, Any]:
    bundle = load_approved_bundle()
    targets = {(r["bucket"], canonical_key(r)) for r in bundle["records"]}
    if len(targets) != 207:
        raise ValueError("promotion refused: canonical target collision")
    snapshot = _read(ROLLBACK_SNAPSHOT)
    if snapshot.get("catalog_id") != CATALOG_ID or snapshot.get("record_count") != 38 or len(snapshot.get("records", [])) != 38:
        raise ValueError("promotion refused: committed catalog-64 rollback snapshot is incomplete")
    return {
        "mode": "dry_run_no_service_calls", "catalog_id": CATALOG_ID,
        "approved_adjudication_commit": ADJUDICATION_COMMIT,
        "assets_to_promote": len(bundle["records"]), "canonical_targets": len(targets),
        "final_ranks": list(FINAL_RANKS), "retained_tracks": 23,
        "retained_detail_mappings": 135, "database_writes": 0, "storage_writes": 0,
    }


def verify_live_api(api_base: str, bundle: dict[str, Any]) -> None:
    """Require the cache-disabled public contract after the transaction commits."""
    import requests
    expected = {entry["proposed_rank"]: entry for entry in bundle["entries"]}
    for language in ("en", "es", "pt-BR"):
        response = requests.get(
            f"{api_base.rstrip('/')}/supabase/decade-genre/get-sequence",
            params={"decade": "1960s", "genre": "tv_themes", "language": language, "v": uuid.uuid4().hex},
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"}, timeout=(10, 45),
        )
        response.raise_for_status()
        rows = response.json().get("tracks", [])
        if len(rows) != 38 or tuple(row.get("rank") for row in rows) != FINAL_RANKS:
            raise ValueError(f"production API refused: {language} does not return contiguous ranks 1..38")
        for row in rows:
            entry = expected[row["rank"]]
            required_urls = (row.get("introUrl"), row.get("shortDetailUrl"), row.get("detailUrl"))
            if (row.get("spotifyTrackId") != entry["spotify_track_id"] or row.get("artistName") != entry["artist"]
                    or not row.get("albumArtwork") or not row.get("artistArtwork") or not all(required_urls)):
                raise ValueError(f"production API refused: incomplete identity/media at {language} rank {row['rank']}")


class SupabaseStorage:
    def __init__(self) -> None:
        from backend.services.supabase_client import supabase
        self.client = supabase

    def get(self, bucket: str, key: str) -> bytes:
        return self.client.storage.from_(bucket).download(key)

    def put(self, bucket: str, key: str, data: bytes) -> None:
        self.client.storage.from_(bucket).upload(key, data, {"content-type": "audio/mpeg", "upsert": "true"})

    def remove(self, bucket: str, key: str) -> None:
        self.client.storage.from_(bucket).remove([key])


def _verify_staged_objects(storage: Storage, records: list[dict]) -> dict[tuple[str, str], bytes]:
    data_by_source = {}
    for record in records:
        data = storage.get(record["bucket"], record["staging_key"])
        if not data or _sha(data) != record["audio_sha256"]:
            raise ValueError(f"promotion refused: staged hash mismatch for {record['staging_key']}")
        data_by_source[(record["bucket"], record["staging_key"])] = data
    return data_by_source


def _backup_and_promote(storage: Storage, records: list[dict], payloads: dict[tuple[str, str], bytes], run_id: str) -> list[dict]:
    backups = []
    for record in records:
        bucket, target = record["bucket"], canonical_key(record)
        backup_key = f"rollback/catalog-64/{run_id}/{target}"
        try:
            old = storage.get(bucket, target)
        except Exception:
            old = None
        if old is not None:
            storage.put(bucket, backup_key, old)
        backups.append({"bucket": bucket, "target": target, "backup_key": backup_key, "existed": old is not None})
        storage.put(bucket, target, payloads[(bucket, record["staging_key"])])
    return backups


def _restore_storage(storage: Storage, backups: list[dict]) -> None:
    for item in reversed(backups):
        if item["existed"]:
            storage.put(item["bucket"], item["target"], storage.get(item["bucket"], item["backup_key"]))
        else:
            storage.remove(item["bucket"], item["target"])


def verify_canonical_storage(storage: Storage, records: list[dict]) -> None:
    """The promoted canonical bytes must be the exact approved staged bytes."""
    for record in records:
        data = storage.get(record["bucket"], canonical_key(record))
        if not data or _sha(data) != record["audio_sha256"]:
            raise ValueError(f"production Storage refused: canonical hash mismatch for {canonical_key(record)}")


def verify_database_projection(session: Any, bundle: dict[str, Any]) -> None:
    """Verify the committed source of truth before any eventually-consistent API."""
    from sqlmodel import select
    from backend.models.dbmodels import Artist, Track, TrackLocale, TrackRanking, TrackRankingLocale
    expected = {entry["proposed_rank"]: entry for entry in bundle["entries"]}
    rows = session.exec(select(TrackRanking, Track, Artist).join(Track).join(Artist).where(TrackRanking.decade_genre_id == CATALOG_ID).order_by(TrackRanking.ranking)).all()
    if len(rows) != 38 or tuple(ranking.ranking for ranking, _, _ in rows) != FINAL_RANKS:
        raise ValueError("production database refused: catalog-64 is not exactly ranks 1..38")
    by_rank = {ranking.ranking: (ranking, track, artist) for ranking, track, artist in rows}
    for rank, entry in expected.items():
        _, track, artist = by_rank[rank]
        if track.spotify_track_id != entry["spotify_track_id"] or artist.artist_name != entry["artist"] or track.artist_id is None:
            raise ValueError(f"production database refused: identity mismatch at rank {rank}")
    for record in bundle["records"]:
        ranking, track, _ = by_rank[record["rank"]]
        draft = bundle["drafts"][(record["rank"], record["language"], record["kind"])]
        if record["kind"] == "intro":
            if record["language"] == "en":
                if ranking.intro != draft["text"]: raise ValueError(f"production database refused: English intro {record['rank']}")
            else:
                code = "es" if record["language"] == "es-MX" else "pt-BR"
                locale = session.exec(select(TrackRankingLocale).where(TrackRankingLocale.track_ranking_id == ranking.id, TrackRankingLocale.language_code == code)).first()
                if not locale or locale.intro_text != draft["text"] or locale.tts_key != canonical_key(record): raise ValueError(f"production database refused: intro mapping {record['rank']}/{code}")
        elif record["language"] == "en":
            if record["kind"] == "short_detail": ok = track.short_detail == draft["text"] and track.short_detail_tts_key == canonical_key(record)
            else: ok = track.detail == draft["text"]
            if not ok: raise ValueError(f"production database refused: English detail mapping {record['rank']}")
        else:
            code = "es" if record["language"] == "es-MX" else "pt-BR"
            locale = session.exec(select(TrackLocale).where(TrackLocale.track_id == track.id, TrackLocale.language_code == code)).first()
            if record["kind"] == "short_detail": ok = locale and locale.short_detail_text == draft["text"] and locale.short_detail_tts_key == canonical_key(record)
            else: ok = locale and locale.detail_text == draft["text"] and locale.tts_key == canonical_key(record)
            if not ok: raise ValueError(f"production database refused: detail mapping {record['rank']}/{code}")


def verify_preapply_snapshot(session: Any) -> None:
    """Require the reviewed sparse source state before any production write."""
    from sqlmodel import select
    from backend.models.dbmodels import TrackRanking
    snapshot = _read(ROLLBACK_SNAPSHOT)
    expected = tuple(sorted(item["ranking"]["ranking"] for item in snapshot["records"]))
    rows = session.exec(select(TrackRanking.ranking).where(TrackRanking.decade_genre_id == CATALOG_ID).order_by(TrackRanking.ranking)).all()
    if tuple(rows) != expected or len(rows) != 38:
        raise ValueError("production database refused: catalog-64 no longer matches the committed pre-apply snapshot")


def _database_snapshot(session: Any) -> dict[str, Any]:
    """Capture only catalog-64 rows and their mutable locale/track fields."""
    from sqlmodel import select
    from backend.models.dbmodels import Track, TrackLocale, TrackRanking, TrackRankingLocale
    pairs = session.exec(select(TrackRanking, Track).join(Track).where(TrackRanking.decade_genre_id == CATALOG_ID)).all()
    rankings = [ranking.model_dump() for ranking, _ in pairs]
    tracks = [track.model_dump() for _, track in pairs]
    ranking_ids, track_ids = [r["id"] for r in rankings], [t["id"] for t in tracks]
    return {
        "rankings": rankings, "tracks": tracks,
        "ranking_locales": [row.model_dump() for row in session.exec(select(TrackRankingLocale).where(TrackRankingLocale.track_ranking_id.in_(ranking_ids))).all()],
        "track_locales": [row.model_dump() for row in session.exec(select(TrackLocale).where(TrackLocale.track_id.in_(track_ids))).all()],
        "track_ids": set(track_ids),
    }


def _restore_database_snapshot(session: Any, snapshot: dict[str, Any], created_track_ids: set[int], created_artist_ids: set[int]) -> None:
    """Compensate a committed catalog-64 change without touching shared rows."""
    from sqlmodel import select
    from backend.models.dbmodels import Artist, Track, TrackLocale, TrackRanking, TrackRankingLocale
    current = session.exec(select(TrackRanking).where(TrackRanking.decade_genre_id == CATALOG_ID)).all()
    current_rank_ids = [row.id for row in current]
    if current_rank_ids:
        for locale in session.exec(select(TrackRankingLocale).where(TrackRankingLocale.track_ranking_id.in_(current_rank_ids))).all():
            session.delete(locale)
    for ranking in current:
        session.delete(ranking)
    # New tracks can only have been created by this executor.  They are removed
    # only after their catalog-64 rankings are gone, and only if no other
    # catalog can reference them.  Existing/shared Track and Artist rows are
    # never deleted.
    for track_id in created_track_ids:
        refs = session.exec(select(TrackRanking).where(TrackRanking.track_id == track_id)).all()
        if not refs:
            track = session.get(Track, track_id)
            if track is not None:
                for locale in session.exec(select(TrackLocale).where(TrackLocale.track_id == track_id)).all():
                    session.delete(locale)
                session.delete(track)
    session.flush()
    for data in snapshot["tracks"]:
        session.merge(Track(**data))
    for data in snapshot["rankings"]:
        session.merge(TrackRanking(**data))
    for data in snapshot["track_locales"]:
        session.merge(TrackLocale(**data))
    for data in snapshot["ranking_locales"]:
        session.merge(TrackRankingLocale(**data))
    session.flush()
    for artist_id in created_artist_ids:
        artist = session.get(Artist, artist_id)
        if artist is not None and not session.exec(select(Track).where(Track.artist_id == artist_id)).first():
            session.delete(artist)
    session.commit()


def apply_narration_mappings(session: Any, final_rows: dict[int, tuple[Any, Any]], bundle: dict[str, Any]) -> None:
    """Map only the 207 planned assets; untouched detail mappings stay intact."""
    from sqlmodel import select
    from backend.models.dbmodels import TrackLocale, TrackRankingLocale
    for record in bundle["records"]:
        ranking, track = final_rows[record["rank"]]
        draft = bundle["drafts"][(record["rank"], record["language"], record["kind"])]
        key, language, bucket = canonical_key(record), record["language"], record["bucket"]
        if record["kind"] == "intro":
            if language == "en":
                ranking.intro = draft["text"]; session.add(ranking)
            else:
                code = "es" if language == "es-MX" else "pt-BR"
                locale = session.exec(select(TrackRankingLocale).where(TrackRankingLocale.track_ranking_id == ranking.id, TrackRankingLocale.language_code == code)).first()
                if locale is None:
                    locale = TrackRankingLocale(track_ranking_id=ranking.id, language_code=code, intro_text=draft["text"])
                locale.intro_text, locale.tts_bucket, locale.tts_key = draft["text"], bucket, key
                session.add(locale)
            continue
        is_short = record["kind"] == "short_detail"
        if language == "en":
            if is_short: track.short_detail, track.short_detail_tts_key = draft["text"], key
            else: track.detail = draft["text"]
            session.add(track)
        else:
            code = "es" if language == "es-MX" else "pt-BR"
            locale = session.exec(select(TrackLocale).where(TrackLocale.track_id == track.id, TrackLocale.language_code == code)).first()
            if locale is None:
                locale = TrackLocale(track_id=track.id, language_code=code, detail_text="")
            if is_short: locale.short_detail_text, locale.short_detail_tts_key = draft["text"], key
            else: locale.detail_text, locale.tts_bucket, locale.tts_key = draft["text"], bucket, key
            session.add(locale)
    session.flush()


def execute(*, approved_commit: str, api_base: str, storage: Storage | None = None) -> dict[str, Any]:
    """The live-only path.  Compensates Storage and rolls back DB on failure."""
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual != approved_commit:
        raise ValueError(f"promotion refused: HEAD {actual} is not approved commit {approved_commit}")
    if subprocess.check_output(["git", "status", "--porcelain"], text=True).strip():
        raise ValueError("promotion refused: working tree is not clean")
    dry_run()  # includes the committed rollback-snapshot completeness gate
    bundle = load_approved_bundle()
    storage = storage or SupabaseStorage()
    payloads = _verify_staged_objects(storage, bundle["records"])
    backups: list[dict] = []
    snapshot: dict[str, Any] | None = None
    created_track_ids: set[int] = set()
    created_artist_ids: set[int] = set()
    committed = False
    from backend.database import get_db_session
    from backend.scripts.catalogs.tv_themes_1960s_apply import apply_catalog_64
    try:
        # Refuse before the first Storage write unless production is precisely
        # the reviewed sparse source state.
        with get_db_session() as preflight_session:
            verify_preapply_snapshot(preflight_session)
        backups = _backup_and_promote(storage, bundle["records"], payloads, uuid.uuid4().hex)
        with get_db_session() as session:
            verify_preapply_snapshot(session)
            snapshot = _database_snapshot(session)
            from sqlmodel import select
            from backend.models.dbmodels import Artist
            before_artists = {row.id for row in session.exec(select(Artist)).all()}
            final_rows = apply_catalog_64(session, bundle["entries"], commit=False)
            apply_narration_mappings(session, final_rows, bundle)
            created_track_ids = {track.id for _, track in final_rows.values() if track.id not in snapshot["track_ids"]}
            created_artist_ids = {track.artist_id for _, track in final_rows.values() if track.artist_id not in before_artists}
            session.commit()
            committed = True
            verify_database_projection(session, bundle)
        verify_canonical_storage(storage, bundle["records"])
    except Exception:
        try:
            if committed and snapshot is not None:
                with get_db_session() as restore_session:
                    _restore_database_snapshot(restore_session, snapshot, created_track_ids, created_artist_ids)
            _restore_storage(storage, backups)
        finally:
            raise
    # The public API is outside this transaction.  A stale response must never
    # compensate an already verified database/Storage commit; callers recheck
    # it after the platform's ordinary cache invalidation or deployment.
    verify_live_api(api_base, bundle)
    return {"catalog_id": CATALOG_ID, "promoted": 207, "rollback_backups": len(backups)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-commit")
    parser.add_argument("--api-base")
    args = parser.parse_args()
    if args.execute and (not args.approved_commit or not args.api_base):
        parser.error("--execute requires --approved-commit and --api-base")
    report = execute(approved_commit=args.approved_commit, api_base=args.api_base) if args.execute else dry_run()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
