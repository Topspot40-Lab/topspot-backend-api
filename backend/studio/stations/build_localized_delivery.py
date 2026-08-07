"""Canonical Stage 9 localized documentary delivery assembly."""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.studio.factory.production_contract import SUPPORTED_LANGUAGE_CODES
from backend.studio.factory.production_execution import ProductionExecution
from backend.studio.stations.build_storyboard import save_json_atomic

VISUAL_MASTER = "shared.visual_master"
VISUAL_RENDER = "visual_render"
DELIVERY_DURATION_TOLERANCE_SECONDS = 0.25
Builder = Callable[[Path, tuple[Path, Path, Path], Path], None]
MediaProbe = Callable[[Path], dict[str, Any]]
MediaValidator = Callable[[Path, tuple[Path, Path, Path]], dict[str, float]]


def station(language: str) -> str:
    return f"localized_delivery_{language}"


def video_artifact(language: str) -> str:
    return f"delivery.{language}.video"


def narration_artifact(language: str, segment: str) -> str:
    return f"delivery.{language}.narration.{segment}"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sidecar(execution: ProductionExecution, language: str) -> Path:
    return execution.factory_root / "delivery" / language / "documentary.inputs.json"


def ffprobe_media(path: Path) -> dict[str, Any]:
    """Return FFprobe's stream and container metadata for one local file."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("FFprobe did not return a media object")
    return payload


def _duration(metadata: dict[str, Any]) -> float:
    raw = metadata.get("format", {}).get("duration") if isinstance(metadata.get("format"), dict) else None
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Media duration is missing or invalid") from exc
    if value <= 0:
        raise RuntimeError("Media duration must be non-zero")
    return value


def _stream_duration(stream: dict[str, Any]) -> float:
    raw = stream.get("duration")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "Media stream duration is missing or invalid"
        ) from exc
    if value <= 0:
        raise RuntimeError("Media stream duration must be non-zero")
    return value


def _fps(stream: dict[str, Any]) -> float:
    raw = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
    try:
        numerator, denominator = str(raw).split("/", maxsplit=1)
        value = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError) as exc:
        raise RuntimeError("Video frame rate is missing or invalid") from exc
    return value


def validate_delivery_media(
    output: Path,
    narration: tuple[Path, Path, Path],
    *,
    probe: MediaProbe = ffprobe_media,
) -> dict[str, float]:
    """Require a playable 1080p/30fps MP4 synchronized to localized narration."""
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("Localized delivery is missing or empty")
    delivery = probe(output)
    streams = delivery.get("streams")
    if not isinstance(streams, list):
        raise RuntimeError("Localized delivery has no stream metadata")
    video = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"), None)
    if video is None:
        raise RuntimeError("Localized delivery has no video stream")
    if audio is None:
        raise RuntimeError("Localized delivery has no audio stream")
    if video.get("width") != 1920 or video.get("height") != 1080:
        raise RuntimeError("Localized delivery must be 1920x1080")
    fps = _fps(video)
    if abs(fps - 30.0) > 0.01:
        raise RuntimeError("Localized delivery must be 30 fps")
    duration = _duration(delivery)
    audio_duration = _stream_duration(audio)
    narration_duration = sum(
        _duration(probe(track))
        for track in narration
    )
    if (
        abs(audio_duration - narration_duration)
        > DELIVERY_DURATION_TOLERANCE_SECONDS
    ):
        raise RuntimeError(
            "Localized delivery duration is not synchronized with narration"
        )
    return {"duration_seconds": duration, "fps": fps}


def ffmpeg_delivery(master: Path, narration: tuple[Path, Path, Path], output: Path) -> None:
    """Narrow canonical FFmpeg adapter; legacy story-video CLI is untouched."""
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(master), *sum((['-i', str(path)] for path in narration), []), "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]", "-map", "0:v:0", "-map", "[a]", "-c:v", "libx264", "-r", "30", "-pix_fmt", "yuv420p", "-vf", "scale=1920:1080", "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"FFmpeg localized delivery failed: {result.stderr[-400:]}")


def _inputs(execution: ProductionExecution, language: str) -> tuple[Path, tuple[Path, Path, Path], dict[str, str]]:
    execution.require_verified_completed(station=VISUAL_RENDER, artifact_id=VISUAL_MASTER)
    master = execution.output_path(station=VISUAL_RENDER, artifact_id=VISUAL_MASTER)
    tracks = tuple(execution.output_path(station=f"narration_{language}", artifact_id=narration_artifact(language, part)) for part in ("intro", "story", "outro"))
    for part in ("intro", "story", "outro"):
        execution.require_verified_completed(station=f"narration_{language}", artifact_id=narration_artifact(language, part))
    return master, tracks, {"visual_master": digest(master), **{part: digest(path) for part, path in zip(("intro", "story", "outro"), tracks, strict=True)}}


def _recorded(path: Path) -> dict[str, str] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("input_sha256")
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def run_localized_deliveries(
    production: Any,
    execution: ProductionExecution,
    *,
    builder: Builder = ffmpeg_delivery,
    media_validator: MediaValidator = validate_delivery_media,
) -> bool:
    """Build all contract languages; each delivery resumes independently."""
    execution.resume()
    changed = False
    failures: list[str] = []
    for language in SUPPORTED_LANGUAGE_CODES:
        delivery_station = station(language)
        artifact = video_artifact(language)
        session = production.session
        session.start_station(delivery_station)
        claimed = False
        try:
            master, tracks, inputs = _inputs(execution, language)
            pending = artifact in execution.pending_artifacts(station=delivery_station)
            if not pending and _recorded(sidecar(execution, language)) == inputs:
                media_validator(execution.output_path(station=delivery_station, artifact_id=artifact), tracks)
                session.finish_station(delivery_station, success=True)
                continue
            if not pending:
                execution.requeue_artifact(station=delivery_station, artifact_id=artifact, reason="Localized delivery input digest changed or is missing")
            output = execution.start_artifact(station=delivery_station, artifact_id=artifact)
            claimed = True
            builder(master, tracks, output)
            media = media_validator(output, tracks)
            execution.complete_artifact(station=delivery_station, artifact_id=artifact)
            save_json_atomic(sidecar(execution, language), {"version": 1, "input_sha256": inputs})
        except Exception as exc:
            if claimed:
                try:
                    execution.fail_artifact(station=delivery_station, artifact_id=artifact, error_summary=f"{type(exc).__name__}: {exc}")
                except RuntimeError:
                    pass
            session.finish_station(delivery_station, success=False)
            failures.append(f"{language}: {type(exc).__name__}: {exc}")
            continue
        session.metric("resolution", "1920x1080", station=delivery_station)
        session.metric("fps", media["fps"], station=delivery_station)
        session.metric("duration_seconds", media["duration_seconds"], station=delivery_station)
        session.artifact(artifact, output, station=delivery_station)
        session.finish_station(delivery_station, success=True)
        execution.require_verified_completed(station=delivery_station, artifact_id=artifact)
        changed = True
    if failures:
        raise RuntimeError("Localized delivery failures: " + "; ".join(failures))
    return changed