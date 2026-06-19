from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from fastapi import Cookie, HTTPException

from backend.isaiah.jwt_session import decode_jwt_token


@dataclass
class PlaybackRuntime:
    status: Any
    flags: Any
    current_task: asyncio.Task | None = None
    track_done_event: asyncio.Event = field(default_factory=asyncio.Event)
    narration_done_event: asyncio.Event = field(default_factory=asyncio.Event)
    skip_event: asyncio.Event = field(default_factory=asyncio.Event)
    sequence_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    play_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    spotify_client: Any = None


runtime_by_user: dict[str, PlaybackRuntime] = {}
_task_user: dict[asyncio.Task, str] = {}


def _new_runtime() -> PlaybackRuntime:
    from backend.state.playback_flags import PlaybackFlags
    from backend.state.playback_state import PlaybackStatus

    return PlaybackRuntime(status=PlaybackStatus(), flags=PlaybackFlags())


def get_runtime_for_user(user_id: str) -> PlaybackRuntime:
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user id")

    key = str(user_id)
    runtime = runtime_by_user.get(key)
    if runtime is None:
        runtime = _new_runtime()
        runtime_by_user[key] = runtime
    return runtime


def user_id_from_token(access_token: str | None) -> str:
    payload = decode_jwt_token(access_token) if access_token else None
    if not payload or not payload.get("user_id"):
        raise HTTPException(status_code=401, detail="Invalid or missing session")
    return str(payload["user_id"])


def bind_task(task: asyncio.Task, user_id: str) -> None:
    _task_user[task] = str(user_id)
    task.add_done_callback(lambda done_task: _task_user.pop(done_task, None))


def bind_current_task(user_id: str) -> str:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None

    if task is None:
        raise HTTPException(status_code=500, detail="Playback request is not running in an asyncio task")

    _task_user[task] = str(user_id)
    get_runtime_for_user(user_id)
    return str(user_id)


async def bind_request_user(access_token: str | None = Cookie(None)) -> str:
    return bind_current_task(user_id_from_token(access_token))


def current_user_id() -> str:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None

    if task is not None:
        user_id = _task_user.get(task)
        if user_id:
            return user_id

    raise HTTPException(status_code=401, detail="Playback runtime is not bound to a user")


def current_runtime() -> PlaybackRuntime:
    return get_runtime_for_user(current_user_id())


def snapshot_dataclass(obj: Any) -> dict[str, Any]:
    target = obj._target() if hasattr(obj, "_target") else obj
    if not is_dataclass(target):
        raise TypeError("Expected a dataclass-backed playback object")
    return asdict(target)


class RuntimeObjectProxy:
    def __init__(self, attr_name: str):
        object.__setattr__(self, "_attr_name", attr_name)

    def _target(self):
        return getattr(current_runtime(), object.__getattribute__(self, "_attr_name"))

    def __getattr__(self, name: str):
        return getattr(self._target(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._target(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(self._target(), name)


class RuntimeEventProxy:
    def __init__(self, attr_name: str):
        self._attr_name = attr_name

    def _target(self) -> asyncio.Event:
        return getattr(current_runtime(), self._attr_name)

    def set(self) -> None:
        self._target().set()

    def clear(self) -> None:
        self._target().clear()

    def is_set(self) -> bool:
        return self._target().is_set()

    async def wait(self) -> bool:
        return await self._target().wait()
