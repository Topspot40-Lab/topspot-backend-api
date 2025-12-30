# backend/models/enums.py
from __future__ import annotations
from enum import Enum

# --- Playback / performer context on a track ---
class ModeFlag(str, Enum):
    SOLO     = "SOLO"
    DUET     = "DUET"
    FEATURED = "FEATURED"
    GROUP    = "GROUP"
    UNKNOWN  = "UNKNOWN"

# --- High-level collection classification ---
class CollectionType(str, Enum):
    DECADE_GENRE = "DECADE_GENRE"
    COLLECTION   = "COLLECTION"

# --- Language codes (canonical / BCP-47 where applicable) ---
class LanguageCode(str, Enum):
    EN    = "en"
    ES    = "es"
    PT_BR = "pt-BR"   # canonical; alias 'ptbr' can be normalized at input

# --- Optional: keep if you use fixed decade labels in UI/filters ---
class DecadeName(str, Enum):
    Y1950s = "1950s"
    Y1960s = "1960s"
    Y1970s = "1970s"
    Y1980s = "1980s"
    Y1990s = "1990s"
    Y2000s = "2000s"
    Y2010s = "2010s"
    Y2020s = "2020s"

__all__ = [
    "ModeFlag",
    "CollectionType",
    "LanguageCode",
    "DecadeName",
]
