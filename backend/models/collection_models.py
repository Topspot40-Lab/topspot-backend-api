from __future__ import annotations

from typing import Optional, TYPE_CHECKING, List
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import UniqueConstraint, CheckConstraint, Column, ForeignKey, Text

from sqlalchemy.orm import relationship as sa_relationship  # ✅ lowercase alias

if TYPE_CHECKING:
    from backend.models.dbmodels import Track  # type-only import


# ────────────────────────────────────────────────
# 🎵 CollectionCategory — new parent grouping table
# ────────────────────────────────────────────────
class CollectionCategory(SQLModel, table=True):
    __tablename__ = "collection_category"
    __table_args__ = (UniqueConstraint("slug", name="uq_collection_category_slug"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    slug: str = Field(index=True)

    # DB column is 'description'; expose as 'intro' in Python for consistency
    intro: Optional[str] = Field(
        default=None,
        sa_column=Column("description", Text, nullable=True)
    )

    sort_order: int = Field(default=0)

    collections: List["Collection"] = Relationship(
        sa_relationship=sa_relationship(
            "Collection",
            back_populates="category",
            cascade="all, delete-orphan",
        )
    )


# ────────────────────────────────────────────────
# 🎶 Collection — holds playlist-like groups (Stage & Screen, Legends, etc.)
# ────────────────────────────────────────────────
class Collection(SQLModel, table=True):
    __tablename__ = "collection"
    __table_args__ = (UniqueConstraint("slug", name="uq_collection_slug"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    slug: str = Field(index=True)
    intro: Optional[str] = None

    # ✅ New category linkage
    category_id: Optional[int] = Field(
        sa_column=Column(
            ForeignKey("collection_category.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        )
    )

    category: Optional["CollectionCategory"] = Relationship(
        sa_relationship=sa_relationship(
            "CollectionCategory",
            back_populates="collections",
        )
    )

    # ✅ Relationship to ranked tracks in this collection
    rankings: List["CollectionTrackRanking"] = Relationship(
        sa_relationship=sa_relationship(
            "CollectionTrackRanking",
            back_populates="collection",
            cascade="all, delete-orphan",
        )
    )


# ────────────────────────────────────────────────
# 🏆 CollectionTrackRanking — links tracks to a collection (ranked)
# ────────────────────────────────────────────────
class CollectionTrackRanking(SQLModel, table=True):
    __tablename__ = "collection_track_ranking"
    __table_args__ = (
        UniqueConstraint("collection_id", "track_id", name="uix_ctr_collection_track"),
        UniqueConstraint("collection_id", "ranking", name="uix_ctr_collection_rank"),
        CheckConstraint("ranking > 0", name="ck_ctr_ranking_positive"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    collection_id: int = Field(
        sa_column=Column(
            ForeignKey("collection.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    track_id: int = Field(
        sa_column=Column(
            ForeignKey("track.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )

    ranking: int = Field(index=True)
    intro: Optional[str] = None

    collection: "Collection" = Relationship(
        sa_relationship=sa_relationship(
            "Collection",
            back_populates="rankings",
        )
    )

    locales: List["CollectionTrackRankingLocale"] = Relationship(
        sa_relationship=sa_relationship(
            "CollectionTrackRankingLocale",
            back_populates="ranking",
            cascade="all, delete-orphan",
        )
    )

    # ✅ Link to Track model (for eager loading or deletion cascade)
    track: "Track" = Relationship(
        sa_relationship=sa_relationship(
            "Track",
            back_populates="collection_rankings",
        )
    )


# ────────────────────────────────────────────────
# 🌐 CollectionTrackRankingLocale — per-language text & TTS keys
# ────────────────────────────────────────────────
class CollectionTrackRankingLocale(SQLModel, table=True):
    __tablename__ = "collection_track_ranking_locale"
    __table_args__ = (
        UniqueConstraint("collection_track_ranking_id", "lang", name="uq_ctr_locale"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    collection_track_ranking_id: int = Field(
        sa_column=Column(
            ForeignKey("collection_track_ranking.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )

    lang: str
    intro_text: str
    tts_key: Optional[str] = None

    ranking: "CollectionTrackRanking" = Relationship(
        sa_relationship=sa_relationship(
            "CollectionTrackRanking",
            back_populates="locales",
        )
    )
