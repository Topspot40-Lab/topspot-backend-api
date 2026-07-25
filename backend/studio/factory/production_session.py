from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ProductionSession:
    """
    Persistent operational record for one TopSpot Studio production.

    The session records station status, timing, warnings, errors,
    metrics, and generated artifacts under:

        work/<slug>/factory/session.json
    """

    def __init__(
        self,
        *,
        production_slug: str,
        work_root: Path,
    ) -> None:
        self.production_slug = production_slug
        self.factory_root = work_root / "factory"
        self.session_path = self.factory_root / "session.json"

        self.factory_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._station_started_monotonic: dict[str, float] = {}
        self.payload = self._load_or_create()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _load_or_create(self) -> dict[str, Any]:
        if self.session_path.exists():
            try:
                payload = json.loads(
                    self.session_path.read_text(
                        encoding="utf-8"
                    )
                )

                if isinstance(payload, dict):
                    return payload

            except json.JSONDecodeError:
                pass

        payload: dict[str, Any] = {
            "version": 1,
            "production": self.production_slug,
            "status": "idle",
            "started_at": None,
            "finished_at": None,
            "updated_at": self._now(),
            "stations": {},
            "warnings": [],
            "errors": [],
            "metrics": {},
            "artifacts": {},
        }

        self._write(payload)
        return payload

    def _write(
        self,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if payload is not None:
            self.payload = payload

        self.payload["updated_at"] = self._now()

        temporary = self.session_path.with_suffix(
            ".json.tmp"
        )

        temporary.write_text(
            json.dumps(
                self.payload,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary.replace(self.session_path)

    def start_production(self) -> None:
        if not self.payload.get("started_at"):
            self.payload["started_at"] = self._now()

        self.payload["finished_at"] = None
        self.payload["status"] = "running"
        self._write()

    def finish_production(
        self,
        *,
        success: bool,
    ) -> None:
        self.payload["finished_at"] = self._now()
        self.payload["status"] = (
            "complete"
            if success
            else "failed"
        )
        self._write()

    def start_station(
        self,
        station: str,
    ) -> None:
        self.start_production()

        stations = self.payload.setdefault(
            "stations",
            {},
        )

        existing = dict(
            stations.get(station, {})
        )

        existing.update(
            {
                "status": "running",
                "started_at": self._now(),
                "finished_at": None,
                "elapsed_seconds": None,
                "metrics": dict(
                    existing.get("metrics", {})
                ),
                "artifacts": dict(
                    existing.get("artifacts", {})
                ),
                "warnings": list(
                    existing.get("warnings", [])
                ),
                "errors": list(
                    existing.get("errors", [])
                ),
            }
        )

        stations[station] = existing
        self._station_started_monotonic[station] = (
            time.monotonic()
        )

        self._write()

    def finish_station(
        self,
        station: str,
        *,
        success: bool = True,
    ) -> None:
        stations = self.payload.setdefault(
            "stations",
            {},
        )

        record = dict(
            stations.get(station, {})
        )

        started = self._station_started_monotonic.pop(
            station,
            None,
        )

        elapsed = (
            round(time.monotonic() - started, 3)
            if started is not None
            else None
        )

        record.update(
            {
                "status": (
                    "complete"
                    if success
                    else "failed"
                ),
                "finished_at": self._now(),
                "elapsed_seconds": elapsed,
            }
        )

        stations[station] = record
        self._write()

    def metric(
        self,
        name: str,
        value: Any,
        *,
        station: str | None = None,
    ) -> None:
        if station is None:
            metrics = self.payload.setdefault(
                "metrics",
                {},
            )
        else:
            stations = self.payload.setdefault(
                "stations",
                {},
            )
            record = stations.setdefault(
                station,
                {
                    "status": "unknown",
                    "metrics": {},
                    "artifacts": {},
                    "warnings": [],
                    "errors": [],
                },
            )
            metrics = record.setdefault(
                "metrics",
                {},
            )

        metrics[name] = value
        self._write()

    def artifact(
        self,
        name: str,
        path: str | Path,
        *,
        station: str | None = None,
    ) -> None:
        value = str(path)

        if station is None:
            artifacts = self.payload.setdefault(
                "artifacts",
                {},
            )
        else:
            stations = self.payload.setdefault(
                "stations",
                {},
            )
            record = stations.setdefault(
                station,
                {
                    "status": "unknown",
                    "metrics": {},
                    "artifacts": {},
                    "warnings": [],
                    "errors": [],
                },
            )
            artifacts = record.setdefault(
                "artifacts",
                {},
            )

        artifacts[name] = value
        self._write()

    def warning(
        self,
        message: str,
        *,
        station: str | None = None,
    ) -> None:
        entry = {
            "time": self._now(),
            "message": message,
        }

        self.payload.setdefault(
            "warnings",
            [],
        ).append(entry)

        if station is not None:
            stations = self.payload.setdefault(
                "stations",
                {},
            )
            record = stations.setdefault(
                station,
                {
                    "status": "unknown",
                    "metrics": {},
                    "artifacts": {},
                    "warnings": [],
                    "errors": [],
                },
            )
            record.setdefault(
                "warnings",
                [],
            ).append(entry)

        self._write()

    def error(
        self,
        message: str,
        *,
        station: str | None = None,
    ) -> None:
        entry = {
            "time": self._now(),
            "message": message,
        }

        self.payload.setdefault(
            "errors",
            [],
        ).append(entry)

        if station is not None:
            stations = self.payload.setdefault(
                "stations",
                {},
            )
            record = stations.setdefault(
                station,
                {
                    "status": "unknown",
                    "metrics": {},
                    "artifacts": {},
                    "warnings": [],
                    "errors": [],
                },
            )
            record.setdefault(
                "errors",
                [],
            ).append(entry)

        self._write()
