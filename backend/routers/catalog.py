from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
import logging
from sqlalchemy import func
from backend.models import CollectionTrackRanking
from backend.models import TrackRanking
from backend.models import DecadeGenre

from backend.database import get_db
from backend.models import Decade, Genre
from backend.models.collection_models import CollectionCategory, Collection

router = APIRouter(prefix="/api/catalog", tags=["Catalog"])

logger = logging.getLogger(__name__)


@router.get("/summary")
def get_catalog_summary(db: Session = Depends(get_db)):  # ✅ use get_db
    try:
        decades = [d.decade_name for d in db.exec(select(Decade)).all()]
        genres = [g.genre_name for g in db.exec(select(Genre)).all()]
        collections = [c.name for c in db.exec(select(Collection)).all()]

        logger.info("📚 Catalog summary retrieved: %d decades, %d genres, %d collections",
                    len(decades), len(genres), len(collections))

        return {
            "decades": decades,
            "genres": genres,
            "collections": collections
        }

    except Exception as e:
        logger.exception("❌ Failed to load catalog summary: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get-json-catalog")
def get_json_catalog(db: Session = Depends(get_db)):  # ✅ also use get_db here
    try:
        decades = db.exec(select(Decade).order_by(Decade.decade_name)).all()
        genres = db.exec(select(Genre).order_by(Genre.genre_name)).all()
        categories = db.exec(select(CollectionCategory).order_by(CollectionCategory.sort_order)).all()

        data = {
            "decades": [{"id": d.id, "name": d.decade_name, "slug": d.slug} for d in decades],
            "genres": [{"id": g.id, "name": g.genre_name, "slug": g.slug} for g in genres],
            "collections": []
        }

        for cat in categories:
            cols = db.exec(
                select(Collection).where(Collection.category_id == cat.id).order_by(Collection.name)
            ).all()
            data["collections"].append({
                "category": cat.name,
                "slug": cat.slug,
                "collections": [{"id": c.id, "name": c.name, "slug": c.slug} for c in cols]
            })

        return data

    except Exception as e:
        logger.exception("❌ Failed to load grouped catalog: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/grouped")
def get_grouped_catalog(db: Session = Depends(get_db)):
    """
    Returns decades, genres, and grouped collections (by CollectionCategory).
    Example structure:
    {
      "decades": [...],
      "genres": [...],
      "collections": [
        {
          "category": "Legends",
          "slug": "legends",
          "collections": [
            {"id": 1, "name": "Legends – Rock", "slug": "legends_rock"},
            {"id": 2, "name": "Legends – Pop", "slug": "legends_pop"}
          ]
        }
      ]
    }
    """
    try:
        # --- Decades and Genres ---
        decades = db.exec(select(Decade).order_by(Decade.decade_name)).all()
        genres = db.exec(select(Genre).order_by(Genre.genre_name)).all()

        # --- Categories ---
        categories = db.exec(
            select(CollectionCategory).order_by(CollectionCategory.sort_order, CollectionCategory.name)
        ).all()

        collections_grouped = []
        for category in categories:
            # get collections for this category
            collections = db.exec(
                select(Collection)
                .where(Collection.category_id == category.id)
                .order_by(Collection.name)
            ).all()

            collections_with_counts = []

            for c in collections:
                total_tracks = db.exec(
                    select(func.count())
                    .where(CollectionTrackRanking.collection_id == c.id)
                ).one()

                collections_with_counts.append({
                    "id": c.id,
                    "name": c.name,
                    "slug": c.slug,
                    "totalTracks": total_tracks
                })

            collections_grouped.append({
                "category": category.name,
                "slug": category.slug,
                "collections": collections_with_counts
            })

        # --- Decade-Genre Totals ---
        dg_totals = db.exec(
            select(
                Decade.slug.label("decade"),
                Genre.slug.label("genre"),
                func.count().label("total_tracks")
            )
            .join(DecadeGenre, DecadeGenre.decade_id == Decade.id)
            .join(Genre, DecadeGenre.genre_id == Genre.id)
            .join(TrackRanking, TrackRanking.decade_genre_id == DecadeGenre.id)
            .group_by(Decade.slug, Genre.slug)
        ).all()

        # --- Return structured response ---
        return {
            "decades": [
                {"id": d.id, "name": d.decade_name, "slug": d.slug}
                for d in decades
            ],
            "genres": [
                {"id": g.id, "name": g.genre_name, "slug": g.slug}
                for g in genres
            ],
            "collections": collections_grouped,

            # 👇 ADD THIS
            "decade_genre_totals": [
                {
                    "decade": row.decade,
                    "genre": row.genre,
                    "total_tracks": row.total_tracks
                }
                for row in dg_totals
            ]
        }

    except Exception as e:
        logger.exception("❌ Failed to load grouped catalog: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
