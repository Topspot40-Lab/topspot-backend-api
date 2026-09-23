"""Session-local selection helpers used exclusively by radio program modes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar


T = TypeVar("T")


def unused_session_candidates(
    candidates: Sequence[T],
    used: set[object],
    key: Callable[[T], object],
) -> list[T]:
    """Prefer candidates not used in this radio session, without resetting history.

    When this particular candidate set is exhausted, callers can still choose from
    it.  Keeping the session history lets a later source prefer any track that has
    not yet been heard elsewhere in the session.
    """
    unused = [candidate for candidate in candidates if key(candidate) not in used]
    return unused or list(candidates)


def unused_source_candidates(
    candidates: Sequence[T], used: set[object], key: Callable[[T], object]
) -> list[T]:
    """Return unused sources, resetting only after the whole source pool is used."""
    unused = [candidate for candidate in candidates if key(candidate) not in used]
    if unused:
        return unused
    used.clear()
    return list(candidates)
