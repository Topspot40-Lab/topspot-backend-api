from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import decade_genre_player


@pytest.fixture
def radio_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, list[list[str] | None]]:
    captured_filters: list[list[str] | None] = []

    def fake_get_db() -> Generator[object, None, None]:
        yield object()

    async def fake_start_new_sequence(coroutine: object) -> None:
        frame = coroutine.cr_frame  # type: ignore[attr-defined]
        captured_filters.append(frame.f_locals["genre_filters"])
        coroutine.close()  # type: ignore[attr-defined]

    monkeypatch.setattr(decade_genre_player, "get_db", fake_get_db)
    monkeypatch.setattr(decade_genre_player, "get_max_rank_for_decade_genre", lambda *_: 40)
    monkeypatch.setattr(decade_genre_player, "start_radio_mode", lambda *_: None)
    monkeypatch.setattr(decade_genre_player, "start_new_sequence", fake_start_new_sequence)

    app = FastAPI()
    app.include_router(decade_genre_player.router)
    app.dependency_overrides[decade_genre_player.bind_request_user] = lambda: SimpleNamespace()
    return TestClient(app), captured_filters


def test_play_sequence_parses_repeated_genres_query_parameters(radio_client) -> None:
    client, captured_filters = radio_client

    response = client.get(
        "/supabase/decade-genre/play-sequence",
        params=[
            ("decade", "ALL"),
            ("genre", "ALL"),
            ("genres", "pop"),
            ("genres", "rock"),
        ],
    )

    assert response.status_code == 200
    assert response.json() == {"status": "started", "mode": "radio_ALL"}
    assert captured_filters == [["pop", "rock"]]


def test_play_sequence_explicit_all_overrides_legacy_scalar_genre(radio_client) -> None:
    client, captured_filters = radio_client

    response = client.get(
        "/supabase/decade-genre/play-sequence",
        params=[("decade", "ALL"), ("genre", "rock"), ("genres", "ALL")],
    )

    assert response.status_code == 200
    assert captured_filters == [None]
