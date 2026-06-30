from fastapi import APIRouter, Query, Depends, HTTPException
from sqlmodel import SQLModel, select
import logging
from sqlalchemy import Table

from backend.database import engine, get_db
from backend.models.dbmodels import (
    Track,
    Artist,
    Collection,
    CollectionTrackRanking,
    TrackLocale,
    ArtistLocale,
    CollectionTrackRankingLocale,
)

collection_category_table = Table(
    "collection_category",
    SQLModel.metadata,
    autoload_with=engine,
)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/supabase/collections", tags=["Supabase: Collections"])


@router.get("/get-sequence")
async def get_sequence_collection(
    collection_slug: str | None = Query(None),
    collection_group_slug: str | None = Query(None),
    start_rank: int = Query(1),
    end_rank: int | None = Query(None),
    language: str = Query("en"),
    db=Depends(get_db),
):
    if not collection_slug and not collection_group_slug:
        raise HTTPException(
            status_code=400,
            detail="Either collection_slug or collection_group_slug is required."
        )

    resolved_collection_slug = collection_slug

    # ------------------------------------------------------------
    # Group slug -> choose one collection
    # ------------------------------------------------------------
    if not resolved_collection_slug and collection_group_slug:
        collection_rows = db.exec(
            select(Collection)
            .join(
                collection_category_table,
                collection_category_table.c.id == Collection.category_id
            )
            .where(collection_category_table.c.slug == collection_group_slug)
            .order_by(Collection.id)
        ).all()

        if not collection_rows:
            logger.warning(
                "📻 Collection group '%s': no collections found",
                collection_group_slug
            )
            return {"status": "empty", "total": 0, "tracks": []}

        # deterministic for testing
        chosen_collection = collection_rows[0]
        resolved_collection_slug = chosen_collection.slug

        logger.info(
            "📻 Collection group '%s' resolved to collection '%s'",
            collection_group_slug,
            resolved_collection_slug
        )

    filters = [
        Collection.slug == resolved_collection_slug,
        CollectionTrackRanking.ranking >= start_rank,
    ]

    if end_rank is not None:
        filters.append(CollectionTrackRanking.ranking <= end_rank)
    else:
        filters.append(CollectionTrackRanking.ranking <= 100)

    q = (
        select(Track, Artist, CollectionTrackRanking, Collection)
        .join(Artist, Artist.id == Track.artist_id)
        .join(CollectionTrackRanking, CollectionTrackRanking.track_id == Track.id)
        .join(Collection, Collection.id == CollectionTrackRanking.collection_id)
        .where(*filters)
        .order_by(CollectionTrackRanking.ranking)
    )

    rows = db.exec(q).all()

    if not rows:
        return {"status": "empty", "total": 0, "tracks": []}

    locale_code = "pt-BR" if language in ("ptbr", "pt-BR") else language

    tracks = []

    for track, artist, ctr, collection in rows:
        track_locale = None
        artist_locale = None
        ranking_locale = None

        if locale_code != "en":
            track_locale = db.exec(
                select(TrackLocale).where(
                    TrackLocale.track_id == track.id,
                    TrackLocale.language_code == locale_code,
                )
            ).first()

            artist_locale = db.exec(
                select(ArtistLocale).where(
                    ArtistLocale.artist_id == artist.id,
                    ArtistLocale.language_code == locale_code,
                )
            ).first()

            ranking_locale = db.exec(
                select(CollectionTrackRankingLocale).where(
                    CollectionTrackRankingLocale.collection_track_ranking_id == ctr.id,
                    CollectionTrackRankingLocale.language_code == locale_code,
                )
            ).first()

        detail_text = (
            getattr(track_locale, "detail_text", None)
            if track_locale
            else getattr(track, "detail", None)
        )

        artist_description_text = (
            getattr(artist_locale, "artist_description_text", None)
            if artist_locale
            else getattr(artist, "artist_description", None)
        )

        intro_text = (
            getattr(ranking_locale, "intro_text", None)
            if ranking_locale
            else getattr(ctr, "intro", None)
        )

        tracks.append({
            "rankingId": ctr.id,
            "rank": ctr.ranking,
            "trackName": track.track_name,
            "artistName": artist.artist_name,
            "yearReleased": getattr(track, "year_released", None),
            "durationMs": getattr(track, "duration_ms", None),
            "albumArtwork": getattr(track, "album_artwork", None),
            "artistArtwork": getattr(artist, "artist_artwork", None),
            "spotifyTrackId": getattr(track, "spotify_track_id", None),
            "albumName": getattr(track, "album_name", None),
            "collectionSlug": collection.slug,

            "intro": intro_text,
            "detail": detail_text,
            "artistDescription": artist_description_text,
        })

    logger.info(
        "📚 Collection '%s': returning %d tracks (range %s-%s)",
        resolved_collection_slug,
        len(rows),
        start_rank,
        end_rank if end_rank else "ALL"
    )

    return {
        "status": "ok",
        "total": len(tracks),
        "collection_slug": resolved_collection_slug,
        "tracks": tracks,
    }
