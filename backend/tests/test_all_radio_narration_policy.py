import asyncio
from types import SimpleNamespace

from backend.routers import decade_genre_player
from backend.services import all_radio_sequence


def test_radio_start_persists_explicit_detail_length_and_artist_choice(monkeypatch):
    status = SimpleNamespace(selection={})
    monkeypatch.setattr(
        decade_genre_player,
        "current_runtime",
        lambda: SimpleNamespace(status=status),
    )
    monkeypatch.setattr(decade_genre_player, "flags", SimpleNamespace())

    decade_genre_player.start_radio_mode(
        "en", True, True, True, "before", "short"
    )

    assert status.selection == {
        "voices": ["intro", "detail", "artist"],
        "detail_length": "short",
    }


def test_short_and_long_radio_details_use_the_existing_asset_resolvers(monkeypatch):
    track = SimpleNamespace(spotify_track_id="track")
    artist = SimpleNamespace(spotify_artist_id="artist")
    monkeypatch.setattr(
        all_radio_sequence,
        "short_detail_keys_for",
        lambda **_: ("audio-en", "short-detail/track.mp3"),
    )
    monkeypatch.setattr(
        all_radio_sequence,
        "narration_keys_for",
        lambda **_: ("audio-en", "detail/track.mp3", "audio-en", "artist/artist.mp3"),
    )

    assert all_radio_sequence.detail_audio_keys_for_radio(
        detail_length="short", lang="en", track=track, artist=artist, decade_genre_id=1
    ) == ("audio-en", "short-detail/track.mp3")
    assert all_radio_sequence.detail_audio_keys_for_radio(
        detail_length="long", lang="en", track=track, artist=artist, decade_genre_id=1
    ) == ("audio-en", "detail/track.mp3")


def test_artist_bio_guard_uses_primary_artist_identity_once_per_session():
    first = SimpleNamespace(spotify_artist_id="artist-1", id=1, artist_name="First")
    repeat = SimpleNamespace(spotify_artist_id="artist-1", id=2, artist_name="Renamed")
    another = SimpleNamespace(spotify_artist_id="artist-2", id=3, artist_name="Another")

    played = {all_radio_sequence.radio_artist_identity(first)}
    assert all_radio_sequence.radio_artist_identity(repeat) in played
    assert all_radio_sequence.radio_artist_identity(another) not in played


def test_radio_phase_policy_honors_details_and_artist_combinations():
    phases = all_radio_sequence.selected_radio_narration_phases
    common = {"first_track": False, "play_intro": True, "has_intro": True, "has_detail": True, "has_artist": True}

    assert phases(**common, play_detail=False, play_artist=True) == ["intro", "artist"]
    assert phases(**common, play_detail=True, play_artist=False) == ["intro", "detail"]
    assert phases(**common, play_detail=True, play_artist=True) == ["intro", "detail", "artist"]
    assert phases(first_track=True, play_intro=True, has_intro=True, play_detail=True, has_detail=True, play_artist=True, has_artist=True) == [
        "set_intro", "intro", "detail", "artist"
    ]


def test_radio_policy_update_is_queued_for_the_next_set(monkeypatch):
    status = SimpleNamespace(
        selection={"voices": ["intro", "detail"], "detail_length": "short"}
    )
    monkeypatch.setattr(
        decade_genre_player,
        "current_runtime",
        lambda: SimpleNamespace(status=status),
    )

    current_set_policy = all_radio_sequence.resolve_radio_narration_policy(
        status,
        default_play_detail=True,
        default_detail_length="long",
    )

    result = asyncio.run(
        decade_genre_player.update_radio_narration_policy(
            decade_genre_player.RadioNarrationPolicyRequest(
                detail_length="long",
                artist_stories_enabled=True,
            )
        )
    )

    assert current_set_policy == (True, True, "short", False)
    assert status.selection == {
        "voices": ["intro", "detail", "artist"],
        "detail_length": "long",
    }
    assert result["applies_at"] == "next_set"

    next_set_policy = all_radio_sequence.resolve_radio_narration_policy(
        status,
        default_play_detail=True,
        default_detail_length="short",
    )
    assert next_set_policy == (True, True, "long", True)


def test_radio_policy_can_turn_details_and_artist_bios_off():
    status = SimpleNamespace(
        selection={
            "voices": ["intro"],
            "detail_length": "off",
        }
    )

    assert all_radio_sequence.resolve_radio_narration_policy(
        status,
        default_play_detail=True,
        default_detail_length="long",
    ) == (True, False, "off", False)
