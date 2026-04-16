from __future__ import annotations

from sqlalchemy import select
from backend.models import Collection, CollectionTrackRanking, Track, Artist


def get_valid_collections(session, collection_group_slug: str | None = None) -> list[dict]:
    stmt = select(Collection)

    rows = session.exec(stmt).all()

    items: list[dict] = []
    for c in rows:
        group_slug = getattr(c, "collection_group_slug", None)
        group_name = getattr(c, "collection_group_name", None)

        if collection_group_slug and collection_group_slug != "ALL":
            if group_slug != collection_group_slug:
                continue

        items.append(
            {
                "collection_slug": c.slug,
                "collection_name": c.name,
                "collection_group_slug": group_slug,
                "collection_group_name": group_name,
            }
        )

    return items


def load_collection_rows(session, collection_slug: str):
    stmt = (
        select(CollectionTrackRanking, Track, Artist, Collection)
        .join(Collection, Collection.id == CollectionTrackRanking.collection_id)
        .join(Track, Track.id == CollectionTrackRanking.track_id)
        .join(Artist, Artist.id == Track.artist_id)
        .where(Collection.slug == collection_slug)
        .order_by(CollectionTrackRanking.ranking)
    )

    rows = session.exec(stmt).all()

    normalized = []
    for ctr, track, artist, collection in rows:
        normalized.append((track, artist, ctr, collection))

    return normalized