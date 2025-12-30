# backend/models/__init__.py

# Keep enums here (no ORM/relationship loading), safe to import early.
from .enums import ModeFlag

# Re-export ORM models so callers can do: from backend.models import Track, Artist, ...
from .dbmodels import (
    # taxonomy / linking
    Genre, Decade, DecadeGenre, ArtistGenre,
    # core entities
    Artist, Track, TrackRanking,
    # locales
    TrackRankingLocale, TrackLocale, ArtistLocale, Language,
)

from .collection_models import (
    Collection, CollectionCategory, CollectionTrackRanking, CollectionTrackRankingLocale,
)

__all__ = [
    # enums
    "ModeFlag",
    # taxonomy / linking
    "Genre", "Decade", "DecadeGenre", "ArtistGenre",
    # core entities
    "Artist", "Track", "TrackRanking",
    # locales
    "TrackRankingLocale", "TrackLocale", "ArtistLocale", "Language",
    # collections
    "Collection", "CollectionCategory", "CollectionTrackRanking", "CollectionTrackRankingLocale",
]
