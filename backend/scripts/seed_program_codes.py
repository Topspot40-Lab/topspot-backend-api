"""Idempotently import verified permanent-code mappings; never generate numbers."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any
from sqlalchemy import exists
from sqlmodel import Session, select
from backend.database import engine
from backend.models.collection_models import Collection
from backend.models.dbmodels import Artist, ArtistGenre, Decade, DecadeGenre, Genre, MusicDocuseriesCollection, ProgramCode
from backend.services.program_codes import normalize_program_code

KINDS = {"nostalgia", "collection", "artist_spotlight", "docuseries_group"}
PREFIXES = {"nostalgia": "N", "collection": "C", "artist_spotlight": "A", "docuseries_group": "D"}

def load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("assignments"), list):
        raise ValueError("manifest must be an object with version 1 and an assignments list")
    assignments = payload["assignments"]
    codes = [normalize_program_code(str(item.get("code", ""))) for item in assignments if isinstance(item, dict)]
    if len(codes) != len(assignments) or any(code is None for code in codes) or len(codes) != len(set(codes)):
        raise ValueError("manifest contains duplicate or invalid codes")
    return assignments

def _target_for(session: Session, item: dict[str, Any]) -> tuple[str, int]:
    kind = item.get("kind")
    if kind not in KINDS: raise ValueError(f"{item.get('code')}: unsupported kind {kind!r}")
    code = normalize_program_code(str(item.get("code", "")))
    if not code or code[0] != PREFIXES[kind]: raise ValueError(f"{item.get('code')}: code does not match {kind}")
    target = item.get("target")
    if not isinstance(target, dict): raise ValueError(f"{code}: target must be an object")
    if kind == "nostalgia":
        row = session.exec(select(DecadeGenre.id).join(Decade, DecadeGenre.decade_id == Decade.id).join(Genre, DecadeGenre.genre_id == Genre.id).where(Decade.slug == target.get("decade_slug"), Genre.slug == target.get("genre_slug"))).first(); column = "decade_genre_id"
    elif kind == "collection":
        row = session.exec(select(Collection.id).where(Collection.slug == target.get("slug"))).first(); column = "collection_id"
    elif kind == "artist_spotlight":
        row = session.exec(select(Artist.id).where(Artist.id == target.get("artist_id"))).first(); column = "artist_id"
        if row is not None and session.exec(select(exists().where(ArtistGenre.artist_id == row).where(ArtistGenre.genre_id == Genre.id).where(Genre.slug == "tv_themes"))).one(): raise ValueError(f"{code}: TV Themes artist {row} cannot receive an Artist Spotlight code")
    else:
        row = session.exec(select(MusicDocuseriesCollection.id).where(MusicDocuseriesCollection.slug == target.get("slug"))).first(); column = "music_docuseries_collection_id"
    if row is None: raise ValueError(f"{code}: target does not exist")
    return column, row

def seed(session: Session, assignments: list[dict[str, Any]]) -> dict[str, int]:
    resolved = []; targets: set[tuple[str, int]] = set()
    for item in assignments:
        if not isinstance(item, dict): raise ValueError("manifest assignments must be objects")
        column, target_id = _target_for(session, item); code = normalize_program_code(item["code"]); key = (column, target_id)
        if key in targets: raise ValueError(f"{code}: conflicting duplicate target assignment")
        targets.add(key); resolved.append((code, item["kind"], column, target_id))
    inserted = unchanged = 0
    for code, kind, column, target_id in resolved:
        existing_code = session.get(ProgramCode, code); existing_target = session.exec(select(ProgramCode).where(getattr(ProgramCode, column) == target_id)).first()
        if existing_code:
            if existing_code.program_kind != kind or getattr(existing_code, column) != target_id: raise ValueError(f"{code}: conflicts with its existing database assignment")
            unchanged += 1; continue
        if existing_target: raise ValueError(f"{code}: target is already assigned to {existing_target.code}")
        session.add(ProgramCode(code=code, program_kind=kind, **{column: target_id})); inserted += 1
    session.commit(); return {"inserted": inserted, "unchanged": unchanged}

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--manifest", type=Path, required=True); args = parser.parse_args()
    with Session(engine) as session: result = seed(session, load_manifest(args.manifest))
    print(json.dumps(result, sort_keys=True))
if __name__ == "__main__": main()
