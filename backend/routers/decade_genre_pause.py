from fastapi import APIRouter, Query, Depends
from sqlmodel import select, Session

from backend.database import get_db
from backend.models.dbmodels import (
    Track,
    Artist,
    TrackRanking,
    DecadeGenre,
    Decade,
    Genre,
)

router = APIRouter(
    prefix="/playback/decade-genre",
    tags=["Playback: Pause Mode"],
)

@router.get("")
def get_decade_genre_pause(
    decade: str = Query(..., description="Decade slug, e.g. 1960s"),
    genre: str = Query(..., description="Genre slug, e.g. pop"),
    db: Session = Depends(get_db),
):
    q = (
        select(Track, Artist, TrackRanking)
        .join(Artist, Artist.id == Track.artist_id)
        .join(TrackRanking, TrackRanking.track_id == Track.id)
        .join(DecadeGenre, DecadeGenre.id == TrackRanking.decade_genre_id)
        .join(Decade, Decade.id == DecadeGenre.decade_id)
        .join(Genre, Genre.id == DecadeGenre.genre_id)
        .where(
            Decade.slug == decade,
            Genre.slug == genre,
        )
        .order_by(TrackRanking.ranking)
    )

    rows = db.exec(q).all()

    tracks = [
        {
            "rank": ranking.ranking,
            "track_id": getattr(track, "spotify_track_id", None),
            "title": track.track_name,
            "artist": artist.artist_name,
            "duration_ms": track.duration_ms,
            "album_artwork": track.album_artwork,
        }
        for track, artist, ranking in rows
    ]

    return {
        "decade": decade,
        "genre": genre,
        "total_tracks": len(tracks),
        "tracks": tracks,
    }
