from sqlmodel import SQLModel, Session, create_engine
from backend.models.collection_models import Collection, CollectionTrackRanking
from backend.models.dbmodels import Artist, Decade, DecadeGenre, Genre, Track, TrackRanking
from backend.services import song_search


def test_artist_search_finds_collection_only_artists_and_excludes_unapproved(tmp_path, monkeypatch):
    monkeypatch.setattr(song_search, "_SPOTLIGHT_CODES", {})
    monkeypatch.setattr(song_search, "_NOSTALGIA_CODES", {})
    monkeypatch.setattr(song_search, "_COLLECTION_CODES", {"celtic_favorites": "C-005"})
    engine = create_engine(f"sqlite:///{tmp_path / 'artist-collections.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Artist(id=99999, artist_name="The Irish Tenors"),
            Artist(id=99998, artist_name="Irish Unapproved"),
            Artist(id=99997, artist_name="Irish Unranked"),
            Artist(id=99996, artist_name="Other Performer"),
            Collection(id=1, name="Celtic Favorites", slug="celtic_favorites"),
            Collection(id=2, name="Unapproved", slug="unapproved"),
            Track(id=1, track_name="Danny Boy", artist_id=99999, spotify_track_id="one"),
            Track(id=2, track_name="Fields of Athenry", artist_id=99999, spotify_track_id="two"),
            Track(id=3, track_name="Other song", artist_id=99998, spotify_track_id="three"),
            Track(id=4, track_name="Unranked song", artist_id=99997, spotify_track_id="four"),
            Track(id=5, track_name="Irish title only", artist_id=99996, spotify_track_id="five"),
            Track(id=6, track_name="Beyond playback range", artist_id=99999, spotify_track_id="six"),
            CollectionTrackRanking(id=1, track_id=1, collection_id=1, ranking=1),
            CollectionTrackRanking(id=2, track_id=2, collection_id=1, ranking=2),
            CollectionTrackRanking(id=3, track_id=3, collection_id=2, ranking=1),
            CollectionTrackRanking(id=4, track_id=5, collection_id=1, ranking=3),
            CollectionTrackRanking(id=5, track_id=6, collection_id=1, ranking=101),
        ])
        session.commit()
        result = song_search.search_artists(session, "irish")
        assert len(result) == 1
        assert result[0]["artist"] == "The Irish Tenors"
        assert result[0]["program_code"] == "C-005"
        assert result[0]["program_name"] == "Celtic Favorites"
        assert result[0]["track_id"] == 1
        assert song_search.search_artists(session, "IRISH TENORS") == result
        assert song_search.search_artists(session, "Danny Boy") == []
        assert song_search.search_artists(session, "%%") == []
        assert song_search.search_artists(session, "__") == []
        assert song_search.search_artists(session, "I") == []
        assert song_search.search_artists(session, "irish", limit=0) == []
        assert song_search.search_songs(session, "Danny")[0]["track_id"] == 1


def test_artist_search_preserves_spotlight_and_nostalgia_priority(tmp_path, monkeypatch):
    monkeypatch.setattr(song_search, "_SPOTLIGHT_CODES", {10: "A-158"})
    monkeypatch.setattr(song_search, "_NOSTALGIA_CODES", {("2000s", "tv-themes"): "N-048"})
    monkeypatch.setattr(song_search, "_COLLECTION_CODES", {"favorites": "C-001"})
    engine = create_engine(f"sqlite:///{tmp_path / 'artist-priority.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Artist(id=10, artist_name="The Beatles"),
            Artist(id=20, artist_name="Massive Attack"),
            Decade(id=1, decade_name="2000s", slug="2000s"),
            Genre(id=1, genre_name="TV Themes", slug="tv-themes"),
            DecadeGenre(id=1, decade_id=1, genre_id=1),
            Collection(id=1, name="Favorites", slug="favorites"),
            Track(id=1, track_name="Hey Jude", artist_id=10, spotify_track_id="one"),
            Track(id=2, track_name="Teardrop", artist_id=20, spotify_track_id="two"),
            Track(id=3, track_name="Another song", artist_id=10, spotify_track_id="three"),
            TrackRanking(id=1, track_id=1, decade_genre_id=1, ranking=1),
            TrackRanking(id=2, track_id=2, decade_genre_id=1, ranking=2),
            CollectionTrackRanking(id=1, track_id=2, collection_id=1, ranking=1),
            CollectionTrackRanking(id=2, track_id=3, collection_id=1, ranking=2),
        ])
        session.commit()
        beatles = song_search.search_artists(session, "beat")
        assert len(beatles) == 1
        assert beatles[0]["artist_code"] == "A-158"
        assert beatles[0]["spotlight_artist"] == "The Beatles"
        massive = song_search.search_artists(session, "massive")
        assert massive[0]["program_code"] == "N-048"
        assert "artist_code" not in massive[0]
        assert song_search.search_songs(session, "Hey Jude")[0]["artist_code"] == "A-158"
