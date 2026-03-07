from fastapi import APIRouter, Query, Depends
from sqlmodel import select

from backend.database import get_db
from backend.models.dbmodels import (
    Track,
    Artist,
    Collection,
    CollectionTrackRanking,
)

router = APIRouter(prefix="/supabase/collections", tags=["Supabase: Collections"])
@router.get("/get-sequence")
async def get_sequence_collection(
    collection_slug: str = Query(...),
    start_rank: int = Query(1),
    end_rank: int = Query(40),
    db=Depends(get_db),
):
    q = (
        select(Track, Artist, CollectionTrackRanking)
        .join(Artist, Artist.id == Track.artist_id)
        .join(CollectionTrackRanking, CollectionTrackRanking.track_id == Track.id)
        .join(Collection, Collection.id == CollectionTrackRanking.collection_id)
        .where(
            Collection.slug == collection_slug,
            CollectionTrackRanking.ranking >= start_rank,
            CollectionTrackRanking.ranking <= end_rank,
        )
        .order_by(CollectionTrackRanking.ranking)
    )

    rows = db.exec(q).all()

    if not rows:
        return {"status": "empty", "tracks": []}

    tracks = [
        {
            "rank": ctr.ranking,
            "trackName": track.track_name,
            "artistName": artist.artist_name,
            "yearReleased": getattr(track, "year_released", None),
            "durationMs": getattr(track, "duration_ms", None),
            "albumArtwork": getattr(track, "album_artwork", None),
            "spotifyTrackId": getattr(track, "spotify_track_id", None),
            "albumName": getattr(track, "album_name", None),
        }
        for track, artist, ctr in rows
    ]

    return {"status": "ok", "total": len(tracks), "tracks": tracks}
