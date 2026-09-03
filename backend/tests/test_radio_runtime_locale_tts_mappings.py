from types import SimpleNamespace

from backend.services import radio_runtime


def test_intro_job_prefers_the_database_locale_mapping(monkeypatch):
    monkeypatch.setattr(
        radio_runtime,
        "_locale_narration_keys",
        lambda **kwargs: ("audio-es", "intro/1950s-tv_themes_01.mp3"),
    )

    jobs = radio_runtime.build_intro_jobs(
        lang="es",
        tr_rows=[(SimpleNamespace(id=71, ranking=1, decade_genre_id=63), "1950s", "TV Themes")],
    )

    assert jobs == [("audio-es", "intro/1950s-tv_themes_01.mp3", "1950s", "TV Themes", 1)]


def test_detail_job_prefers_the_database_locale_mapping(monkeypatch):
    monkeypatch.setattr(
        radio_runtime,
        "_locale_narration_keys",
        lambda **kwargs: ("audio-ptbr", "detail/spotify-1950s-theme.mp3")
        if kwargs.get("track_id") == 12
        else (None, None),
    )
    track = SimpleNamespace(id=12, spotify_track_id="spotify-1950s-theme")
    artist = SimpleNamespace(spotify_artist_id="artist")

    detail_bucket, detail_key, _, _ = radio_runtime.narration_keys_for(
        lang="pt-BR", track=track, artist=artist, decade_genre_id=63
    )

    assert (detail_bucket, detail_key) == ("audio-ptbr", "detail/spotify-1950s-theme.mp3")


def test_catalog_63_english_intro_uses_the_canonical_hyphenated_slug():
    jobs = radio_runtime.build_intro_jobs(
        lang="en",
        tr_rows=[(SimpleNamespace(id=71, ranking=1, decade_genre_id=63), "1950s", "TV Themes")],
    )

    assert jobs[0][:2] == ("audio-en", "intro/1950s-tv_themes_01.mp3")
