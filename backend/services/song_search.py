"""Find approved Artist Spotlights through ranked track titles."""
from __future__ import annotations

from sqlalchemy import exists, or_
from sqlmodel import Session, select

from backend.models.collection_models import CollectionTrackRanking
from backend.models.dbmodels import Artist, Track, TrackRanking
from backend.services.program_codes import _APPROVED_PROGRAMS


_SPOTLIGHT_CODES = {
    program["target"]["artist_id"]: code
    for code, program in _APPROVED_PROGRAMS.items()
    if program["kind"] == "artist_spotlight"
}


def search_songs(session: Session, query: str, limit: int = 25) -> list[dict]:
    """Return catalog recordings whose main artist has an approved A-code."""
    cleaned = query.strip()
    if len(cleaned) < 2:
        return []
    escaped = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    ranked = exists(select(TrackRanking.id).where(TrackRanking.track_id == Track.id))
    # Keep search results within the same catalog boundary as Artist
    # Spotlight's loader. Otherwise a collection-only recording beyond 100
    # appears in search but cannot be queued after Car Mode opens.
    collected = exists(
        select(CollectionTrackRanking.id)
        .where(CollectionTrackRanking.track_id == Track.id)
        .where(CollectionTrackRanking.ranking.between(1, 100))
    )
    matches = session.exec(
        select(Track, Artist)
        .join(Artist, Track.artist_id == Artist.id)
        .where(Track.artist_id.in_(list(_SPOTLIGHT_CODES)))
        .where(Track.track_name.ilike(f"%{escaped}%", escape="\\"))
        .where(or_(ranked, collected))
        .order_by(Track.track_name, Artist.artist_name, Track.id)
        .limit(limit)
    ).all()
    return [
        {
            "track_id": track.id,
            "title": track.track_name,
            "artist": track.artist_display_name or artist.artist_name,
            "spotlight_artist": artist.artist_name,
            "artist_code": _SPOTLIGHT_CODES[artist.id],
        }
        for track, artist in matches
    ]
