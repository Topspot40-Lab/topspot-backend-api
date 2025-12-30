from datetime import datetime, UTC
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import CheckConstraint, Column
from sqlalchemy import Enum as SqlEnum
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from sqlalchemy.orm import relationship as sa_relationship  # add this

from backend.models.enums import ModeFlag

if TYPE_CHECKING:
    from backend.models.collection_models import CollectionTrackRanking
# ─────────────────────────────────────────────────────────────────────────────
# Core entities
# ─────────────────────────────────────────────────────────────────────────────

class DecadeGenreTrivia(SQLModel, table=True):
    __tablename__ = "decade_genre_trivia"

    id: Optional[int] = Field(default=None, primary_key=True)
    decade_genre_id: int = Field(foreign_key="decade_genre.id")
    trivia: str
    trivia_mp3_url: Optional[str] = None
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))


class Artist(SQLModel, table=True):
    __tablename__ = "artist"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    artist_name: str
    spotify_artist_id: Optional[str] = Field(default=None, nullable=True)
    artist_artwork: Optional[str] = None
    artist_description: Optional[str] = None
    not_on_spotify: bool = Field(default=False)
    language: Optional[str] = Field(default="en", max_length=2)

    # Relationships
    tracks_as_main: list["Track"] = Relationship(
        back_populates="artist",
        sa_relationship_kwargs={"foreign_keys": "[Track.artist_id]"},
    )
    tracks_as_featured: list["Track"] = Relationship(
        back_populates="featured_artist",
        sa_relationship_kwargs={"foreign_keys": "[Track.featured_artist_id]"},
    )

class Decade(SQLModel, table=True):
    __tablename__ = "decade"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    decade_name: str
    slug: Optional[str] = Field(default=None, index=True)         # NEW (optional)
    description: Optional[str] = Field(default=None)              # NEW (optional)


class Genre(SQLModel, table=True):
    __tablename__ = "genre"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    genre_name: str
    slug: Optional[str] = Field(default=None, index=True)         # NEW (optional)
    description: Optional[str] = Field(default=None)              # NEW (optional)


class Language(SQLModel, table=True):
    __tablename__ = "language"

    code: str = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)


class ArtistGenre(SQLModel, table=True):
    __tablename__ = "artist_genre"
    __table_args__ = {"extend_existing": True}

    id: int = Field(default=None, primary_key=True)
    artist_id: Optional[int] = Field(default=None, foreign_key="artist.id")
    genre_id: int = Field(foreign_key="genre.id")


class DecadeGenre(SQLModel, table=True):
    __tablename__ = "decade_genre"
    __table_args__ = {"extend_existing": True}

    id: int = Field(default=None, primary_key=True)
    decade_id: Optional[int] = Field(default=None, foreign_key="decade.id")
    genre_id: Optional[int] = Field(default=None, foreign_key="genre.id")
    slug: Optional[str] = Field(default=None, index=True)  # NEW (optional)

    decade: Optional["Decade"] = Relationship()


class TrackGenre(SQLModel, table=True):
    __tablename__ = "track_genre"
    __table_args__ = {"extend_existing": True}

    track_id: int = Field(primary_key=True, foreign_key="track.id")
    genre_id: int = Field(foreign_key="genre.id")


class Top40GenreRanking(SQLModel, table=True):
    __tablename__ = "top40_genre_ranking"
    __table_args__ = {"extend_existing": True}

    id: int = Field(default=None, primary_key=True)
    genre_id: int = Field(foreign_key="genre.id")
    artist_id: int = Field(foreign_key="artist.id")
    track_id: int = Field(foreign_key="track.id")
    ranking: int = Field(nullable=False)
    info: Optional[str] = Field(default=None)
    detail: Optional[str] = Field(default=None)
    created_at: Optional[datetime] = Field(default=None)
    intro_mp3_url: Optional[str] = Field(default=None)


class TrackRanking(SQLModel, table=True):
    __tablename__ = "track_ranking"
    __table_args__ = (
        UniqueConstraint("decade_genre_id", "ranking", name="uix_rank_per_decade_genre"),
        UniqueConstraint("decade_genre_id", "track_id", name="uix_track_per_decade_genre"),
        CheckConstraint("ranking >= 1", name="chk_tr_ranking_positive"),
        {"extend_existing": True},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    track_id: int = Field(foreign_key="track.id", index=True)
    decade_genre_id: int = Field(foreign_key="decade_genre.id", index=True)

    # single list for now
    tracklist_id: int = Field(default=1)

    ranking: int = Field(index=True)
    intro: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    track: Optional["Track"] = Relationship(back_populates="rankings")
    decade_genre: Optional["DecadeGenre"] = Relationship()


class Tracklist(SQLModel, table=True):
    __tablename__ = "track_list"
    __table_args__ = {"extend_existing": True}

    id: int = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    curator: Optional[str] = Field(default=None)
    is_official: Optional[bool] = Field(default=False)
    language: Optional[str] = Field(default="en", max_length=2)
    notes: Optional[str] = Field(default=None)
    created_at: Optional[datetime] = Field(default=None)

class Track(SQLModel, table=True):
    __tablename__ = "track"
    __table_args__ = {"extend_existing": True}

    id: int = Field(default=None, primary_key=True)
    track_name: str = Field(nullable=False)
    album_name: Optional[str] = Field(default=None)
    artist_display_name: Optional[str] = Field(default=None)
    spotify_track_id: str = Field(nullable=False)

    mode_flag: ModeFlag = Field(
        sa_column=Column(SqlEnum(ModeFlag, name="modeflag", create_constraint=True)),
        default=ModeFlag.SOLO,
    )
    duration_ms: Optional[int] = Field(default=None)
    popularity: Optional[int] = Field(default=None)
    album_artwork: Optional[str] = Field(default=None)
    year_released: Optional[int] = Field(default=None)

    artist_id: int = Field(foreign_key="artist.id")                     # main artist
    featured_artist_id: Optional[int] = Field(default=None, foreign_key="artist.id")

    is_explicit: Optional[bool] = Field(default=False)
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))
    detail: Optional[str] = Field(default=None)
    language: Optional[str] = Field(default="en", max_length=2)

    # ── NEW: media/source metadata for TV / film / stage etc. ───────────────
    source_type: Optional[str] = Field(default=None)         # e.g., "TV", "Film", "Stage", "Game"
    source_title: Optional[str] = Field(default=None)        # e.g., show / film / production title
    years_on_air: Optional[str] = Field(default=None)        # e.g., "1959–1973" (TEXT)
    source_role: Optional[str] = Field(default=None)         # e.g., "THEME", "OPENING", "CLOSING"
    version_notes: Optional[str] = Field(default=None)       # e.g., "TV Opening", "Single edit"

    # Relationships
    artist: "Artist" = Relationship(
        back_populates="tracks_as_main",
        sa_relationship_kwargs={"foreign_keys": "[Track.artist_id]"},
    )
    featured_artist: Optional["Artist"] = Relationship(
        back_populates="tracks_as_featured",
        sa_relationship_kwargs={"foreign_keys": "[Track.featured_artist_id]"},
    )
    rankings: list["TrackRanking"] = Relationship(back_populates="track")

    # ✅ FIX: use SQLModel's Relationship with kwargs, not a raw sa_relationship
    collection_rankings: List["CollectionTrackRanking"] = Relationship(
        back_populates="track",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class TrackRankingLocale(SQLModel, table=True):
    __tablename__ = "track_ranking_locale"
    __table_args__ = (
        UniqueConstraint("track_ranking_id", "language_code", name="uix_trl_rank_lang"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    track_ranking_id: int = Field(foreign_key="track_ranking.id")
    language_code: str
    intro_text: str
    tts_bucket: Optional[str] = None
    tts_key: Optional[str] = None


class TrackLocale(SQLModel, table=True):
    __tablename__ = "track_locale"
    __table_args__ = (
        UniqueConstraint("track_id", "language_code", name="uix_tl_track_lang"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    track_id: int = Field(foreign_key="track.id")
    language_code: str
    detail_text: str
    tts_bucket: Optional[str] = None
    tts_key: Optional[str] = None


class ArtistLocale(SQLModel, table=True):
    __tablename__ = "artist_locale"
    __table_args__ = (
        UniqueConstraint("artist_id", "language_code", name="uix_al_artist_lang"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    artist_id: int = Field(foreign_key="artist.id")
    language_code: str
    artist_description_text: str
    tts_bucket: Optional[str] = None
    tts_key: Optional[str] = None


# Re-exports from collection_models
from .collection_models import (
    Collection,
    CollectionTrackRanking,
    CollectionTrackRankingLocale,
)

__all__ = [
    # core models
    "DecadeGenreTrivia",
    "Artist",
    "Decade",
    "Genre",
    "Language",
    "ArtistGenre",
    "DecadeGenre",
    "TrackGenre",
    "Top40GenreRanking",
    "TrackRanking",
    "Tracklist",
    "Track",
    "TrackRankingLocale",
    "TrackLocale",
    "ArtistLocale",
    # collections
    "Collection",
    "CollectionTrackRanking",
    "CollectionTrackRankingLocale",
]
