from backend.routers import artist_spotlight
from backend.services import artist_radio_sequence as radio
from backend.services import artist_spotlight_eligibility as eligibility


def _base(artist_id, name, genre):
    return {
        "artist_id": artist_id,
        "artist_name": name,
        "genre_slug": genre,
        "genre_name": genre.title(),
        "genre_track_count": 3,
        "total_track_count": 3,
        "has_story": True,
    }


def _ready(artist_id, name):
    return {
        "artist_id": artist_id,
        "artist_name": name,
        "spotify_artist_id": f"spotify-{artist_id}",
        "artist_description": "Biography",
        "long_bucket": "audio-es",
        "long_key": f"artist-story/{artist_id}.mp3",
        "short_bucket": "audio-es",
        "short_key": f"artist/{artist_id}.mp3",
    }


def test_canonical_query_uses_ranked_primary_artist_membership_not_featured_performers():
    query = eligibility.build_featured_artist_eligibility_query(
        genres=["country"],
        min_tracks=3,
        featured_only=True,
        per_genre=True,
    ).text

    assert "JOIN artist a\n                ON t.artist_id = a.id" in query
    assert "featured_artist_id" not in query
    assert "WHERE gc.genre_track_count >= :min_tracks" in query


def test_country_duet_featured_pop_artist_is_excluded_from_program_and_radio(monkeypatch):
    # The canonical result represents Dan + Shay's primary Country tracks;
    # Justin Bieber's Country-duet featured_artist_id is deliberately absent.
    canonical = [_base(444, "Dan + Shay", "country")]
    monkeypatch.setattr(
        eligibility,
        "featured_artist_eligibility_rows",
        lambda **_: canonical,
    )
    monkeypatch.setattr(
        radio,
        "_radio_metadata",
        lambda artist_ids, language: {444: _ready(444, "Dan + Shay")},
    )
    monkeypatch.setattr(
        radio,
        "_playable_ranked_genres",
        lambda artist_ids, genres: {(444, "country")},
    )

    program_rows = artist_spotlight.artists_by_genre(
        genre="country", min_tracks=3, max_tracks=None, featured_only=True
    )
    radio_rows_by_language = {
        language: radio._artists(["country"], language)
        for language in ("en", "es", "pt-BR")
    }

    assert [row["artist_id"] for row in program_rows] == [444]
    for radio_rows in radio_rows_by_language.values():
        assert [row["artist_id"] for row in radio_rows] == [444]
        assert 415 not in {row["artist_id"] for row in radio_rows}


def test_primary_artist_with_three_ranked_tracks_is_included_and_lower_count_is_not(monkeypatch):
    canonical = [_base(1, "Qualified Country Artist", "country")]
    monkeypatch.setattr(
        eligibility,
        "featured_artist_eligibility_rows",
        lambda **_: canonical,
    )
    monkeypatch.setattr(
        radio,
        "_radio_metadata",
        lambda artist_ids, language: {1: _ready(1, "Qualified Country Artist")},
    )
    monkeypatch.setattr(
        radio,
        "_playable_ranked_genres",
        lambda artist_ids, genres: {(1, "country")},
    )

    assert [row["artist_id"] for row in artist_spotlight.artists_by_genre(
        genre="country", min_tracks=3, max_tracks=None, featured_only=True
    )] == [1]
    assert [row["artist_id"] for row in radio._artists(["country"], "es")] == [1]


def test_missing_localized_tts_keeps_the_program_eligible_artist_in_radio(monkeypatch):
    canonical = [_base(1, "Localized", "country"), _base(2, "English Only", "country")]
    monkeypatch.setattr(eligibility, "featured_artist_eligibility_rows", lambda **_: canonical)
    missing_tts = _ready(2, "English Only")
    missing_tts.update({"long_bucket": None, "long_key": None, "short_bucket": None, "short_key": None})
    monkeypatch.setattr(radio, "_radio_metadata", lambda artist_ids, language: {
        1: _ready(1, "Localized"), 2: missing_tts,
    })
    monkeypatch.setattr(radio, "_playable_ranked_genres", lambda artist_ids, genres: {(1, "country"), (2, "country")})

    assert [row["artist_id"] for row in artist_spotlight.artists_by_genre(
        genre="country", min_tracks=3, max_tracks=None, featured_only=True
    )] == [1, 2]
    assert [row["artist_id"] for row in radio._artists(["country"], "es")] == [1, 2]
    assert radio.biography_keys_for_artist(missing_tts, "short") == (None, None)
    assert radio.biography_keys_for_artist(missing_tts, "long") == (None, None)


def test_rock_artist_without_spanish_biography_tts_remains_eligible(monkeypatch):
    canonical = [_base(1168, "Rock Artist", "rock")]
    no_spanish_bio = _ready(1168, "Rock Artist")
    no_spanish_bio.update({"long_bucket": None, "long_key": None, "short_bucket": None, "short_key": None})
    monkeypatch.setattr(eligibility, "featured_artist_eligibility_rows", lambda **_: canonical)
    monkeypatch.setattr(radio, "_radio_metadata", lambda artist_ids, language: {1168: no_spanish_bio})
    monkeypatch.setattr(radio, "_playable_ranked_genres", lambda artist_ids, genres: {(1168, "rock")})

    assert [row["artist_id"] for row in radio._artists(["rock"], "es")] == [1168]


def test_radio_preserves_each_canonical_genre_membership_regardless_of_row_order(monkeypatch):
    canonical = [_base(1, "Cross Genre", "pop"), _base(1, "Cross Genre", "country")]
    monkeypatch.setattr(eligibility, "featured_artist_eligibility_rows", lambda **_: canonical)
    monkeypatch.setattr(radio, "_radio_metadata", lambda artist_ids, language: {1: _ready(1, "Cross Genre")})
    monkeypatch.setattr(radio, "_playable_ranked_genres", lambda artist_ids, genres: {(1, "country"), (1, "pop")})

    rows = radio._artists(["country", "pop"], "es")

    assert {(row["artist_id"], row["genre_slug"]) for row in rows} == {(1, "country"), (1, "pop")}


def test_radio_track_query_is_limited_to_the_selected_canonical_genre():
    query = radio.build_ranked_artist_track_query().text

    assert "AND g.slug=:genre_slug" in query
    assert "JOIN artist a ON a.id=t.artist_id" in query


def test_radio_queries_the_same_canonical_base_for_every_supported_genre(monkeypatch):
    calls = []

    def canonical(**kwargs):
        requested = tuple(kwargs.get("genres") or [kwargs["genre"]])
        calls.append((requested, kwargs["per_genre"]))
        return [_base(index + 1, f"{genre} Artist", genre) for index, genre in enumerate(requested)]

    monkeypatch.setattr(eligibility, "featured_artist_eligibility_rows", canonical)
    monkeypatch.setattr(
        radio,
        "_radio_metadata",
        lambda artist_ids, language: {
            artist_id: _ready(artist_id, f"Artist {artist_id}") for artist_id in artist_ids
        },
    )
    monkeypatch.setattr(
        radio,
        "_playable_ranked_genres",
        lambda artist_ids, genres: {(artist_id, genre) for artist_id in artist_ids for genre in genres},
    )

    for genre in radio.ALLOWED_GENRES:
        program_rows = artist_spotlight.artists_by_genre(
            genre=genre, min_tracks=3, max_tracks=None, featured_only=True
        )
        for language in ("en", "es", "pt-BR"):
            radio_rows = radio._artists([genre], language)
            assert [row["artist_id"] for row in radio_rows] == [row["artist_id"] for row in program_rows]

    expected_calls = []
    for genre in radio.ALLOWED_GENRES:
        expected_calls.append(((genre,), False))
        expected_calls.extend([((genre,), True)] * 3)
    assert calls == expected_calls


def test_radio_artist_pool_is_identical_for_en_es_and_ptbr(monkeypatch):
    canonical = [_base(1, "Country Artist", "country"), _base(2, "Another Country Artist", "country")]
    monkeypatch.setattr(eligibility, "featured_artist_eligibility_rows", lambda **_: canonical)
    monkeypatch.setattr(
        radio,
        "_radio_metadata",
        lambda artist_ids, language: {
            artist_id: _ready(artist_id, f"Artist {artist_id}") for artist_id in artist_ids
        },
    )
    monkeypatch.setattr(radio, "_playable_ranked_genres", lambda artist_ids, genres: {
        (artist_id, genre) for artist_id in artist_ids for genre in genres
    })

    pools = {
        language: {(row["artist_id"], row["genre_slug"]) for row in radio._artists(["country"], language)}
        for language in ("en", "es", "pt-BR")
    }

    assert pools["en"] == pools["es"] == pools["pt-BR"] == {(1, "country"), (2, "country")}
