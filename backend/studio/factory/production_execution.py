"""Mutable local execution state for a canonical documentary contract."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from backend.studio.factory.production_contract import (
    DocumentaryProductionContract,
    artifact_identity,
    canonical_artifact_path,
    require_safe_relative_path,
)

ArtifactStatus = Literal["pending", "running", "completed", "failed", "skipped"]
_VALID_STATUSES: Final[frozenset[str]] = frozenset(
    {"pending", "running", "completed", "failed", "skipped"}
)
_FACTORY_CONTROL_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {"execution.json", "session.json", "execution.lock", "workflow.lock"}
)


@dataclass(frozen=True, slots=True)
class ArtifactAssignment:
    artifact_id: str
    contract_path: str
    station: str


class ProductionWorkflowLock:
    """Fail-fast lock for one factory orchestration at a time."""

    _held_paths: set[str] = set()

    def __init__(self, work_root: Path) -> None:
        self.path = Path(work_root) / "factory" / "workflow.lock"
        self._file: Any | None = None
        self._identity = os.path.normcase(os.path.abspath(self.path))

    def __enter__(self) -> "ProductionWorkflowLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._identity in self._held_paths:
            raise RuntimeError("Create Documentary production already running")
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
                    raise RuntimeError("Create Documentary production already running") from exc
            else:
                import fcntl

                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise RuntimeError("Create Documentary production already running") from exc
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


def is_reserved_factory_control_path(path: str) -> bool:
    """Whether a work-root-relative path belongs to factory control state.

    Comparison uses the same canonical, case-insensitive Windows identity as
    contract artifacts. Temporary descendants are reserved with their control
    file, so callers cannot collide with an atomic ledger/session write.
    """
    identity = artifact_identity(path)
    for filename in _FACTORY_CONTROL_FILE_NAMES:
        control_identity = artifact_identity(f"factory/{filename}")
        if identity == control_identity or identity.startswith(control_identity + "."):
            return True
    return False


def documentary_artifact_assignments(
    contract: DocumentaryProductionContract,
) -> tuple[ArtifactAssignment, ...]:
    """Return the fixed Stage 3 ownership map for a documentary contract."""
    shared = contract.shared_assets
    assignments: list[ArtifactAssignment] = [
        ArtifactAssignment("shared.storyboard_and_scene_plan", shared.storyboard_and_scene_plan, "visual_planning"),
        ArtifactAssignment("shared.approved_visuals", shared.approved_visuals, "visual_research"),
        ArtifactAssignment("shared.visual_master", shared.visual_master, "visual_render"),
        ArtifactAssignment("shared.opening_video", shared.opening_video, "visual_render"),
        ArtifactAssignment("shared.hook_visual", shared.hook_visual, "visual_render"),
        ArtifactAssignment("shared.provenance_report", shared.provenance_report, "visual_quality"),
        ArtifactAssignment("shared.quality_report", shared.quality_report, "visual_quality"),
    ]
    for edition in contract.editions:
        code = edition.language_code
        narration = edition.delivery.narration
        assignments.extend((
            ArtifactAssignment(f"delivery.{code}.video", edition.delivery.video_mp4, f"localized_delivery_{code}"),
            ArtifactAssignment(f"delivery.{code}.narration.hook", narration.hook, f"narration_{code}"),
            ArtifactAssignment(f"delivery.{code}.narration.intro", narration.intro, f"narration_{code}"),
            ArtifactAssignment(f"delivery.{code}.narration.story", narration.story, f"narration_{code}"),
            ArtifactAssignment(f"delivery.{code}.narration.outro", narration.outro, f"narration_{code}"),
        ))
        for name, path in (
            ("complete_audio_master", edition.publishing.complete_audio_master),
            ("captions", edition.publishing.captions),
            ("thumbnail", edition.publishing.thumbnail),
            ("youtube_metadata", edition.publishing.youtube_metadata),
            ("youtube_chapters", edition.publishing.youtube_chapters),
        ):
            assignments.append(
                ArtifactAssignment(f"publishing.{code}.{name}", path, f"youtube_prepare_{code}")
            )
    return tuple(assignments)


class ProductionExecution:
    """Persistent local artifact state, with ownership and resume checks.

    Compatibility mappings are explicit: artifact ID to a safe path relative
    to ``work_root``. Without one, outputs stay under ``factory``.
    """

    def __init__(
        self,
        *,
        contract: DocumentaryProductionContract,
        work_root: Path,
        compatibility_mappings: Mapping[str, str] | None = None,
    ) -> None:
        if contract.youtube_multilingual.publishing_enabled:
            raise ValueError("Stage 3 execution does not permit publishing")
        self.contract = contract
        self.work_root = Path(work_root)
        self.factory_root = self.work_root / "factory"
        self.execution_path = self.factory_root / "execution.json"
        self.lock_path = self.factory_root / "execution.lock"
        self.assignments = documentary_artifact_assignments(contract)
        self._assignments = {item.artifact_id: item for item in self.assignments}
        mappings = dict(compatibility_mappings or {})
        unknown = sorted(set(mappings) - set(self._assignments))
        if unknown:
            raise ValueError("Unknown compatibility mapping artifact IDs: " + ", ".join(unknown))
        self._output_paths = {
            artifact_id: self._mapped_output_path(artifact_id, mappings)
            for artifact_id in self._assignments
        }
        self._validate_output_paths()
        self.factory_root.mkdir(parents=True, exist_ok=True)
        with self._locked():
            self.payload = self._load_or_create_locked()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _mapped_output_path(self, artifact_id: str, mappings: Mapping[str, str]) -> Path:
        if artifact_id in mappings:
            relative_path = mappings[artifact_id]
            require_safe_relative_path(relative_path, field=f"compatibility mapping for {artifact_id}")
            normalized = canonical_artifact_path(relative_path)
            return self.work_root / normalized
        return self.factory_root / self._assignments[artifact_id].contract_path

    def _validate_output_paths(self) -> None:
        """Reject reserved or colliding paths after all resolution is complete."""
        paths_by_identity: dict[str, str] = {}
        for artifact_id, path in self._output_paths.items():
            relative_path = path.relative_to(self.work_root).as_posix()
            if is_reserved_factory_control_path(relative_path):
                raise ValueError(
                    "Artifact output targets reserved factory control path: "
                    + relative_path
                )
            identity = artifact_identity(relative_path)
            previous = paths_by_identity.get(identity)
            if previous is not None:
                raise ValueError(
                    "Artifact output paths must be unique: "
                    f"{previous} and {artifact_id}"
                )
            paths_by_identity[identity] = artifact_id
    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Acquire a blocking inter-process lock on Windows or POSIX."""
        self.factory_root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock_file:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                if lock_file.tell() == 0 and self.lock_path.stat().st_size == 0:
                    lock_file.write(b"0")
                    lock_file.flush()
                while True:
                    try:
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.01)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _record_template(self, assignment: ArtifactAssignment) -> dict[str, Any]:
        return {
            "artifact_id": assignment.artifact_id,
            "contract_path": assignment.contract_path,
            "station": assignment.station,
            "output_path": self._output_paths[assignment.artifact_id].relative_to(self.work_root).as_posix(),
            "status": "pending", "attempts": 0, "started_at": None,
            "finished_at": None, "updated_at": self._now(),
            "error_summary": None, "skip_reason": None, "verification": None,
        }

    def _load_or_create_locked(self) -> dict[str, Any]:
        if self.execution_path.exists():
            try:
                payload = json.loads(self.execution_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid execution JSON: {self.execution_path}") from exc
            self._validate_payload(payload)
            missing = [item for item in self.assignments if item.artifact_id not in payload["artifacts"]]
            if missing:
                for assignment in missing:
                    payload["artifacts"][assignment.artifact_id] = self._record_template(assignment)
                self._write_locked(payload)
            return payload
        payload: dict[str, Any] = {
            "version": 1, "production": self.contract.slug,
            "artifacts": {item.artifact_id: self._record_template(item) for item in self.assignments},
        }
        self._write_locked(payload)
        return payload

    def _reload_locked(self) -> None:
        self.payload = self._load_or_create_locked()

    def _validate_payload(self, payload: Any) -> None:
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Unsupported execution ledger")
        if payload.get("production") != self.contract.slug:
            raise ValueError("Execution ledger production does not match contract")
        records = payload.get("artifacts")
        if not isinstance(records, dict):
            raise ValueError("Execution ledger artifacts do not match contract")
        unknown = set(records) - set(self._assignments)
        if unknown:
            raise ValueError("Execution ledger artifacts do not match contract")
        for artifact_id, record in records.items():
            assignment = self._assignments[artifact_id]
            expected = self._output_paths[artifact_id].relative_to(self.work_root).as_posix()
            if not isinstance(record, dict):
                raise ValueError(f"Invalid execution record: {artifact_id}")
            if (record.get("artifact_id") != artifact_id or record.get("contract_path") != assignment.contract_path
                    or record.get("station") != assignment.station or record.get("status") not in _VALID_STATUSES):
                raise ValueError(f"Execution record does not match contract: {artifact_id}")
            if record.get("output_path") != expected:
                raise ValueError(f"Execution output path requires the supplied compatibility mapping: {artifact_id}")

    def _write_locked(self, payload: dict[str, Any] | None = None) -> None:
        if payload is not None:
            self.payload = payload
        temporary = self.execution_path.with_name(
            f"{self.execution_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        temporary.write_text(json.dumps(self.payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.execution_path)

    def _assignment_for(self, artifact_id: str, station: str) -> ArtifactAssignment:
        try:
            assignment = self._assignments[artifact_id]
        except KeyError as exc:
            raise KeyError(f"Unknown contract artifact: {artifact_id}") from exc
        if assignment.station != station:
            raise PermissionError(f"Station {station!r} cannot write {artifact_id!r}; assigned to {assignment.station!r}")
        return assignment

    def _record(self, artifact_id: str) -> dict[str, Any]:
        return self.payload["artifacts"][artifact_id]

    def record(self, artifact_id: str) -> dict[str, Any]:
        if artifact_id not in self._assignments:
            raise KeyError(f"Unknown contract artifact: {artifact_id}")
        with self._locked():
            self._reload_locked()
            return dict(self._record(artifact_id))

    def output_path(self, *, station: str, artifact_id: str) -> Path:
        self._assignment_for(artifact_id, station)
        return self._output_paths[artifact_id]

    def _verify(self, artifact_id: str) -> dict[str, Any]:
        path = self._output_paths[artifact_id]
        verification: dict[str, Any] = {"verified_at": self._now(), "exists": path.exists(), "is_file": path.is_file(), "size_bytes": None, "sha256": None, "valid": False}
        if not path.is_file():
            return verification
        size_bytes = path.stat().st_size
        verification["size_bytes"] = size_bytes
        if size_bytes <= 0:
            return verification
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        verification.update({"sha256": digest.hexdigest(), "valid": True})
        return verification

    @staticmethod
    def _matches_recorded_verification(recorded: Any, current: dict[str, Any]) -> bool:
        """Require a completed output to remain the output that was verified."""
        return (
            current["valid"] is True
            and isinstance(recorded, dict)
            and recorded.get("valid") is True
            and recorded.get("size_bytes") == current["size_bytes"]
            and recorded.get("sha256") == current["sha256"]
        )

    def require_verified_completed(self, *, station: str, artifact_id: str) -> None:
        """Fail unless an artifact is completed and its recorded output remains valid."""
        self._assignment_for(artifact_id, station)
        with self._locked():
            self._reload_locked()
            record = self._record(artifact_id)
            current = self._verify(artifact_id)
            if record["status"] == "completed" and self._matches_recorded_verification(
                record.get("verification"), current
            ):
                record["verification"] = current
                record["updated_at"] = self._now()
                self._write_locked()
                return
            record["verification"] = current
            if record["status"] == "completed":
                record.update({
                    "status": "pending",
                    "finished_at": None,
                    "updated_at": self._now(),
                    "error_summary": "Output verification failed during required-output check",
                })
                self._write_locked()
            raise RuntimeError(f"Required artifact is not verified and completed: {artifact_id}")

    def start_artifact(self, *, station: str, artifact_id: str) -> Path:
        self._assignment_for(artifact_id, station)
        with self._locked():
            self._reload_locked()
            record = self._record(artifact_id)
            if record["status"] == "completed":
                recorded_verification = record.get("verification")
                verification = self._verify(artifact_id)
                record["verification"] = verification
                if self._matches_recorded_verification(recorded_verification, verification):
                    self._write_locked()
                    raise RuntimeError(f"Artifact is already completed: {artifact_id}")
                record["status"] = "pending"
            if record["status"] == "running":
                raise RuntimeError(f"Artifact is already running: {artifact_id}")
            if record["status"] == "skipped":
                raise RuntimeError(f"Artifact is skipped: {artifact_id}")
            record.update({"status": "running", "attempts": int(record["attempts"]) + 1,
                           "started_at": self._now(), "finished_at": None, "updated_at": self._now(),
                           "error_summary": None, "skip_reason": None, "verification": None})
            self._write_locked()
        return self._output_paths[artifact_id]

    def complete_artifact(self, *, station: str, artifact_id: str) -> None:
        self._assignment_for(artifact_id, station)
        with self._locked():
            self._reload_locked()
            record = self._record(artifact_id)
            if record["status"] != "running":
                raise RuntimeError(f"Artifact is not running: {artifact_id}")
            verification = self._verify(artifact_id)
            record.update({"verification": verification, "finished_at": self._now(), "updated_at": self._now()})
            if not verification["valid"]:
                record.update({"status": "failed", "error_summary": "Output verification failed"})
                self._write_locked()
                raise ValueError(f"Output verification failed: {artifact_id}")
            record.update({"status": "completed", "error_summary": None})
            self._write_locked()

    def fail_artifact(self, *, station: str, artifact_id: str, error_summary: str) -> None:
        self._assignment_for(artifact_id, station)
        if not error_summary.strip():
            raise ValueError("error_summary must not be empty")
        with self._locked():
            self._reload_locked()
            record = self._record(artifact_id)
            if record["status"] != "running":
                raise RuntimeError(f"Artifact is not running: {artifact_id}")
            record.update({"status": "failed", "finished_at": self._now(), "updated_at": self._now(), "error_summary": error_summary.strip()})
            self._write_locked()

    def requeue_artifact(self, *, station: str, artifact_id: str, reason: str) -> None:
        """Return completed work to pending when its verified input changed."""
        self._assignment_for(artifact_id, station)
        if not reason.strip():
            raise ValueError("requeue reason must not be empty")
        with self._locked():
            self._reload_locked()
            record = self._record(artifact_id)
            if record["status"] == "running":
                raise RuntimeError(f"Cannot requeue a running artifact: {artifact_id}")
            if record["status"] == "skipped":
                raise RuntimeError(f"Cannot requeue a skipped artifact: {artifact_id}")
            record.update({
                "status": "pending",
                "finished_at": None,
                "updated_at": self._now(),
                "error_summary": reason.strip(),
                "skip_reason": None,
                "verification": None,
            })
            self._write_locked()

    def skip_artifact(self, *, station: str, artifact_id: str, reason: str) -> None:
        self._assignment_for(artifact_id, station)
        if not reason.strip():
            raise ValueError("skip reason must not be empty")
        with self._locked():
            self._reload_locked()
            record = self._record(artifact_id)
            if record["status"] == "running":
                raise RuntimeError(f"Cannot skip a running artifact: {artifact_id}")
            record.update({"status": "skipped", "finished_at": self._now(), "updated_at": self._now(), "skip_reason": reason.strip(), "error_summary": None})
            self._write_locked()

    def resume(self) -> tuple[str, ...]:
        """Requeue interrupted or invalid work and retain verified completions."""
        with self._locked():
            self._reload_locked()
            pending: list[str] = []
            changed = False
            for artifact_id in self._assignments:
                record = self._record(artifact_id)
                if record["status"] == "running":
                    record.update({"status": "pending", "finished_at": None, "updated_at": self._now(), "error_summary": "Interrupted before completion"})
                    pending.append(artifact_id)
                    changed = True
                elif record["status"] == "completed":
                    recorded_verification = record.get("verification")
                    verification = self._verify(artifact_id)
                    record["verification"] = verification
                    if self._matches_recorded_verification(recorded_verification, verification):
                        changed = True
                        continue
                    record.update({"status": "pending", "finished_at": None, "updated_at": self._now(), "error_summary": "Output verification failed during resume"})
                    pending.append(artifact_id)
                    changed = True
                elif record["status"] in {"pending", "failed"}:
                    pending.append(artifact_id)
            if changed:
                self._write_locked()
            return tuple(pending)

    def pending_artifacts(self, *, station: str) -> tuple[str, ...]:
        with self._locked():
            self._reload_locked()
            return tuple(artifact_id for artifact_id, assignment in self._assignments.items()
                         if assignment.station == station and self._record(artifact_id)["status"] in {"pending", "failed"})
