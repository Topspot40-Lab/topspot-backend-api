"""Atomic local state and locking for documentary factory batch runs."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Final, Literal

BatchStatus = Literal["pending", "running", "completed", "failed", "skipped"]
VALID_BATCH_STATUSES: Final[frozenset[str]] = frozenset(
    {"pending", "running", "completed", "failed", "skipped"}
)
SUPPORTED_SOURCE_TYPES: Final[frozenset[str]] = frozenset(
    {"music_docuseries", "artist_story"}
)
LEDGER_VERSION: Final = 1


def now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class BatchItem:
    source_type: str
    source_id: int
    slug: str
    eligible: bool
    reason: str
    status: BatchStatus
    attempts: int
    created_at: str
    started_at: str | None
    finished_at: str | None
    updated_at: str
    error: str | None

    @property
    def identity(self) -> tuple[str, int]:
        return (self.source_type, self.source_id)

    def payload(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_payload(cls, value: object) -> BatchItem:
        if not isinstance(value, dict):
            raise ValueError("Invalid batch ledger item")
        required_strings = (
            "source_type", "slug", "reason", "created_at", "updated_at",
        )
        if not all(isinstance(value.get(field), str) for field in required_strings):
            raise ValueError("Invalid batch ledger item")
        source_type = value["source_type"]
        source_id = value.get("source_id")
        attempts = value.get("attempts")
        slug = value["slug"]
        if source_type not in SUPPORTED_SOURCE_TYPES:
            raise ValueError("Unsupported batch ledger source type")
        if (
            not isinstance(source_id, int)
            or isinstance(source_id, bool)
            or source_id <= 0
        ):
            raise ValueError("Invalid batch ledger source ID")
        if not isinstance(slug, str) or not slug.strip():
            raise ValueError("Invalid batch ledger slug")
        if not isinstance(value.get("eligible"), bool):
            raise ValueError("Invalid batch ledger item")
        if value.get("status") not in VALID_BATCH_STATUSES:
            raise ValueError("Invalid batch ledger item status")
        if (
            not isinstance(attempts, int)
            or isinstance(attempts, bool)
            or attempts < 0
        ):
            raise ValueError("Invalid batch ledger attempts")
        for field in ("started_at", "finished_at", "error"):
            if value.get(field) is not None and not isinstance(value.get(field), str):
                raise ValueError("Invalid batch ledger item")
        return cls(
            source_type=source_type,
            source_id=source_id,
            slug=slug,
            eligible=value["eligible"],
            reason=value["reason"],
            status=value["status"],
            attempts=attempts,
            created_at=value["created_at"],
            started_at=value["started_at"],
            finished_at=value["finished_at"],
            updated_at=value["updated_at"],
            error=value["error"],
        )


class BatchWorkflowLock:
    """Fail-fast cross-platform lock beside one batch ledger."""

    _held_paths: set[str] = set()

    def __init__(self, ledger_path: Path) -> None:
        self.path = ledger_path.with_name(f"{ledger_path.name}.lock")
        self._file: BinaryIO | None = None
        self._identity = os.path.normcase(os.path.abspath(self.path))

    def __enter__(self) -> BatchWorkflowLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._identity in self._held_paths:
            raise RuntimeError("Documentary batch already running")
        lock_file = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if self.path.stat().st_size == 0:
                    lock_file.write(b"0")
                    lock_file.flush()
                lock_file.seek(0)
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise RuntimeError("Documentary batch already running") from exc
            else:
                import fcntl

                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise RuntimeError("Documentary batch already running") from exc
            self._held_paths.add(self._identity)
            self._file = lock_file
            return self
        except Exception:
            lock_file.close()
            raise

    def __exit__(self, *_: object) -> None:
        if self._file is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None
            self._held_paths.discard(self._identity)


class BatchLedger:
    """Versioned batch state persisted with atomic replacement."""

    def __init__(self, path: Path, items: dict[tuple[str, int], BatchItem]) -> None:
        self.path = path
        self.items = items

    @classmethod
    def load(cls, path: Path) -> BatchLedger:
        if not path.exists():
            return cls(path, {})
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid batch ledger JSON: {path}") from exc
        if not isinstance(value, dict) or value.get("version") != LEDGER_VERSION:
            raise ValueError("Unsupported batch ledger version")
        raw_items = value.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("Invalid batch ledger items")
        items: dict[tuple[str, int], BatchItem] = {}
        for raw_item in raw_items:
            item = BatchItem.from_payload(raw_item)
            if item.identity in items:
                raise ValueError("Duplicate batch ledger item identity")
            items[item.identity] = item
        return cls(path, items)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": LEDGER_VERSION,
            "items": [self.items[key].payload() for key in sorted(self.items)],
        }
        temporary = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
