from fastapi import APIRouter, Query
from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import (
    MusicDocuseries,
    MusicDocuseriesCollection,
    MusicDocuseriesLocale,
)
from backend.models.studio_models import (
    StudioProductionAsset,
)

router = APIRouter(
    prefix="/music-docuseries",
    tags=["music-docuseries"],
)


@router.get("/collections")
def list_docuseries_collections():
    with Session(engine) as session:
        rows = session.exec(
            select(MusicDocuseriesCollection)
            .where(MusicDocuseriesCollection.is_active == True)
            .order_by(MusicDocuseriesCollection.sort_order)
        ).all()

    return [
        {
            "id": row.id,
            "slug": row.slug,
            "name": row.name,
            "description": row.description,
            "sort_order": row.sort_order,
        }
        for row in rows
    ]


@router.get("/items")
def list_docuseries_items(
        collection_slug: str = Query(...),
):
    with Session(engine) as session:
        collection = session.exec(
            select(MusicDocuseriesCollection)
            .where(MusicDocuseriesCollection.slug == collection_slug)
        ).first()

        if not collection:
            return []

        rows = session.exec(
            select(MusicDocuseries)
            .where(MusicDocuseries.collection_id == collection.id)
            .where(MusicDocuseries.is_active == True)
            .order_by(MusicDocuseries.sort_order)
        ).all()

    return [
        {
            "id": row.id,
            "slug": row.slug,
            "title": row.title,
            "short_description": row.short_description,
            "artwork_url": row.artwork_url,
            "target_length": row.target_length,
            "sort_order": row.sort_order,
        }
        for row in rows
    ]


@router.post("/play")
def play_docuseries(
        slug: str = Query(...),
        language: str = Query("en"),
):
    with Session(engine) as session:
        result = session.exec(
            select(MusicDocuseries, MusicDocuseriesLocale)
            .join(
                MusicDocuseriesLocale,
                MusicDocuseriesLocale.docuseries_id == MusicDocuseries.id,
                isouter=True,
            )
            .where(MusicDocuseries.slug == slug)
            .where(
                (MusicDocuseriesLocale.language_code == language)
                | (MusicDocuseriesLocale.language_code.is_(None))
            )
        ).first()

        if not result:
            return {
                "ok": False,
                "message": "Music docuseries item not found",
            }

        item, locale = result

        youtube_asset = session.exec(
            select(StudioProductionAsset)
            .where(
                StudioProductionAsset.production_type
                == "documentary"
            )
            .where(
                StudioProductionAsset.source_id
                == item.id
            )
            .where(
                StudioProductionAsset.asset_type
                == "localized_video"
            )
            .where(
                StudioProductionAsset.language_code
                == language
            )
            .where(
                StudioProductionAsset.status
                == "published"
            )
            .where(
                StudioProductionAsset.is_current
                == True
            )
        ).first()

        youtube_url = (
            youtube_asset.youtube_url
            if youtube_asset
            else None
        )

        return {
            "ok": True,
            "content_type": "music_docuseries",
            "id": item.id,
            "slug": item.slug,
            "title": item.title,
            "story_text": locale.story_text if locale else None,
            "duration_seconds": locale.duration_seconds if locale else None,
            "tts_bucket": locale.tts_bucket if locale else None,
            "tts_key": locale.tts_key if locale else None,
            "artwork_url": item.artwork_url,
            "target_length": item.target_length,
            "has_youtube_video": bool(youtube_url),
            "youtube_video_id": (
                youtube_asset.youtube_video_id
                if youtube_asset
                else None
            ),
            "youtube_url": youtube_url,
            "bed_bucket": "audio-en",
            "bed_key": "bed-tracks/docuseries/bed_01.mp3",
        }