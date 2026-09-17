from collections.abc import Generator
from contextlib import contextmanager
from types import SimpleNamespace
import asyncio

import pytest
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import playback_control
from backend.routers import playback_status
from backend.services.collections_radio_loader import get_valid_collections
from backend.services import collections_radio_sequence
from backend.services import decade_genre_sequence
from backend.state.narration import narration_done_event, track_done_event
from backend.state.playback_state import get_status as get_playback_status
from backend.state.playback_state import update_phase


@pytest.fixture
def radio_client(monkeypatch: pytest.MonkeyPatch):
    captured: list[dict] = []

    async def fake_start_new_sequence(coroutine):
        frame = coroutine.cr_frame
        captured.append({
            "legacy": frame.f_locals["collection_group_slug"],
            "groups": frame.f_locals["collection_group_slugs"],
            "detail_length": frame.f_locals["detail_length"],
        })
        coroutine.close()

    @contextmanager
    def fake_session() -> Generator[object, None, None]:
        yield object()

    def fake_collections(_session, *_args, **_kwargs):
        return [
            {"collection_group_slug": "music_legends"},
            {"collection_group_slug": "stage_and_screen"},
        ]

    monkeypatch.setattr(playback_control, "start_new_sequence", fake_start_new_sequence)
    monkeypatch.setattr(playback_control, "current_user_id", lambda: "test-user")
    monkeypatch.setattr(playback_control, "current_runtime", lambda: SimpleNamespace(status=SimpleNamespace()))
    monkeypatch.setattr(playback_control, "reset_for_single_track", lambda: None)
    monkeypatch.setattr("backend.database.get_db_session", fake_session)
    monkeypatch.setattr("backend.services.collections_radio_loader.get_valid_collections", fake_collections)
    return captured


def payload(context: dict) -> dict:
    return {
        "track": {
            "track_id": None,
            "spotify_track_id": "",
            "rank": 0,
            "track_name": "TopSpot Collections Radio",
            "artist_name": "Press Play to Start",
        },
        "selection": {
            "language": "en",
            "languages": ["en"],
            "voices": ["intro"],
            "voicePlayMode": "before",
            "pauseMode": "continuous",
        },
        "context": {"type": "collection_radio", **context},
    }


def test_legacy_all_and_single_group_remain_singular(radio_client):
    captured = radio_client
    assert asyncio.run(playback_control.play_track(payload({"collection_group_slug": "ALL"})))["ok"]
    assert asyncio.run(playback_control.play_track(payload({"collection_group_slug": "music_legends"})))["ok"]
    assert captured == [
        {"legacy": "ALL", "groups": None, "detail_length": "off"},
        {"legacy": "music_legends", "groups": None, "detail_length": "off"},
    ]


def test_explicit_groups_are_normalized_deduplicated_and_authoritative(radio_client):
    captured = radio_client
    result = asyncio.run(playback_control.play_track(payload({
        "collection_group_slug": "ALL",
        "collection_group_slugs": [" Stage_And_Screen ", "music_legends", "stage_and_screen"],
    })))
    assert result["ok"]
    assert captured == [{
        "legacy": "ALL",
        "groups": ["stage_and_screen", "music_legends"],
        "detail_length": "off",
    }]


def test_collections_launch_passes_camel_case_short_detail_to_sequence(radio_client):
    requested = payload({
        "collection_group_slug": "ALL",
        "collection_group_slugs": ["music_legends"],
    })
    requested["selection"]["voices"] = ["intro", "detail"]
    requested["selection"]["detailLength"] = "short"

    assert asyncio.run(playback_control.play_track(requested))["ok"]
    assert radio_client == [{
        "legacy": "ALL",
        "groups": ["music_legends"],
        "detail_length": "short",
    }]


def test_collections_http_launch_and_status_routes_preserve_short_and_track_identifiers(
    monkeypatch: pytest.MonkeyPatch,
):
    """Exercise the route payload and public poll response, not just the runner."""
    user_id = "collections-http-contract"
    captured: dict[str, object] = {}
    app = FastAPI()
    app.include_router(playback_control.router)
    app.include_router(playback_status.router)
    app.dependency_overrides[playback_control.bind_request_user] = lambda: user_id
    app.dependency_overrides[playback_status.bind_request_user] = lambda: user_id

    async def fake_start_new_sequence(coroutine):
        captured["detail_length"] = coroutine.cr_frame.f_locals["detail_length"]
        coroutine.close()

    monkeypatch.setattr(playback_control, "current_user_id", lambda: user_id)
    monkeypatch.setattr(playback_control, "current_runtime", lambda: SimpleNamespace(status=SimpleNamespace()))
    monkeypatch.setattr(playback_control, "reset_for_single_track", lambda: None)
    monkeypatch.setattr(playback_control, "start_new_sequence", fake_start_new_sequence)
    monkeypatch.setattr(playback_status, "current_user_id", lambda: user_id)

    launch = payload({"collection_group_slug": "ALL"})
    launch["selection"]["voices"] = ["intro", "detail"]
    launch["selection"]["detailLength"] = "short"
    with TestClient(app) as client:
        response = client.post("/playback/play-track", json=launch)
        assert response.status_code == 200
        assert captured["detail_length"] == "short"

        public_status = get_playback_status(user_id)
        public_status.playback_session_id = "collections-http-session"
        update_phase(
            user_id,
            "track",
            is_playing=True,
            stopped=False,
            current_rank=7,
            current_ranking_id=707,
            spotify_track_id="spotify-http-track",
            track_name="HTTP Track",
            artist_name="HTTP Artist",
            context={
                "mode": "spotify",
                "ranking_id": 707,
                "spotify_track_id": "spotify-http-track",
            },
        )
        poll = client.get("/playback/status")

    assert poll.status_code == 200
    assert poll.json()["phase"] == "track"
    assert poll.json()["current_rank"] == 7
    assert poll.json()["context"]["ranking_id"] == 707
    assert poll.json()["context"]["spotify_track_id"] == "spotify-http-track"


@pytest.mark.parametrize("groups", [[], ["ALL"], ["unknown"], ["music_docuseries"], ["  "]])
def test_invalid_or_unavailable_explicit_groups_return_422(radio_client, groups):
    with pytest.raises(HTTPException) as error:
        asyncio.run(playback_control.play_track(payload({
            "collection_group_slug": "ALL",
            "collection_group_slugs": groups,
        })))
    assert error.value.status_code == 422


def test_concrete_legacy_group_conflicts_with_explicit_list(radio_client):
    with pytest.raises(HTTPException) as error:
        asyncio.run(playback_control.play_track(payload({
            "collection_group_slug": "music_legends",
            "collection_group_slugs": ["stage_and_screen"],
        })))
    assert error.value.status_code == 422


def test_explicit_group_union_restricts_eligible_pool_before_sequence_shuffle():
    rows = [
        (SimpleNamespace(slug="legends", name="Legends", category=SimpleNamespace(slug="music_legends", name="Music Legends")),),
        (SimpleNamespace(slug="screen", name="Screen", category=SimpleNamespace(slug="stage_and_screen", name="Stage & Screen")),),
        (SimpleNamespace(slug="trends", name="Trends", category=SimpleNamespace(slug="music_trends", name="Music Trends")),),
    ]
    session = SimpleNamespace(exec=lambda _statement: SimpleNamespace(all=lambda: rows))
    eligible = get_valid_collections(session, collection_group_slugs=["music_legends", "stage_and_screen"])
    assert [item["collection_slug"] for item in eligible] == ["legends", "screen"]


def test_prepared_collections_track_remains_available_from_playback_status(monkeypatch: pytest.MonkeyPatch):
    """A Collections set intro must not terminate its sequence before track publish."""
    user_id = "collections-radio-status-regression"
    status = get_playback_status(user_id)
    runtime = SimpleNamespace(status=status)
    track = SimpleNamespace(
        id=101,
        track_name="Ready Track",
        spotify_track_id="spotify-ready-track",
        duration_ms=180_000,
        album_artwork=None,
        detail=None,
        detail_text=None,
    )
    artist = SimpleNamespace(
        id=102,
        artist_name="Ready Artist",
        artist_artwork=None,
        spotify_artist_id="spotify-ready-artist",
        artist_description=None,
        artist_description_text=None,
    )
    ranking = SimpleNamespace(ranking=1, id=103, intro=None, intro_text=None)
    collection = SimpleNamespace(
        set_intro_tts_bucket="audio-en",
        set_intro_tts_key="collections/ready-intro.mp3",
    )
    row = (track, artist, ranking, collection, None, None, None)

    @contextmanager
    def fake_session() -> Generator[object, None, None]:
        yield object()

    monkeypatch.setattr(collections_radio_sequence, "current_user_id", lambda: user_id)
    monkeypatch.setattr(collections_radio_sequence, "current_runtime", lambda: runtime)
    monkeypatch.setattr(collections_radio_sequence, "flags", SimpleNamespace())
    monkeypatch.setattr(collections_radio_sequence, "get_db_session", fake_session)
    monkeypatch.setattr(
        collections_radio_sequence,
        "get_valid_collections",
        lambda *_args: [{
            "collection_slug": "ready-collection",
            "collection_name": "Ready Collection",
            "collection_group_slug": "music_legends",
            "collection_group_name": "Music Legends",
        }],
    )
    monkeypatch.setattr(collections_radio_sequence, "load_collection_rows", lambda *_args: [row])
    monkeypatch.setattr(collections_radio_sequence, "build_track_block", lambda rows, **_kwargs: rows)
    monkeypatch.setattr(collections_radio_sequence, "build_collection_radio_texts_by_language", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(collections_radio_sequence, "resolve_audio_ref", lambda bucket, key: f"/{bucket}/{key}")
    monkeypatch.setattr(playback_status, "current_user_id", lambda: user_id)

    async def run_and_poll() -> dict:
        task = asyncio.create_task(
            collections_radio_sequence.run_collections_radio_sequence(
                tts_language="en",
                collection_group_slugs=["music_legends", "stage_and_screen"],
                voices=[],
                voice_style="over",
            )
        )
        for _ in range(10):
            await asyncio.sleep(0)
            if status.phase == "track":
                break

        poll = await playback_status.get_status()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return poll

    poll = asyncio.run(run_and_poll())

    assert poll["stopped"] is False
    assert poll["phase"] == "track"
    assert poll["track_name"] == "Ready Track"
    assert poll["artist_name"] == "Ready Artist"
    assert poll["current_rank"] == 1
    assert poll["context"]["spotify_track_id"] == "spotify-ready-track"


def test_collection_intro_narration_finished_preserves_and_recognizes_phase(monkeypatch: pytest.MonkeyPatch):
    user_id = "collection-intro-phase-contract"
    session_id = "collection-intro-session"
    status = get_playback_status(user_id)
    status.phase = "collection_intro"
    status.is_playing = True
    status.stopped = False
    status.playback_session_id = session_id
    status.context = {"voice_style": "before"}
    narration_done_event(user_id).clear()
    monkeypatch.setattr(playback_status, "current_user_id", lambda: user_id)

    payload = playback_status.NarrationFinishedRequest.model_validate({
        "playbackSessionId": session_id,
        "phase": "collection_intro",
    })
    result = asyncio.run(playback_status.narration_finished(payload))

    assert payload.phase == "collection_intro"
    assert result == {"ok": True}
    assert narration_done_event(user_id).is_set()

    status.phase = "unrecognized_phase"
    narration_done_event(user_id).clear()
    rejected = asyncio.run(playback_status.narration_finished(
        playback_status.NarrationFinishedRequest(
            playbackSessionId=session_id,
            phase="unrecognized_phase",
        )
    ))
    assert rejected == {"ok": True, "ignored": True, "reason": "not_narration_phase"}
    assert narration_done_event(user_id).is_set() is False


def test_collections_radio_detail_resolver_uses_selected_short_or_long_asset(monkeypatch: pytest.MonkeyPatch):
    track = SimpleNamespace(spotify_track_id="detail-track")
    artist = SimpleNamespace(spotify_artist_id="detail-artist")
    monkeypatch.setattr(
        collections_radio_sequence,
        "short_detail_keys_for",
        lambda **_kwargs: ("audio-en", "short-detail/detail-track.mp3"),
    )
    monkeypatch.setattr(
        collections_radio_sequence,
        "narration_keys_for",
        lambda **_kwargs: ("audio-en", "detail/detail-track.mp3", "audio-en", "artist/detail-artist.mp3"),
    )

    assert collections_radio_sequence.detail_audio_keys_for_collections_radio(
        detail_length="short", lang="en", track=track, artist=artist,
    ) == ("audio-en", "short-detail/detail-track.mp3")
    assert collections_radio_sequence.detail_audio_keys_for_collections_radio(
        detail_length="long", lang="en", track=track, artist=artist,
    ) == ("audio-en", "detail/detail-track.mp3")


@pytest.mark.parametrize(
    ("selection", "voices", "expected"),
    [
        ({"detailLength": "short"}, ["detail"], "short"),
        ({"detail_length": "long"}, ["detail"], "long"),
        ({"detail_length": "off"}, ["detail"], "off"),
        ({}, [], "off"),
    ],
)
def test_collections_launch_preserves_selected_detail_length(selection, voices, expected):
    assert playback_control._collection_radio_detail_length(
        {"selection": selection, "context": {"type": "collection_radio"}},
        voices,
    ) == expected


@pytest.mark.parametrize(
    ("artist_enabled", "detail_length"),
    [(False, "long"), (True, "long"), (False, "off")],
)
def test_collections_radio_advances_every_narration_phase_and_introduces_each_set(
    monkeypatch: pytest.MonkeyPatch,
    artist_enabled: bool,
    detail_length: str,
):
    user_id = f"collections-radio-narration-{'artist' if artist_enabled else 'no-artist'}-{detail_length}"
    session_id = f"{user_id}-session"
    status = get_playback_status(user_id)
    status.playback_session_id = session_id
    runtime = SimpleNamespace(status=status)

    def make_row(track_number: int, collection_slug: str):
        track = SimpleNamespace(
            id=100 + track_number,
            track_name=f"Track {track_number}",
            spotify_track_id=f"spotify-track-{track_number}",
            duration_ms=180_000,
            album_artwork=None,
            detail=None,
            detail_text=None,
        )
        artist = SimpleNamespace(
            id=200 + track_number,
            artist_name=f"Artist {track_number}",
            spotify_artist_id=f"spotify-artist-{track_number}",
            artist_artwork=None,
            artist_description=None,
            artist_description_text=None,
        )
        ranking = SimpleNamespace(ranking=track_number, id=300 + track_number, intro=None, intro_text=None)
        collection = SimpleNamespace(
            slug=collection_slug,
            set_intro_tts_bucket="audio-en",
            set_intro_tts_key=f"set-intros/{collection_slug}.mp3",
        )
        return track, artist, ranking, collection, None, None, None

    first_set_rows = [make_row(1, "first-set"), make_row(2, "first-set")]
    second_set_rows = [make_row(3, "second-set")]

    @contextmanager
    def fake_session() -> Generator[object, None, None]:
        yield object()

    monkeypatch.setattr(collections_radio_sequence, "current_user_id", lambda: user_id)
    monkeypatch.setattr(collections_radio_sequence, "current_runtime", lambda: runtime)
    monkeypatch.setattr(collections_radio_sequence, "flags", SimpleNamespace())
    monkeypatch.setattr(collections_radio_sequence, "get_db_session", fake_session)
    monkeypatch.setattr(collections_radio_sequence.random, "shuffle", lambda _items: None)
    monkeypatch.setattr(
        collections_radio_sequence,
        "get_valid_collections",
        lambda *_args: [
            {
                "collection_slug": "first-set",
                "collection_name": "First Set",
                "collection_group_slug": "music_legends",
                "collection_group_name": "Music Legends",
            },
            {
                "collection_slug": "second-set",
                "collection_name": "Second Set",
                "collection_group_slug": "stage_and_screen",
                "collection_group_name": "Stage & Screen",
            },
        ],
    )
    monkeypatch.setattr(
        collections_radio_sequence,
        "load_collection_rows",
        lambda _session, collection_slug, _language: (
            first_set_rows if collection_slug == "first-set" else second_set_rows
        ),
    )
    monkeypatch.setattr(collections_radio_sequence, "build_track_block", lambda rows, **_kwargs: rows)
    monkeypatch.setattr(collections_radio_sequence, "build_collection_radio_texts_by_language", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(collections_radio_sequence, "collection_intro_jobs", lambda **kwargs: [
        ("audio-en", f"intros/{kwargs['collection_slug']}_{kwargs['rank']}.mp3")
    ])
    monkeypatch.setattr(
        collections_radio_sequence,
        "narration_keys_for",
        lambda **kwargs: (
            "audio-en", f"detail/{kwargs['track'].spotify_track_id}.mp3",
            "audio-en", f"artist/{kwargs['artist'].spotify_artist_id}.mp3",
        ),
    )
    monkeypatch.setattr(collections_radio_sequence, "resolve_audio_ref", lambda bucket, key: f"/{bucket}/{key}")
    monkeypatch.setattr(decade_genre_sequence, "current_user_id", lambda: user_id)
    monkeypatch.setattr(decade_genre_sequence, "current_runtime", lambda: runtime)
    monkeypatch.setattr(playback_status, "current_user_id", lambda: user_id)

    voices = ["intro", "detail"] + (["artist"] if artist_enabled else [])
    expected_first_track = ["collection_intro", "intro"]
    if detail_length != "off":
        expected_first_track.append("detail")
    if artist_enabled:
        expected_first_track.append("artist")
    expected_second_track = ["intro"]
    if detail_length != "off":
        expected_second_track.append("detail")
    if artist_enabled:
        expected_second_track.append("artist")

    async def run_through_second_set_intro() -> list[tuple[str, str, str]]:
        narration_done_event(user_id).clear()
        track_done_event(user_id).clear()
        task = asyncio.create_task(
            collections_radio_sequence.run_collections_radio_sequence(
                tts_language="en",
                collection_group_slugs=["music_legends", "stage_and_screen"],
                voices=voices,
                detail_length=detail_length,
                voice_style="before",
            )
        )
        observed: list[tuple[str, str, str]] = []
        last_marker = None

        for _ in range(200):
            await asyncio.sleep(0)
            if task.done():
                await task
            marker = (status.phase, status.context.get("collection_slug"), status.track_name)
            if marker == last_marker or marker[0] not in {
                "collection_intro", "intro", "detail", "artist", "track",
            }:
                continue
            last_marker = marker
            observed.append(marker)

            if marker[0] == "track":
                assert status.current_ranking_id is not None
                assert status.context["spotify_track_id"] == (
                    "spotify-track-1" if marker[2] == "Track 1" else "spotify-track-2"
                    if marker[2] == "Track 2" else "spotify-track-3"
                )
                assert task.done() is False
                track_done_event(user_id).set()
            else:
                result = await playback_status.narration_finished(
                    playback_status.NarrationFinishedRequest(
                        playbackSessionId=session_id,
                        phase=marker[0],
                    )
                )
                assert result == {"ok": True}

            if marker[:2] == ("collection_intro", "second-set"):
                break

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return observed

    observed = asyncio.run(run_through_second_set_intro())
    phases_by_track = [phase for phase, collection_slug, track_name in observed if collection_slug == "first-set" and track_name == "Track 1"]
    second_track_phases = [phase for phase, collection_slug, track_name in observed if collection_slug == "first-set" and track_name == "Track 2"]

    assert phases_by_track == [*expected_first_track, "track"]
    assert second_track_phases == [*expected_second_track, "track"]
    assert [marker[:2] for marker in observed if marker[0] == "collection_intro"] == [
        ("collection_intro", "first-set"),
        ("collection_intro", "second-set"),
    ]
