from __future__ import annotations

import logging
from sqlalchemy import select
from backend.models import Collection, CollectionTrackRanking, Track, Artist

logger = logging.getLogger(__name__)


def get_valid_collections(session, collection_group_slug: str | None = None) -> list[dict]:
    stmt = select(Collection)

    rows = session.exec(stmt).all()

    items: list[dict] = []
    for (c,) in rows:
        category = getattr(c, "category", None)

        group_slug = getattr(category, "slug", None) if category else None
        group_name = getattr(category, "name", None) if category else None

        if collection_group_slug and collection_group_slug != "ALL":
            if group_slug != collection_group_slug:
                continue

        logger.info("🧪 COLLECTION ROW: %s", c)

        items.append(
            {
                "collection_slug": getattr(c, "collection_slug", None) or getattr(c, "slug", None),
                "collection_name": getattr(c, "collection_name", None) or getattr(c, "name", None),
                "collection_group_slug": group_slug,
                "collection_group_name": group_name,
            }
        )

    return items


def load_collection_rows(session, collection_slug: str):
    from backend.models import (
        CollectionTrackRankingLocale,
        TrackLocale,
        ArtistLocale,
    )

    stmt = (
        select(
            CollectionTrackRanking,
            Track,
            Artist,
            Collection,
            CollectionTrackRankingLocale,
            TrackLocale,
            ArtistLocale,
        )
        .join(Collection, Collection.id == CollectionTrackRanking.collection_id)
        .join(Track, Track.id == CollectionTrackRanking.track_id)
        .join(Artist, Artist.id == Track.artist_id)
        .join(
            CollectionTrackRankingLocale,
            CollectionTrackRankingLocale.collection_track_ranking_id == CollectionTrackRanking.id,
            isouter=True,
        )
        .join(
            TrackLocale,
            TrackLocale.track_id == Track.id,
            isouter=True,
        )
        .join(
            ArtistLocale,
            ArtistLocale.artist_id == Artist.id,
            isouter=True,
        )
        .where(Collection.slug == collection_slug)
        .order_by(CollectionTrackRanking.ranking)
    )

    rows = session.exec(stmt).all()

    normalized = []
    for ctr, track, artist, collection, ctr_locale, track_locale, artist_locale in rows:
        normalized.append(
            (
                track,
                artist,
                ctr,
                collection,
                ctr_locale,
                track_locale,
                artist_locale,
            )
        )

    return normalized
