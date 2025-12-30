# backend/models/enum_utils.py
from typing import Optional
from backend.models.enums import ModeFlag

def normalize_mode_flag(value: Optional[str]) -> ModeFlag:
    if not value:
        return ModeFlag.UNKNOWN
    v = value.strip().upper()
    # Accept a couple of common alternates
    if v in {"SOLO","DUET","FEATURED","GROUP","UNKNOWN"}:
        return ModeFlag(v)
    if v in {"FEAT","FEAT.", "FT", "FT."}:
        return ModeFlag.FEATURED
    return ModeFlag.UNKNOWN
