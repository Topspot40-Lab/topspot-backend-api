# backend/services/radio_render.py
from __future__ import annotations
from typing import Optional, List, Tuple
import textwrap
import re
from backend.models.dbmodels import TrackRanking

BOX_WIDTH = 100
HEADER_LINE = "=" * 51
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

TRow = Tuple[TrackRanking, str, str]  # (TrackRanking, decade_name, genre_name)


def clean_text(s: Optional[str]) -> Optional[str]:
    """Collapse whitespace and remove consecutive duplicate sentences."""
    if not s:
        return None
    s = " ".join(str(s).split())
    parts = _SENT_SPLIT.split(s)
    dedup: list[str] = []
    for p in parts:
        if p and (not dedup or p != dedup[-1]):
            dedup.append(p)
    out = " ".join(dedup).strip()
    return out or None


def box(title: str, body: Optional[str], width: int = BOX_WIDTH) -> str:
    """Render a pretty box with a title and wrapped body (with a leading newline)."""
    if not body or not str(body).strip():
        body = "(none)"
    wrapped = textwrap.fill(str(body).strip(), width=width)
    line = "─" * width
    return f"\n{line}\n{title}\n{line}\n{wrapped}\n{line}"


def kv_line(left: str, right: str, width: int = BOX_WIDTH) -> str:
    """Left + some spaces + right, clipped to width if needed."""
    max_left = max(0, width - len(right) - 1)
    if len(left) > max_left and max_left >= 2:
        left = left[: max_left - 1] + "…"
    space = max(1, width - len(left) - len(right))
    return f"{left}{' ' * space}{right}"


def render_header(
    *,
    track_name: str,
    artist_name: str,
    track_id: Optional[str],
    lang: str,
    tr_rows: List[TRow],
) -> str:
    """Build the top header. If no rankings → say so. Else print each rank/decade/genre + intro."""
    lines: List[str] = []
    lines.append(HEADER_LINE)
    lines.append("RANDOM TRACK PICK")
    lines.append(kv_line(f"Title: {track_name}", f"Artist: {artist_name}"))
    lines.append(kv_line(f"track_id: {track_id or '—'}", f"lang: {lang}"))

    if not tr_rows:
        lines.append(kv_line("Rank: —  Decade: —", "Genre: —"))
        lines.append("This Track not in the Ranking Table")
    else:
        for tr, decade_name, genre_name in tr_rows:
            lines.append(
                kv_line(f"Rank: #{tr.ranking:02d}  Decade: {decade_name}", f"Genre: {genre_name}")
            )
            intro_text = clean_text(getattr(tr, "intro", None))
            lines.append(f"Intro: {intro_text}" if intro_text else "Intro: (no intro text)")
    lines.append(HEADER_LINE)
    return "\n".join(lines)
