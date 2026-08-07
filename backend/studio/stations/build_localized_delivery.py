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
from backend.studio.studio_config import ASSETS_DIR
from backend.studio.render.build_story_video import (
    BED_TRACK_BUCKET, DEFAULT_BED_KEY, audio_mix_settings, ensure_bed_track,
)

VISUAL_MASTER = "shared.visual_master"
OPENING_VIDEO = "shared.opening_video"
VISUAL_RENDER = "visual_render"
DELIVERY_DURATION_TOLERANCE_SECONDS = 0.25
Builder = Callable[[Path, Path, Path, Path, Path, tuple[Path, Path, Path, Path], Path], None]
BedEnsurer = Callable[..., None]
MediaProbe = Callable[[Path], dict[str, Any]]
MediaValidator = Callable[[Path, tuple[Path, Path, Path, Path]], dict[str, float]]


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
    raw = stream.get("r_frame_rate") or stream.get("avg_frame_rate")
    try:
        numerator, denominator = str(raw).split("/", maxsplit=1)
        value = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError) as exc:
        raise RuntimeError("Video frame rate is missing or invalid") from exc
    return value


def validate_delivery_media(
    output: Path,
    narration: tuple[Path, Path, Path, Path],
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
    video_duration = _stream_duration(video)
    if (
        abs(audio_duration - video_duration)
        > DELIVERY_DURATION_TOLERANCE_SECONDS
    ):
        raise RuntimeError(
            "Localized delivery video and audio streams are not synchronized"
        )
    return {"duration_seconds": duration, "fps": fps}


def ffmpeg_delivery(opening: Path, master: Path, hook_visual: Path, brand: Path, bed: Path, narration: tuple[Path, Path, Path, Path], output: Path) -> None:
    """Delegate canonical delivery assembly to the established full-program renderer."""
    from backend.studio.render.build_story_video import build_story_video

    build_story_video(
        opening=opening,
        image_sequence=master,
        hook_image=hook_visual,
        brand_image=brand,
        hook_audio=narration[0],
        intro_audio=narration[1],
        story_audio=narration[2],
        outro_audio=narration[3],
        bed_audio=bed,
        output=output,
        bed_volume_db=-26.0,
        duck_threshold=0.03,
        duck_ratio=8.0,
        duck_attack_ms=25,
        duck_release_ms=500,
    )

def resolve_bed_track(production: Any, execution: ProductionExecution, *, ensurer: BedEnsurer | None = None) -> Path:
    settings = audio_mix_settings(getattr(production, "manifest", {}))
    bed_key = str(settings.get("bed_key") or DEFAULT_BED_KEY)
    destination = execution.factory_root / "cache" / "audio" / Path(bed_key).name
    (ensurer or ensure_bed_track)(bucket=BED_TRACK_BUCKET, bed_key=bed_key, destination=destination)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("Configured bed track is missing or empty after retrieval")
    return destination

def _inputs(execution: ProductionExecution, language: str, bed: Path) -> tuple[Path, Path, Path, Path, Path, tuple[Path, Path, Path, Path], dict[str, str]]:
    execution.require_verified_completed(station=VISUAL_RENDER, artifact_id=VISUAL_MASTER)
    execution.require_verified_completed(station=VISUAL_RENDER, artifact_id=OPENING_VIDEO)
    execution.require_verified_completed(station=VISUAL_RENDER, artifact_id="shared.hook_visual")
    master = execution.output_path(station=VISUAL_RENDER, artifact_id=VISUAL_MASTER)
    opening = execution.output_path(station=VISUAL_RENDER, artifact_id=OPENING_VIDEO)
    hook_visual = execution.output_path(station=VISUAL_RENDER, artifact_id="shared.hook_visual")
    brand = ASSETS_DIR / "old_dog_new_tracks.png"
    if not brand.is_file():
        raise FileNotFoundError(f"Brand image is missing: {brand}")
    tracks = tuple(execution.output_path(station=f"narration_{language}", artifact_id=narration_artifact(language, part)) for part in ("hook", "intro", "story", "outro"))
    for part in ("hook", "intro", "story", "outro"):
        execution.require_verified_completed(station=f"narration_{language}", artifact_id=narration_artifact(language, part))
    inputs = {"opening_video": digest(opening), "visual_master": digest(master), "hook_visual": digest(hook_visual), "old_dog_new_tracks": digest(brand), "bed_track": digest(bed), **{part: digest(path) for part, path in zip(("hook", "intro", "story", "outro"), tracks, strict=True)}}
    return opening, master, hook_visual, brand, bed, tracks, inputs
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
    bed_ensurer: BedEnsurer | None = None,
) -> bool:
    """Build all contract languages; each delivery resumes independently."""
    execution.resume()
    changed = False
    failures: list[str] = []
    bed = resolve_bed_track(production, execution, ensurer=bed_ensurer)
    for language in SUPPORTED_LANGUAGE_CODES:
        delivery_station = station(language)
        artifact = video_artifact(language)
        session = production.session
        session.start_station(delivery_station)
        claimed = False
        try:
            opening, master, hook_visual, brand, bed, tracks, inputs = _inputs(execution, language, bed)
            pending = artifact in execution.pending_artifacts(station=delivery_station)
            if not pending and _recorded(sidecar(execution, language)) == inputs:
                media_validator(execution.output_path(station=delivery_station, artifact_id=artifact), tracks)
                session.finish_station(delivery_station, success=True)
                continue
            if not pending:
                execution.requeue_artifact(station=delivery_station, artifact_id=artifact, reason="Localized delivery input digest changed or is missing")
            output = execution.start_artifact(station=delivery_station, artifact_id=artifact)
            claimed = True
            builder(opening, master, hook_visual, brand, bed, tracks, output)
            media = media_validator(output, tracks)
            execution.complete_artifact(station=delivery_station, artifact_id=artifact)
            save_json_atomic(sidecar(execution, language), {"version": 2, "input_sha256": inputs})
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