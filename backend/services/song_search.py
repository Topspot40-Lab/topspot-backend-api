"""Find playable recordings in approved TopSpot40 programs."""
from __future__ import annotations

from sqlalchemy import exists, or_
from sqlmodel import Session, select

from backend.models.collection_models import Collection, CollectionTrackRanking
from backend.models.dbmodels import Artist, Track, TrackRanking, DecadeGenre, Decade, Genre
from backend.services.program_codes import _APPROVED_PROGRAMS

_SPOTLIGHT_CODES = {
    program["target"]["artist_id"]: code
    for code, program in _APPROVED_PROGRAMS.items()
    if program["kind"] == "artist_spotlight"
}
_NOSTALGIA_CODES = {
    (program["target"]["decade_slug"], program["target"]["genre_slug"]): code
    for code, program in _APPROVED_PROGRAMS.items()
    if program["kind"] == "nostalgia"
}
_COLLECTION_CODES = {
    program["target"]["slug"]: code
    for code, program in _APPROVED_PROGRAMS.items()
    if program["kind"] == "collection"
}

def _search_recordings(session: Session, query: str, limit: int = 25, *, by_artist: bool = False) -> list[dict]:
    """Prefer existing Spotlight destinations, then approved N/C programs."""
    cleaned = query.strip()
    if len(cleaned) < 2 or limit <= 0:
        return []
    escaped = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    ranked = exists(select(TrackRanking.id).where(TrackRanking.track_id == Track.id))
    collected = exists(
        select(CollectionTrackRanking.id)
        .where(CollectionTrackRanking.track_id == Track.id)
        .where(CollectionTrackRanking.ranking.between(1, 100))
    )
    matches = session.exec(
        select(Track, Artist)
        .join(Artist, Track.artist_id == Artist.id)
        .where(or_(
            Artist.artist_name.ilike(f"%{escaped}%", escape="\\"),
            Track.artist_display_name.ilike(f"%{escaped}%", escape="\\"),
        ) if by_artist else Track.track_name.ilike(f"%{escaped}%", escape="\\"))
        .where(or_(ranked, collected))
        .order_by(*(
            (Artist.artist_name, Track.track_name, Track.id) if by_artist
            else (Track.track_name, Artist.artist_name, Track.id)
        ))
    ).all()
    fallback_ids = [track.id for track, artist in matches if artist.id not in _SPOTLIGHT_CODES]
    destinations: dict[int, dict] = {}
    if fallback_ids:
        nostalgia = session.exec(
            select(TrackRanking, Decade, Genre)
            .select_from(TrackRanking)
            .join(DecadeGenre, TrackRanking.decade_genre_id == DecadeGenre.id)
            .join(Decade, DecadeGenre.decade_id == Decade.id)
            .join(Genre, DecadeGenre.genre_id == Genre.id)
            .where(TrackRanking.track_id.in_(fallback_ids))
            .where(TrackRanking.ranking > 0)
            .order_by(TrackRanking.id)
        ).all()
        for ranking, decade, genre in nostalgia:
            code = _NOSTALGIA_CODES.get((decade.slug, genre.slug))
            if code:
                destinations.setdefault(ranking.track_id, {
                    "program_code": code, "program_kind": "nostalgia",
                    "program_name": f"{decade.decade_name} · {genre.genre_name}",
                })
        collections = session.exec(
            select(CollectionTrackRanking, Collection)
            .select_from(CollectionTrackRanking)
            .join(Collection, CollectionTrackRanking.collection_id == Collection.id)
            .where(CollectionTrackRanking.track_id.in_(fallback_ids))
            .where(CollectionTrackRanking.ranking.between(1, 100))
            .order_by(CollectionTrackRanking.id)
        ).all()
        for ranking, collection in collections:
            code = _COLLECTION_CODES.get(collection.slug)
            if code:
                destinations.setdefault(ranking.track_id, {
                    "program_code": code, "program_kind": "collection",
                    "program_name": collection.name,
                })
    results = []
    seen_artists = set()
    for track, artist in matches:
        result = {"track_id": track.id, "title": track.track_name,
                  "artist": track.artist_display_name or artist.artist_name}
        if artist.id in _SPOTLIGHT_CODES:
            result.update({"spotlight_artist": artist.artist_name,
                           "artist_code": _SPOTLIGHT_CODES[artist.id]})
        elif track.id in destinations:
            result.update(destinations[track.id])
        else:
            continue
        if by_artist:
            identity = (artist.id, result.get("artist_code") or result.get("program_code"))
            if identity in seen_artists:
                continue
            seen_artists.add(identity)
        results.append(result)
        if len(results) >= limit:
            break
    return results


def search_songs(session: Session, query: str, limit: int = 25) -> list[dict]:
    """Find recordings by title, retaining existing destination priority."""
    return _search_recordings(session, query, limit)


def search_artists(session: Session, query: str, limit: int = 25) -> list[dict]:
    """Find artists in approved programs, once per artist and destination.

    Spotlight artists retain their Spotlight destination. Other artists get
    an approved Nostalgia or Collection program and a matching starting track.
    """
    return _search_recordings(session, query, limit, by_artist=True)
