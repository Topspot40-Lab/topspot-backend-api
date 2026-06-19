# backend/state/narration.py
import asyncio

narration_done_events: dict[str, asyncio.Event] = {}
track_done_events: dict[str, asyncio.Event] = {}


def narration_done_event(user_id: str) -> asyncio.Event:
    if user_id not in narration_done_events:
        narration_done_events[user_id] = asyncio.Event()

    return narration_done_events[user_id]


def track_done_event(user_id: str) -> asyncio.Event:
    if user_id not in track_done_events:
        track_done_events[user_id] = asyncio.Event()

    return track_done_events[user_id]