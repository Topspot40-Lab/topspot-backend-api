import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from backend.database import get_db
from backend.main import app
from backend.models.dbmodels import (
    Artist,
    ArtistGenre,
    Decade,
    DecadeGenre,
    Genre,
    MusicDocuseries,
    MusicDocuseriesCollection,
    ProgramCode,
)
from backend.routers import catalog
from backend.scripts.seed_program_codes import load_manifest, seed
from backend.services.program_codes import get_program_by_code, list_programs, normalize_program_code


@pytest.mark.parametrize(("raw", "canonical"), [("N23", "N-023"), ("n-023", "N-023"), (" N-23 ", "N-023"), ("D999", "D-999")])
def test_normalize_program_code_accepts_unambiguous_variants(raw, canonical):
    assert normalize_program_code(raw) == canonical


@pytest.mark.parametrize("raw", ["N-0000", "X-023", "N-", "23", "N-2-3"])
def test_normalize_program_code_rejects_invalid_forms(raw):
    assert normalize_program_code(raw) is None


@pytest.mark.parametrize(("raw", "canonical"), [("n23", "N-023"), ("d1", "D-001")])
def test_exact_lookup_normalizes_before_database_lookup(monkeypatch, raw, canonical):
    monkeypatch.setattr(catalog, "get_program_by_code", lambda _db, code: {"code": code})
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/catalog/programs/{raw}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"code": canonical}


@pytest.mark.parametrize(("code", "kind", "target"), [
    ("N-001", "nostalgia", {"decade_slug": "1950s", "genre_slug": "country"}),
    ("C-001", "collection", {"slug": "african_american_heritage_favorites"}),
    ("A-001", "artist_spotlight", {"artist_id": 945}),
    ("D-001", "docuseries_story", {"slug": "history_electric_guitar"}),
])
def test_approved_program_codes_resolve_without_program_code_rows(code, kind, target):
    """Printed programs work before the derived ProgramCode table is seeded."""
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/catalog/programs/{code}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"code": code, "kind": kind, "is_active": True, "target": target}


def test_docuseries_lookup_and_search_return_story_and_group_metadata(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'program-codes.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(MusicDocuseriesCollection(id=11, slug="instruments", name="Instruments"))
        session.add(MusicDocuseries(id=71, collection_id=11, slug="electric_guitar", title="The Electric Guitar"))
        session.add(ProgramCode(code="D-998", program_kind="docuseries_story", music_docuseries_id=71))
        session.commit()

        result = get_program_by_code(session, "D-998")
        assert result == {
            "code": "D-998", "kind": "docuseries_story", "is_active": True,
            "name": "The Electric Guitar",
            "target": {"music_docuseries_id": 71, "slug": "electric_guitar", "title": "The Electric Guitar"},
            "group": {"slug": "instruments", "name": "Instruments"},
        }
        assert list_programs(session, "guitar", "docuseries_story") == [result]


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


def test_docuseries_seed_is_idempotent_and_rejects_group_or_duplicate_story(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'program-codes.db'}")
    SQLModel.metadata.create_all(engine)
    assignment = {"code": "D-001", "kind": "docuseries_story", "target": {"slug": "electric_guitar"}}
    with Session(engine) as session:
        session.add(MusicDocuseriesCollection(id=11, slug="instruments", name="Instruments"))
        session.add(MusicDocuseries(id=71, collection_id=11, slug="electric_guitar", title="The Electric Guitar"))
        session.commit()
        assert seed(session, [assignment]) == {"inserted": 1, "unchanged": 0}
        assert seed(session, [assignment]) == {"inserted": 0, "unchanged": 1}
        with pytest.raises(ValueError, match="already assigned"):
            seed(session, [{**assignment, "code": "D-002"}])
        with pytest.raises(ValueError, match="story slug, not a group"):
            seed(session, [{"code": "D-003", "kind": "docuseries_story", "target": {"group_slug": "instruments"}}])


def test_artist_seed_rejects_tv_themes_only_but_allows_retained_artist(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'program-codes.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Genre(id=1, genre_name="TV Themes", slug="tv_themes"),
            Genre(id=2, genre_name="Rock", slug="rock"),
            Artist(id=1, artist_name="TV Only"),
            Artist(id=2, artist_name="Also Rock"),
            ArtistGenre(id=1, artist_id=1, genre_id=1),
            ArtistGenre(id=2, artist_id=2, genre_id=1),
            ArtistGenre(id=3, artist_id=2, genre_id=2),
        ])
        session.commit()
        with pytest.raises(ValueError, match="TV-Themes-only"):
            seed(session, [{"code": "A-001", "kind": "artist_spotlight", "target": {"artist_id": 1}}])
        assert seed(session, [{"code": "A-002", "kind": "artist_spotlight", "target": {"artist_id": 2}}]) == {
            "inserted": 1, "unchanged": 0,
        }


def test_approved_manifest_has_every_expected_code_once():
    manifest = load_manifest(
        Path(__file__).parents[1] / "data" / "program_code_manifest.json",
        require_approved=True,
    )
    assert len(manifest) == 469
    assert {prefix: sum(item["code"].startswith(f"{prefix}-") for item in manifest) for prefix in "NCAD"} == {
        "N": 64, "C": 52, "A": 226, "D": 127,
    }
