from backend.services.radio_selection import (
    unused_session_candidates,
    unused_source_candidates,
)
from backend.services import artist_radio_sequence


def test_radio_sources_do_not_repeat_until_the_pool_is_exhausted() -> None:
    sources = ["one", "two", "three"]
    used = {"one", "two"}

    assert unused_source_candidates(sources, used, str) == ["three"]
    used.add("three")

    assert unused_source_candidates(sources, used, str) == sources
    assert used == set()


def test_radio_tracks_prefer_unused_session_tracks_without_resetting_history() -> None:
    tracks = [{"id": 1}, {"id": 2}]
    played = {1}

    assert unused_session_candidates(tracks, played, lambda track: track["id"]) == [{"id": 2}]

    played.add(2)
    assert unused_session_candidates(tracks, played, lambda track: track["id"]) == tracks
    assert played == {1, 2}


def test_artist_radio_track_loader_deduplicates_tracks(monkeypatch) -> None:
    rows = [
        {"track_id": 1, "track_name": "One", "artist_id": 9, "artist_name": "Artist"},
        {"track_id": 1, "track_name": "One", "artist_id": 9, "artist_name": "Artist"},
        {"track_id": 2, "track_name": "Two", "artist_id": 9, "artist_name": "Artist"},
        {"track_id": 3, "track_name": "Three", "artist_id": 9, "artist_name": "Artist"},
    ]

    class Result:
        def mappings(self):
            return self

        def all(self):
            return rows

    class Connection:
        def execute(self, *_):
            return Result()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class Engine:
        def connect(self):
            return Connection()

    monkeypatch.setattr(artist_radio_sequence, "engine", Engine())

    tracks = artist_radio_sequence._tracks(9, "rock")

    assert [track["track_id"] for track in tracks] == [1, 2, 3]
