"""Lookup and presentation helpers for permanent public program codes."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlmodel import Session, select

from backend.models.collection_models import Collection
from backend.models.dbmodels import (
    Artist,
    Decade,
    DecadeGenre,
    Genre,
    MusicDocuseries,
    MusicDocuseriesCollection,
    ProgramCode,
)

_CODE_INPUT = re.compile(r"^\s*([ncad])\s*-?\s*(\d{1,3})\s*$", re.IGNORECASE)
_APPROVED_MANIFEST_PATH = Path(__file__).parents[1] / "data" / "program_code_manifest.json"


def _load_approved_programs() -> dict[str, dict[str, Any]]:
    """Load public code assignments independently of the DB projection."""
    payload = json.loads(_APPROVED_MANIFEST_PATH.read_text(encoding="utf-8"))
    if payload.get("approved") is not True or not isinstance(payload.get("assignments"), list):
        raise ValueError("approved program code manifest is invalid")

    programs: dict[str, dict[str, Any]] = {}
    for assignment in payload["assignments"]:
        if not isinstance(assignment, dict):
            raise ValueError("approved program code manifest contains an invalid assignment")
        code = normalize_program_code(str(assignment.get("code", "")))
        kind = assignment.get("kind")
        target = assignment.get("target")
        if (
            not code
            or kind not in {"nostalgia", "collection", "artist_spotlight", "docuseries_story"}
            or not isinstance(target, dict)
            or code in programs
        ):
            raise ValueError("approved program code manifest contains an invalid assignment")
        programs[code] = {"code": code, "kind": kind, "is_active": True, "target": target}
    return programs


def normalize_program_code(value: str) -> str | None:
    """Return a canonical code, accepting unambiguous forms such as ``n23``."""
    match = _CODE_INPUT.fullmatch(value or "")
    if not match:
        return None
    number = int(match.group(2))
    if number > 999:
        return None
    return f"{match.group(1).upper()}-{number:03d}"


_APPROVED_PROGRAMS = _load_approved_programs()


def _program_query():
    return (
        select(ProgramCode, Decade, Genre, Collection, Artist, MusicDocuseries, MusicDocuseriesCollection)
        .join(DecadeGenre, ProgramCode.decade_genre_id == DecadeGenre.id, isouter=True)
        .join(Decade, DecadeGenre.decade_id == Decade.id, isouter=True)
        .join(Genre, DecadeGenre.genre_id == Genre.id, isouter=True)
        .join(Collection, ProgramCode.collection_id == Collection.id, isouter=True)
        .join(Artist, ProgramCode.artist_id == Artist.id, isouter=True)
        .join(MusicDocuseries, ProgramCode.music_docuseries_id == MusicDocuseries.id, isouter=True)
        .join(MusicDocuseriesCollection, MusicDocuseries.collection_id == MusicDocuseriesCollection.id, isouter=True)
    )


def serialize_program(row: tuple[Any, ...]) -> dict[str, Any]:
    code, decade, genre, collection, artist, docuseries_story, docuseries_group = row
    result: dict[str, Any] = {"code": code.code, "kind": code.program_kind, "is_active": code.is_active}
    if code.program_kind == "nostalgia":
        result.update({"name": f"{decade.decade_name} {genre.genre_name}", "target": {"decade_slug": decade.slug, "genre_slug": genre.slug}})
    elif code.program_kind == "collection":
        result.update({"name": collection.name, "target": {"slug": collection.slug}})
    elif code.program_kind == "artist_spotlight":
        result.update({"name": artist.artist_name, "target": {"artist_id": artist.id}})
    else:
        result.update({
            "name": docuseries_story.title,
            "target": {
                "music_docuseries_id": docuseries_story.id,
                "slug": docuseries_story.slug,
                "title": docuseries_story.title,
            },
            "group": {"slug": docuseries_group.slug, "name": docuseries_group.name},
        })
    return result


def get_program_by_code(session: Session, canonical_code: str) -> dict[str, Any] | None:
    # The manifest is authoritative; the ProgramCode table is a seedable,
    # derived projection and may legitimately be empty on a fresh deployment.
    approved_program = _APPROVED_PROGRAMS.get(canonical_code)
    if approved_program:
        return approved_program
    row = session.exec(_program_query().where(ProgramCode.code == canonical_code).where(ProgramCode.is_active == True)).first()  # noqa: E712
    return serialize_program(row) if row else None


def list_programs(session: Session, query: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    statement = _program_query().where(ProgramCode.is_active == True)  # noqa: E712
    if kind:
        statement = statement.where(ProgramCode.program_kind == kind)
    if query and query.strip():
        pattern = f"%{query.strip()}%"
        statement = statement.where(or_(ProgramCode.code.ilike(pattern), Decade.decade_name.ilike(pattern), Genre.genre_name.ilike(pattern), Collection.name.ilike(pattern), Artist.artist_name.ilike(pattern), MusicDocuseries.slug.ilike(pattern), MusicDocuseries.title.ilike(pattern), MusicDocuseriesCollection.name.ilike(pattern)))
    return [serialize_program(row) for row in session.exec(statement.order_by(ProgramCode.code)).all()]
