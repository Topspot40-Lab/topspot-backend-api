# backend/services/localization.py
from __future__ import annotations
from typing import Tuple, Optional, Iterable
from sqlmodel import select

try:
    from backend.models.dbmodels import TrackRankingLocale, TrackLocale
    HAS_TR_LOCALE = True
except Exception:
    TrackRankingLocale = None  # type: ignore
    TrackLocale = None         # type: ignore
    HAS_TR_LOCALE = False

def canon_lang(lang: Optional[str]) -> str:
    if not lang:
        return "en"
    s = lang.strip().lower().replace("_", "-")
    if s.startswith("es"):
        return "es"
    if s.startswith("pt"):
        return "ptbr"
    return "en"

def _first_attr(obj, names: Iterable[str]) -> Optional[str]:
    """Return the first attribute name that exists on obj (class or instance)."""
    for n in names:
        if hasattr(obj, n):
            return n
    return None

def get_localized_texts(db, lang: str, rk, track) -> Tuple[str, str]:
    """
    Returns (intro_text, detail_text) using locale tables when present:
      intro  -> TrackRankingLocale (by track_ranking_id or composite keys)
      detail -> TrackLocale (by track_id)
    Prefers 'language_code' for filtering; falls back to 'language'/'lang'/'locale'.
    Falls back to EN and finally to base fields on rk/track.
    """
    req = canon_lang(lang)
    order = (req, "en") if req != "en" else ("en",)

    # Base fallbacks (EN fields already on ranking/track)
    base_intro  = getattr(rk, "intro", None) or getattr(rk, "info", None) or ""
    base_detail = getattr(track, "detail", None) or getattr(rk, "detail", None) or ""

    intro_text: Optional[str] = None
    detail_text: Optional[str] = None

    # ---------- TrackRankingLocale (INTRO) ----------
    if HAS_TR_LOCALE and rk is not None and getattr(rk, "id", None) is not None:
        try:
            lang_col   = _first_attr(TrackRankingLocale, ("language_code", "language", "lang", "locale"))
            intro_col  = _first_attr(TrackRankingLocale, ("intro", "intro_text"))
            tr_fk_col  = _first_attr(TrackRankingLocale, ("track_ranking_id",))
            # composite fallback (if your schema uses these instead of track_ranking_id)
            tr_tid_col = _first_attr(TrackRankingLocale, ("track_id",))
            tr_dg_col  = _first_attr(TrackRankingLocale, ("decade_genre_id", "dg_id"))
            tr_rankcol = _first_attr(TrackRankingLocale, ("ranking", "rank"))

            for code in order:
                if not lang_col or not intro_col:
                    break

                q = select(TrackRankingLocale)
                where = []
                if tr_fk_col:
                    where.append(getattr(TrackRankingLocale, tr_fk_col) == rk.id)
                elif tr_tid_col and tr_dg_col and tr_rankcol:
                    where.extend([
                        getattr(TrackRankingLocale, tr_tid_col) == getattr(rk, "track_id"),
                        getattr(TrackRankingLocale, tr_dg_col) == getattr(rk, "decade_genre_id"),
                        getattr(TrackRankingLocale, tr_rankcol) == getattr(rk, "ranking"),
                    ])
                else:
                    where = []

                if where:
                    q = q.where(*where, getattr(TrackRankingLocale, lang_col) == code).limit(1)
                    row = db.exec(q).first()
                    if row:
                        val = getattr(row, intro_col, None)
                        if val:
                            intro_text = val
                            break
        except Exception:
            pass  # keep fallbacks

    # ---------- TrackLocale (DETAIL) ----------
    if TrackLocale is not None and track is not None and getattr(track, "id", None) is not None:
        try:
            lang_col   = _first_attr(TrackLocale, ("language_code", "language", "lang", "locale"))
            detail_col = _first_attr(TrackLocale, ("detail", "detail_text", "description", "desc"))
            tk_fk_col  = _first_attr(TrackLocale, ("track_id", "fk_track_id", "song_id"))

            for code in order:
                if not (lang_col and detail_col and tk_fk_col):
                    break
                q = (
                    select(TrackLocale)
                    .where(getattr(TrackLocale, tk_fk_col) == track.id,
                           getattr(TrackLocale, lang_col) == code)
                    .limit(1)
                )
                row = db.exec(q).first()
                if row:
                    val = getattr(row, detail_col, None)
                    if val:
                        detail_text = val
                        break
        except Exception:
            pass

    return (intro_text or base_intro, detail_text or base_detail)
