import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from backend.database import get_db
from backend.main import app
from backend.models.dbmodels import Decade, DecadeGenre, Genre, ProgramCode
from backend.routers import catalog
from backend.scripts.seed_program_codes import load_manifest, seed
from backend.services.program_codes import normalize_program_code


@pytest.mark.parametrize(("raw", "canonical"), [("N23", "N-023"), ("n-023", "N-023"), (" N-23 ", "N-023"), ("D999", "D-999")])
def test_normalize_program_code_accepts_unambiguous_variants(raw, canonical):
    assert normalize_program_code(raw) == canonical


@pytest.mark.parametrize("raw", ["N-0000", "X-023", "N-", "23", "N-2-3"])
def test_normalize_program_code_rejects_invalid_forms(raw):
    assert normalize_program_code(raw) is None


def test_exact_lookup_normalizes_before_database_lookup(monkeypatch):
    monkeypatch.setattr(catalog, "get_program_by_code", lambda _db, code: {"code": code})
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get("/api/catalog/programs/n23")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"code": "N-023"}


def test_manifest_rejects_same_code_written_in_two_forms(tmp_path):
    manifest = tmp_path / "duplicate.json"
    manifest.write_text(json.dumps({"version": 1, "assignments": [
        {"code": "N-1", "kind": "nostalgia", "target": {}},
        {"code": "n-001", "kind": "nostalgia", "target": {}},
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_manifest(manifest)


def test_seed_is_idempotent_and_rejects_conflicting_target(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'program-codes.db'}")
    SQLModel.metadata.create_all(engine)
    assignment = {"code": "N-023", "kind": "nostalgia", "target": {"decade_slug": "1950s", "genre_slug": "country"}}
    with Session(engine) as session:
        session.add(Decade(id=1, decade_name="1950s", slug="1950s"))
        session.add(Genre(id=1, genre_name="Country", slug="country"))
        session.add(DecadeGenre(id=1, decade_id=1, genre_id=1))
        session.commit()
        assert seed(session, [assignment]) == {"inserted": 1, "unchanged": 0}
        assert seed(session, [assignment]) == {"inserted": 0, "unchanged": 1}
        with pytest.raises(ValueError, match="already assigned"):
            seed(session, [{**assignment, "code": "N-024"}])
        assert session.get(ProgramCode, "N-023").decade_genre_id == 1
