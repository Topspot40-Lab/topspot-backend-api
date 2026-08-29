"""ElevenLabs forced alignment and strict, readable WebVTT construction."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

FORCED_ALIGNMENT_URL = "https://api.elevenlabs.io/v1/forced-alignment"
HIGH_WORD_LOSS = 0.5
MAX_CUE_SECONDS = 4.5
MAX_CUE_WORDS = 7
MAX_LINE_CHARS = 42


class AlignmentError(RuntimeError):
    """An alignment cannot safely be used for publishing captions."""


@dataclass(frozen=True)
class AlignedWord:
    text: str
    start: float
    end: float
    loss: float | None


AlignmentRequester = Callable[..., Any]
logger = logging.getLogger(__name__)


def clean_transcript(text: str) -> str:
    value = " ".join(text.split())
    value = re.sub(
        r"^(?:\*\*)?Hook\s*\([^)]*\)\s*:\s*(?:\*\*)?",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"(?<!\w)[*_]{1,2}|[*_]{1,2}(?!\w)", "", value).strip()
    if not value:
        raise AlignmentError("Caption transcript is empty")
    return value


def aligned_words(
    *,
    audio: Path,
    transcript: str,
    cache_dir: Path,
    audio_duration: float,
    requester: AlignmentRequester = requests.post,
) -> list[AlignedWord]:
    """Return a cached or newly-created, validated forced alignment.

    The cache deliberately contains only response metadata, never credentials.
    """
    if not audio.is_file() or audio.stat().st_size == 0:
        raise FileNotFoundError(f"Narration audio is missing or empty: {audio}")
    transcript = clean_transcript(transcript)
    key = _cache_key(audio, transcript)
    path = cache_dir / f"{key}.json"
    quarantine_path = cache_dir / f"{key}.quarantine.json"
    if path.is_file():
        try:
            return _parse_and_validate(
                json.loads(path.read_text(encoding="utf-8")),
                transcript=transcript,
                audio_duration=audio_duration,
            )
        except (OSError, json.JSONDecodeError, AlignmentError) as exc:
            raise AlignmentError(f"Cached alignment is invalid: {path}") from exc

    if quarantine_path.is_file():
        try:
            payload = json.loads(quarantine_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AlignmentError(f"Quarantined alignment is invalid: {quarantine_path}") from exc
        words = _parse_and_validate(payload, transcript=transcript, audio_duration=audio_duration)
        _write_cache(path, payload)
        return words

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise AlignmentError("ELEVENLABS_API_KEY is required when no valid alignment cache exists")
    try:
        with audio.open("rb") as handle:
            response = requester(
                FORCED_ALIGNMENT_URL,
                headers={"xi-api-key": api_key},
                files={"file": (audio.name, handle, "audio/mpeg")},
                data={"text": transcript},
                timeout=(10, 300),
            )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise AlignmentError("ElevenLabs forced alignment request failed") from exc
    except (TypeError, ValueError) as exc:
        raise AlignmentError("ElevenLabs forced alignment returned invalid JSON") from exc
    _write_cache(quarantine_path, payload)
    words = _parse_and_validate(payload, transcript=transcript, audio_duration=audio_duration)
    _write_cache(path, payload)
    return words


def _write_cache(path: Path, payload: Any) -> None:
    """Atomically store a response without exposing it in diagnostics."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def vtt_cues(words: list[AlignedWord], *, offset: float) -> list[tuple[float, float, str]]:
    if offset < 0:
        raise AlignmentError("Caption timeline offset cannot be negative")
    if not words:
        raise AlignmentError("Alignment has no words")
    cues: list[tuple[float, float, str]] = []
    group: list[AlignedWord] = []
    for word in words:
        candidate = [*group, word]
        text = " ".join(item.text for item in candidate)
        duration = candidate[-1].end - candidate[0].start
        if group and (len(candidate) > MAX_CUE_WORDS or len(text) > MAX_LINE_CHARS * 2 or duration > MAX_CUE_SECONDS):
            cues.append(_cue(group, offset))
            group = [word]
        else:
            group = candidate
        if re.search(r"[.!?…]$", word.text):
            cues.append(_cue(group, offset))
            group = []
    if group:
        cues.append(_cue(group, offset))
    _validate_cue_order(cues)
    return cues


def format_vtt(cues: list[tuple[float, float, str]]) -> str:
    _validate_cue_order(cues)
    lines = ["WEBVTT", ""]
    for start, end, text in cues:
        lines.extend((f"{vtt_time(start)} --> {vtt_time(end)}", text, ""))
    return "\n".join(lines)


def vtt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _cache_key(audio: Path, transcript: str) -> str:
    digest = hashlib.sha256()
    digest.update(audio.read_bytes())
    digest.update(b"\0")
    digest.update(transcript.encode("utf-8"))
    digest.update(b"\0forced-alignment-v1")
    return digest.hexdigest()


def _parse_and_validate(payload: Any, *, transcript: str, audio_duration: float) -> list[AlignedWord]:
    if not isinstance(payload, dict) or not isinstance(payload.get("words"), list):
        raise AlignmentError("Alignment response has no word timings")
    if not math.isfinite(audio_duration) or audio_duration <= 0:
        raise AlignmentError("Narration audio duration is invalid")
    words: list[AlignedWord] = []
    previous_end = 0.0
    previous_start = -1.0
    for index, item in enumerate(payload["words"]):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise AlignmentError("Alignment response contains an invalid word")
        text = item["text"].strip()
        # ElevenLabs includes whitespace-only entries between spoken words in
        # some otherwise valid responses.  They are separators, not words, so
        # deliberately exclude them from every spoken-word validation below.
        if not text:
            continue
        start = _number(item.get("start"), "word start", allow_negative=True)
        end = _number(item.get("end"), "word end", allow_negative=True)
        loss = _optional_number(item.get("loss"))
        if start < 0:
            raise AlignmentError(f"Alignment word {index} has a negative start")
        if end <= start:
            raise AlignmentError(f"Alignment word {index} has end <= start")
        if start < previous_start:
            raise AlignmentError(f"Alignment word {index} is non-monotonic")
        if start < previous_end:
            raise AlignmentError(
                f"Alignment word {index} overlaps the previous word by {previous_end - start:.3f} seconds"
            )
        if end > audio_duration:
            raise AlignmentError("Alignment timing exceeds narration audio duration")
        words.append(AlignedWord(text, start, end, loss))
        previous_end = end
        previous_start = start
    if not words:
        raise AlignmentError("Alignment response has no spoken words after separator filtering")
    if _normalized_coverage(" ".join(word.text for word in words)) != _normalized_coverage(transcript):
        raise AlignmentError("Alignment words do not exactly cover the supplied transcript")
    _log_quality_diagnostics(payload.get("loss"), words)
    return words


def _log_quality_diagnostics(overall_loss: Any, words: list[AlignedWord]) -> None:
    """Record numeric-only ElevenLabs quality observations; never reject on them."""
    measured = [word.loss for word in words if word.loss is not None]
    high_run = 0
    longest_high_run = 0
    for loss in measured:
        if loss > HIGH_WORD_LOSS:
            high_run += 1
            longest_high_run = max(longest_high_run, high_run)
        else:
            high_run = 0
    high_count = sum(loss > HIGH_WORD_LOSS for loss in measured)
    logger.warning(
        "Caption alignment quality diagnostics: overall_loss=%.6g max_word_loss=%.6g "
        "high_loss_percentage=%.2f longest_high_loss_run=%d measured_word_losses=%d",
        _numeric_diagnostic(overall_loss),
        max(measured) if measured else -1.0,
        (high_count * 100 / len(measured)) if measured else 0.0,
        longest_high_run,
        len(measured),
    )


def _number(value: Any, field: str, *, allow_negative: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AlignmentError(f"Alignment {field} is missing or invalid") from exc
    if not math.isfinite(number) or (number < 0 and not allow_negative):
        raise AlignmentError(f"Alignment {field} is missing or invalid")
    return number


def _optional_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _numeric_diagnostic(value: Any) -> float:
    number = _optional_number(value)
    return -1.0 if number is None else number


def _normalized_coverage(text: str) -> str:
    """Compare exact spoken text while normalizing only Unicode and spacing."""
    return " ".join(unicodedata.normalize("NFC", text).split()).casefold()


def _cue(words: list[AlignedWord], offset: float) -> tuple[float, float, str]:
    text = _wrap_words([word.text for word in words])
    return offset + words[0].start, offset + words[-1].end, text


def _wrap_words(words: list[str]) -> str:
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = word if not line else f"{line} {word}"
        if line and len(candidate) > MAX_LINE_CHARS and len(lines) < 1:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return "\n".join(lines)


def _validate_cue_order(cues: list[tuple[float, float, str]]) -> None:
    previous_end_ms = -1
    for start, end, text in cues:
        if (
            not isinstance(text, str)
            or not text.strip()
            or isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end <= start
        ):
            raise AlignmentError("Caption cues are empty, invalid, or out of order")
        start_ms = round(start * 1000)
        end_ms = round(end * 1000)
        if end_ms <= start_ms or start_ms < previous_end_ms:
            raise AlignmentError("Caption cues are empty, invalid, or out of order")
        previous_end_ms = end_ms
