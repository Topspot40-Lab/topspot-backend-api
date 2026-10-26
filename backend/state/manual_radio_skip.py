"""Scoped, one-shot manual skips for backend-owned Radio narration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class ManualRadioSkipTarget:
    playback_session_id: str
    ranking_id: int | None
    spotify_track_id: str | None


_events: dict[str, asyncio.Event] = {}
_targets: dict[str, ManualRadioSkipTarget] = {}


def _event(user_id: str) -> asyncio.Event:
    return _events.setdefault(user_id, asyncio.Event())


def request_manual_radio_skip(user_id: str, target: ManualRadioSkipTarget) -> bool:
    """Return False for an identical pending request so duplicate clicks are inert."""
    if _targets.get(user_id) == target and _event(user_id).is_set():
        return False
    _targets[user_id] = target
    _event(user_id).set()
    return True


def _matches(user_id: str, target: ManualRadioSkipTarget) -> bool:
    return _targets.get(user_id) == target and _event(user_id).is_set()


async def wait_for_radio_event_or_manual_skip(
    user_id: str,
    event: asyncio.Event,
    target: ManualRadioSkipTarget,
) -> bool:
    """Wait for normal completion; True means this exact Radio track was skipped."""
    skip_event = _event(user_id)
    normal_wait = asyncio.create_task(event.wait())
    skip_wait = asyncio.create_task(skip_event.wait())
    done, pending = await asyncio.wait(
        {normal_wait, skip_wait}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    for task in pending:
        try:
            await task
        except asyncio.CancelledError:
            pass

    if skip_wait in done and _matches(user_id, target):
        _targets.pop(user_id, None)
        skip_event.clear()
        return True
    return False
