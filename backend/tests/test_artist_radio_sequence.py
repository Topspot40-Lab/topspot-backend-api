import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import artist_radio_sequence as sequence
from backend.state.playback_runtime import bind_current_task, bind_request_user, get_runtime_for_user
from backend.state.playback_state import get_status as get_playback_status


def test_artist_radio_allow_list_is_the_seven_non_tv_genres():
    assert sequence.ALLOWED_GENRES == (
        "country", "pop", "rock", "rnb_soul", "latin_global", "blues_jazz", "folk_acoustic",
    )
    assert "tv_themes" not in sequence.ALLOWED_GENRES


def _eligible_artist(artist_id: int, genre_slug: str) -> dict:
    return {
        "artist_id": artist_id,
        "artist_name": f"{genre_slug.title()} {artist_id}",
        "genre_slug": genre_slug,
    }


def test_artist_radio_selector_uses_the_complete_requested_genre_pool_not_database_position_zero():
    database_order = [
        _eligible_artist(1, "country"),
        _eligible_artist(2, "country"),
        _eligible_artist(3, "pop"),
    ]

    def reverse(items):
        items.reverse()

    chosen = sequence.choose_artist_for_set(
        database_order,
        "country",
        shuffle=reverse,
    )

    assert chosen["artist_id"] == 2
    assert chosen["genre_slug"] == "country"


def test_artist_radio_selector_uses_each_eligible_artist_once_before_resetting_pool():
    pool = {
        artist["artist_id"]: artist
        for artist in [
            _eligible_artist(1, "country"),
            _eligible_artist(2, "country"),
            _eligible_artist(3, "pop"),
        ]
    }
    played_artists: set[int] = set()
    chosen_ids: list[int] = []

    # This injected shuffle produces a deterministic alternate order while
    # exercising the same unplayed-candidate selection contract as the runner.
    def reverse(items):
        items.reverse()

    for wanted in ("country", "country", "pop"):
        available = [
            artist for artist in pool.values()
            if artist["artist_id"] not in played_artists
        ]
        chosen = sequence.choose_artist_for_set(available, wanted, shuffle=reverse)
        chosen_ids.append(chosen["artist_id"])
        played_artists.add(chosen["artist_id"])

    assert chosen_ids == [2, 1, 3]
    assert len(set(chosen_ids)) == len(pool)
    assert all(pool[artist_id]["genre_slug"] == wanted for artist_id, wanted in zip(chosen_ids, ("country", "country", "pop")))


@pytest.mark.parametrize("genre", ["tv_themes", "not_a_genre"])
def test_artist_radio_rejects_manual_unsupported_genres(genre):
    app.dependency_overrides[bind_request_user] = lambda: None
    try:
        response = TestClient(app).post("/artist-spotlight/play-radio", params={"genre": genre})
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_unresolvable_narration_reference_is_skipped_without_waiting(monkeypatch):
    monkeypatch.setattr(sequence, "resolve_audio_ref", lambda *_: (_ for _ in ()).throw(RuntimeError("bad asset")))
    track = {"ranking": 1, "ranking_id": 7, "track_name": "Song", "artist_name": "Artist"}
    assert asyncio.run(sequence._narrate("test-artist-radio", "artist", track, {}, "audio-en", "artist/a.mp3")) is False


def test_http_artist_radio_progression_through_second_artist(monkeypatch):
    """Registered HTTP routes drive artist -> detail -> track Artist Radio sets."""
    user_id = "test:http-artist-radio"

    async def bind_test_user():
        return bind_current_task(user_id)

    artists = [
        {"artist_id": 101, "artist_name": "Country One", "spotify_artist_id": "artist-101", "genre_slug": "country", "genre_name": "Country", "artist_description": "Short bio", "long_bucket": "audio-en", "long_key": "stories/101.mp3"},
        {"artist_id": 202, "artist_name": "Pop Two", "spotify_artist_id": "artist-202", "genre_slug": "pop", "genre_name": "Pop", "artist_description": "Short bio", "long_bucket": "audio-en", "long_key": "stories/202.mp3"},
    ]

    def tracks(artist_id):
        name = "Country One" if artist_id == 101 else "Pop Two"
        return [
            {"track_id": artist_id * 10 + position, "track_name": f"{name} {position}", "spotify_track_id": f"spotify-{artist_id}-{position}", "duration_ms": 180000, "album_artwork": None, "short_detail_tts_key": None, "artist_name": name, "spotify_artist_id": f"artist-{artist_id}", "ranking_id": artist_id * 100 + position, "ranking": position, "decade_name": "1980s", "genre_name": "Country" if artist_id == 101 else "Pop"}
            for position in (1, 2)
        ]

    monkeypatch.setattr(sequence, "_artists", lambda genres, language: artists)
    monkeypatch.setattr(sequence, "_tracks", tracks)
    monkeypatch.setattr(sequence, "build_track_block", lambda candidates, set_number: candidates)
    app.dependency_overrides[bind_request_user] = bind_test_user

    def poll_for(client, phase, attempts=100):
        last = None
        for _ in range(attempts):
            response = client.get("/playback/status")
            assert response.status_code == 200
            last = response.json()
            if last["phase"] == phase:
                return last
            time.sleep(.002)
        raise AssertionError(f"expected phase={phase}; last={last}")

    def acknowledge_narration(client, status):
        response = client.post("/playback/narration-finished", json={"playbackSessionId": status["playbackSessionId"], "phase": status["phase"]})
        assert response.status_code == 200
        assert response.json()["ok"] is True

    try:
        with TestClient(app) as client:
            # The production guest endpoint is exercised; the test binding keeps
            # the deterministic in-process runtime identity stable across routes.
            assert client.post("/playback/guest-session").status_code == 200
            launch = client.post("/artist-spotlight/play-radio", params=[("genre", "ALL"), ("genres", "country"), ("genres", "pop"), ("detail_length", "short"), ("bio_length", "short")])
            assert launch.status_code == 200

            first_bio = poll_for(client, "artist")
            observed_phases = [first_bio["phase"]]
            assert get_playback_status(user_id).language == "en"
            assert first_bio["context"]["programType"] == "RADIO_ARTIST"
            assert first_bio["context"]["selected_genres"] == ["country", "pop"]
            assert first_bio["track_name"] == "Country One 1"
            assert first_bio["artist_name"] == "Country One"
            assert first_bio["context"]["genre_name"] == "Country"
            assert first_bio["context"]["artist_name"] == "Country One"
            assert first_bio["setNumber"] == 1
            assert first_bio["blockPosition"] == 1
            assert first_bio["blockSize"] == 2
            assert first_bio["genreName"] == "Country"
            assert first_bio["context"]["set_number"] == 1
            assert first_bio["context"]["block_position"] == 1
            assert first_bio["context"]["block_size"] == 2
            assert first_bio["context"]["spotify_track_id"] == "spotify-101-1"
            first_artist = first_bio["context"]["artist_id"]

            # Entering Car Mode and polling before Auto Play must leave the
            # runner on its blocking artist biography until the client
            # explicitly acknowledges that exact phase.
            assert client.get("/playback/status").json()["phase"] == "artist"
            acknowledge_narration(client, first_bio)

            first_detail = poll_for(client, "detail")
            observed_phases.append(first_detail["phase"])
            assert first_detail["track_name"] == "Country One 1"
            assert first_detail["artist_name"] == "Country One"
            assert first_detail["context"]["genre_name"] == "Country"
            assert first_detail["context"]["set_number"] == 1
            acknowledge_narration(client, first_detail)
            first_track = poll_for(client, "track")
            observed_phases.append(first_track["phase"])
            context = first_track["context"]
            assert first_track["stopped"] is False
            assert context["programType"] == "RADIO_ARTIST"
            assert context["artist_id"] == first_artist
            assert context["artist_set_number"] == 1
            assert context["set_number"] == 1
            assert context["artist_set_position"] == 1
            assert context["artist_name"] == "Country One"
            assert context["genre_name"] == "Country"
            assert context["ranking_id"] and context["spotify_track_id"]
            assert first_track["durationMs"] > 0
            get_playback_status(user_id).track_start_ts -= 11
            assert client.post("/playback/track-finished").json()["ok"] is True

            second_detail = poll_for(client, "detail")
            observed_phases.append(second_detail["phase"])
            assert second_detail["context"]["artist_id"] == first_artist
            assert second_detail["context"]["artist_set_position"] == 2
            acknowledge_narration(client, second_detail)
            second_track = poll_for(client, "track")
            observed_phases.append(second_track["phase"])
            get_playback_status(user_id).track_start_ts -= 11
            assert client.post("/playback/track-finished").json()["ok"] is True

            next_bio = poll_for(client, "artist")
            observed_phases.append(next_bio["phase"])
            assert next_bio["context"]["artist_id"] != first_artist
            assert next_bio["context"]["artist_set_number"] == 2
            assert next_bio["context"]["set_number"] == 2
            assert next_bio["stopped"] is False
            assert next_bio["isPlaying"] is True
            assert observed_phases == ["artist", "detail", "track", "detail", "track", "artist"]
            assert observed_phases.count("artist") == 2

            stopped = client.post("/playback/stop")
            assert stopped.status_code == 200
            final_status = client.get("/playback/status").json()
            assert final_status["stopped"] is True
    finally:
        app.dependency_overrides.clear()
