from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.routers import decade_genre_player
from backend.config.playback_block_config import MAX_TRACKS_PER_BLOCK, MIN_TRACKS_PER_BLOCK
from backend.services import block_builder
from backend.services.all_radio_sequence import filter_radio_buckets


BUCKETS = [
    ("1950s", "blues-jazz"),
    ("1960s", "rock"),
    ("1970s", "country"),
    ("1980s", "blues-jazz"),
]


def test_multiple_genres_restrict_candidates_and_keep_all_eligible_decades() -> None:
    candidates = filter_radio_buckets(
        BUCKETS, frozenset(("blues-jazz", "rock", "country"))
    )

    assert {genre for _, genre in candidates} <= {"blues-jazz", "rock", "country"}
    assert {decade for decade, _ in candidates} == {"1950s", "1960s", "1970s", "1980s"}


def test_one_genre_and_all_genres_preserve_existing_candidate_sets() -> None:
    assert filter_radio_buckets(BUCKETS, frozenset(("rock",))) == [("1960s", "rock")]
    assert filter_radio_buckets(BUCKETS, None) == BUCKETS


def test_existing_track_set_size_behavior_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [(SimpleNamespace(id=index, duration_ms=5 * 60 * 1000),) for index in range(10)]
    monkeypatch.setattr(block_builder.random, "shuffle", lambda _: None)
    monkeypatch.setattr(block_builder.random, "randint", lambda *_: 8 * 60 * 1000)

    block = block_builder.build_track_block(rows)

    assert MIN_TRACKS_PER_BLOCK <= len(block) <= MAX_TRACKS_PER_BLOCK
    assert len(block) == 2


def test_genre_selection_normalizes_deduplicates_and_rejects_invalid_values() -> None:
    assert decade_genre_player.resolve_radio_genre_selection(
        [" Blues-Jazz ", "rock", "blues-jazz"], BUCKETS
    ) == frozenset(("blues-jazz", "rock"))
    assert decade_genre_player.resolve_radio_genre_selection(["ALL"], BUCKETS) is None

    with pytest.raises(HTTPException, match="Invalid or unavailable") as invalid:
        decade_genre_player.resolve_radio_genre_selection(["not-a-genre"], BUCKETS)
    assert invalid.value.status_code == 422

    with pytest.raises(HTTPException, match="one or more") as empty:
        decade_genre_player.resolve_radio_genre_selection([""], BUCKETS)
    assert empty.value.status_code == 422


@pytest.fixture
def radio_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list[dict[str, object]]]:
    captured: list[dict[str, object]] = []

    def fake_get_db() -> Generator[object, None, None]:
        yield object()

    async def fake_start_new_sequence(coroutine: object) -> None:
        frame = coroutine.cr_frame  # type: ignore[attr-defined]
        captured.append({
            "genre_filter": frame.f_locals["genre_filter"],
            "genre_filters": frame.f_locals["genre_filters"],
        })
        coroutine.close()  # type: ignore[attr-defined]

    monkeypatch.setattr(decade_genre_player, "get_db", fake_get_db)
    monkeypatch.setattr(decade_genre_player, "get_max_rank_for_decade_genre", lambda *_: 40)
    monkeypatch.setattr(decade_genre_player, "get_valid_buckets", lambda _: BUCKETS)
    monkeypatch.setattr(decade_genre_player, "start_radio_mode", lambda *_: None)
    monkeypatch.setattr(decade_genre_player, "start_new_sequence", fake_start_new_sequence)

    app = FastAPI()
    app.include_router(decade_genre_player.router)
    app.dependency_overrides[decade_genre_player.bind_request_user] = lambda: SimpleNamespace()
    return TestClient(app), captured


def test_repeated_genres_take_precedence_over_legacy_genre(radio_client) -> None:
    client, captured = radio_client

    response = client.get(
        "/supabase/decade-genre/play-sequence",
        params=[
            ("decade", "ALL"),
            ("genre", "country"),
            ("genres", "blues-jazz"),
            ("genres", "rock"),
            ("genres", "blues-jazz"),
        ],
    )

    assert response.status_code == 200
    assert response.json() == {"status": "started", "mode": "radio_country"}
    assert captured == [{"genre_filter": None, "genre_filters": frozenset(("blues-jazz", "rock"))}]


def test_legacy_all_and_single_genre_requests_remain_unchanged(radio_client) -> None:
    client, captured = radio_client

    all_response = client.get(
        "/supabase/decade-genre/play-sequence", params={"decade": "ALL", "genre": "ALL"}
    )
    single_response = client.get(
        "/supabase/decade-genre/play-sequence", params={"decade": "ALL", "genre": "rock"}
    )

    assert all_response.json() == {"status": "started", "mode": "radio_ALL"}
    assert single_response.json() == {"status": "started", "mode": "radio_rock"}
    assert captured == [
        {"genre_filter": None, "genre_filters": None},
        {"genre_filter": "rock", "genre_filters": None},
    ]


def test_one_selected_genre_and_select_all_use_the_new_contract(radio_client) -> None:
    client, captured = radio_client

    one_genre_response = client.get(
        "/supabase/decade-genre/play-sequence",
        params=[("decade", "ALL"), ("genre", "ALL"), ("genres", "rock")],
    )
    all_genres_response = client.get(
        "/supabase/decade-genre/play-sequence",
        params=[("decade", "ALL"), ("genre", "rock"), ("genres", "ALL")],
    )

    assert one_genre_response.json() == {"status": "started", "mode": "radio_ALL"}
    assert all_genres_response.json() == {"status": "started", "mode": "radio_rock"}
    assert captured == [
        {"genre_filter": None, "genre_filters": frozenset(("rock",))},
        {"genre_filter": None, "genre_filters": None},
    ]


def test_invalid_repeated_genre_returns_422_without_starting_radio(radio_client) -> None:
    client, captured = radio_client

    response = client.get(
        "/supabase/decade-genre/play-sequence",
        params=[("decade", "ALL"), ("genre", "ALL"), ("genres", "not-a-genre")],
    )

    assert response.status_code == 422
    assert captured == []
