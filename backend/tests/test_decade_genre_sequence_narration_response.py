from types import SimpleNamespace

import pytest

from backend.routers import decade_genre_player


@pytest.mark.parametrize(
    ("rank", "spotify_track_id"),
    [
        (1, "5lSfu6Bb1lZHvEA5Lp3FSo"),
        (10, "1uLyJWPzDJeMCSi3dH6jEb"),
        (19, "1kEauajzb7929zqiIVW9fQ"),
    ],
)
@pytest.mark.parametrize(
    ("language", "bucket"),
    [("en", "audio-en"), ("es", "audio-es"), ("pt-BR", "audio-ptbr")],
)
def test_catalog_63_sequence_response_returns_canonical_narration_assets(
    monkeypatch, rank, spotify_track_id, language, bucket
):
    ranking = SimpleNamespace(ranking=rank, decade_genre_id=63)
    track = SimpleNamespace(spotify_track_id=spotify_track_id)
    artist = SimpleNamespace()
    intro_key = f"intro/1950s-tv_themes_{rank:02d}.mp3"
    detail_key = f"detail/{spotify_track_id}.mp3"
    short_key = f"short-detail/{spotify_track_id}.mp3"

    monkeypatch.setattr(
        decade_genre_player,
        "build_intro_jobs",
        lambda **_: [(bucket, intro_key, "1950s", "TV Themes", rank)],
    )
    monkeypatch.setattr(
        decade_genre_player,
        "narration_keys_for",
        lambda **_: (bucket, detail_key, None, None),
    )
    monkeypatch.setattr(
        decade_genre_player,
        "short_detail_keys_for",
        lambda **_: (bucket, short_key),
    )
    monkeypatch.setattr(
        decade_genre_player,
        "resolve_audio_ref",
        lambda asset_bucket, key: f"https://audio.test/{asset_bucket}/{key}",
    )

    assets = decade_genre_player.resolve_sequence_narration_audio(
        language=language,
        track=track,
        artist=artist,
        ranking=ranking,
        decade_name="1950s",
        genre_name="TV Themes",
    )

    assert assets == {
        "intro": {"bucket": bucket, "key": intro_key, "url": f"https://audio.test/{bucket}/{intro_key}"},
        "detail": {"bucket": bucket, "key": detail_key, "url": f"https://audio.test/{bucket}/{detail_key}"},
        "short_detail": {"bucket": bucket, "key": short_key, "url": f"https://audio.test/{bucket}/{short_key}"},
    }
    assert all(value is not None for asset in assets.values() for value in asset.values())


def test_sequence_response_does_not_use_nonexistent_audio_key_attributes():
    source = (decade_genre_player.__file__ and open(decade_genre_player.__file__, encoding="utf-8").read())
    assert 'getattr(ranking, "intro_key"' not in source
    assert 'getattr(track, "detail_key"' not in source


def test_other_catalogs_keep_resolver_based_fallbacks(monkeypatch):
    ranking = SimpleNamespace(ranking=1, decade_genre_id=7)
    track = SimpleNamespace(spotify_track_id="other-track")
    monkeypatch.setattr(decade_genre_player, "build_intro_jobs", lambda **_: [("audio-en", "intro/other_01.mp3")])
    monkeypatch.setattr(decade_genre_player, "narration_keys_for", lambda **_: ("audio-en", "detail/other-track.mp3", None, None))
    monkeypatch.setattr(decade_genre_player, "short_detail_keys_for", lambda **_: ("audio-en", "short-detail/other-track.mp3"))
    monkeypatch.setattr(decade_genre_player, "resolve_audio_ref", lambda bucket, key: f"{bucket}/{key}")

    assets = decade_genre_player.resolve_sequence_narration_audio(
        language="en", track=track, artist=SimpleNamespace(), ranking=ranking,
        decade_name="Other", genre_name="Program",
    )

    assert assets["intro"]["key"] == "intro/other_01.mp3"
    assert assets["detail"]["key"] == "detail/other-track.mp3"
    assert assets["short_detail"]["key"] == "short-detail/other-track.mp3"
