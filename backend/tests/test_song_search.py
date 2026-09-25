from sqlmodel import SQLModel, Session, create_engine

from backend.models.collection_models import Collection, CollectionTrackRanking
from backend.models.dbmodels import Artist, Decade, DecadeGenre, Genre, Track, TrackRanking
from backend.services.song_search import search_songs


def test_search_songs_finds_ranked_track_and_approved_artist_code(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'songs.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Artist(id=162, artist_name="The Beatles"),
            Artist(id=99999, artist_name="Unlisted Artist"),
            Decade(id=1, decade_name="1960s", slug="1960s"),
            Genre(id=1, genre_name="Rock", slug="rock"),
            DecadeGenre(id=1, decade_id=1, genre_id=1),
            Collection(id=1, name="Favorites", slug="favorites"),
            Track(id=1, track_name="Hey Jude", artist_id=162, artist_display_name="The Beatles", spotify_track_id="one"),
            Track(id=2, track_name="Hey Jude (cover)", artist_id=99999, spotify_track_id="two"),
            Track(id=3, track_name="Hey Jude (unranked)", artist_id=162, spotify_track_id="three"),
            Track(id=4, track_name="Hey Jude (deep collection)", artist_id=162, spotify_track_id="four"),
            TrackRanking(id=1, track_id=1, decade_genre_id=1, ranking=1),
            CollectionTrackRanking(id=1, track_id=2, collection_id=1, ranking=1),
            CollectionTrackRanking(id=2, track_id=4, collection_id=1, ranking=101),
        ])
        session.commit()
        assert search_songs(session, "Hey") == [{
            "track_id": 1, "title": "Hey Jude", "artist": "The Beatles",
            "spotlight_artist": "The Beatles", "artist_code": "A-158",
        }]
        assert search_songs(session, "%") == []
        assert search_songs(session, "H") == []
