from sqlmodel import SQLModel, Session, create_engine
from backend.models.collection_models import Collection, CollectionTrackRanking
from backend.models.dbmodels import Artist, Decade, DecadeGenre, Genre, Track, TrackRanking
from backend.services import song_search

def test_song_search_opens_approved_programs_without_spotlights(tmp_path, monkeypatch):
    monkeypatch.setattr(song_search, "_SPOTLIGHT_CODES", {})
    monkeypatch.setattr(song_search, "_NOSTALGIA_CODES", {("2000s", "tv-themes"): "N-048"})
    monkeypatch.setattr(song_search, "_COLLECTION_CODES", {"favorites": "C-001"})
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog-song-search.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Artist(id=99999, artist_name="Massive Attack"),
            Decade(id=1, decade_name="2000s", slug="2000s"),
            Genre(id=1, genre_name="TV Themes", slug="tv-themes"),
            DecadeGenre(id=1, decade_id=1, genre_id=1),
            Collection(id=1, name="Favorites", slug="favorites"),
            Collection(id=2, name="Unapproved", slug="unapproved"),
            Track(id=1, track_name="Teardrop", artist_id=99999, spotify_track_id="one"),
            Track(id=2, track_name="Teardrop collection", artist_id=99999, spotify_track_id="two"),
            Track(id=3, track_name="Teardrop unranked", artist_id=99999, spotify_track_id="three"),
            Track(id=4, track_name="Teardrop unapproved", artist_id=99999, spotify_track_id="four"),
            TrackRanking(id=1, track_id=1, decade_genre_id=1, ranking=4),
            CollectionTrackRanking(id=1, track_id=1, collection_id=1, ranking=1),
            CollectionTrackRanking(id=2, track_id=2, collection_id=1, ranking=2),
            CollectionTrackRanking(id=3, track_id=4, collection_id=2, ranking=1),
        ])
        session.commit()
        result = song_search.search_songs(session, "Teard")
        assert [row["track_id"] for row in result] == [1, 2]
        assert result[0]["program_code"] == "N-048"
        assert result[0]["program_kind"] == "nostalgia"
        assert result[1]["program_code"] == "C-001"
        assert result[1]["program_kind"] == "collection"
        assert song_search.search_songs(session, "Teard", limit=1) == result[:1]
        assert song_search.search_songs(session, "T") == []
        assert song_search.search_songs(session, "%%") == []
        assert song_search.search_songs(session, "__") == []
        assert song_search.search_songs(session, "Teard", limit=0) == []
