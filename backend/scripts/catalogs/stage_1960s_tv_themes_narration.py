"""Authorized staging-only narration runner for catalog 64.

It has no database imports and never writes canonical keys.  Promotion is a
separate, later authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import tempfile
import unicodedata
from urllib.parse import quote
from collections import Counter
from io import BytesIO
from pathlib import Path

from mutagen.mp3 import MP3
import requests

ROOT = Path(__file__).parent / "review_manifests"
PLAN_PATH = ROOT / "1960s-tv-themes.production-plan.v1.json"
TEXT_PATH = ROOT / "1960s-tv-themes.narration-drafts.v1.json"
DEFAULT_MANIFEST = ROOT / "1960s-tv-themes.staged-media.v2.json"
CATALOG_ID = 64
LANGS = ("en", "es-MX", "pt-BR")
NUMBER_WORDS = {
    "en": ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone twentytwo twentythree twentyfour twentyfive twentysix twentyseven twentyeight twentynine thirty thirtyone thirtytwo thirtythree thirtyfour thirtyfive thirtysix thirtyseven thirtyeight").split(),
    "es-MX": ("uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciseis diecisiete dieciocho diecinueve veinte veintiuno veintidos veintitres veinticuatro veinticinco veintiseis veintisiete veintiocho veintinueve treinta treinta y uno treinta y dos treinta y tres treinta y cuatro treinta y cinco treinta y seis treinta y siete treinta y ocho").split(),
    "pt-BR": ("um dois tres quatro cinco seis sete oito nove dez onze doze treze catorze quinze dezesseis dezessete dezoito dezenove vinte vinte e um vinte e dois vinte e tres vinte e quatro vinte e cinco vinte e seis vinte e sete vinte e oito vinte e nove trinta trinta e um trinta e dois trinta e tres trinta e quatro trinta e cinco trinta e seis trinta e sete trinta e oito").split(),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tokens(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return {token for token in re.findall(r"[a-z0-9]+", text) if len(token) > 2}


def _bucket(language: str) -> str:
    from backend.config import BUCKETS
    return BUCKETS["es" if language == "es-MX" else language]["intro"]


def _key(prefix: str, row: dict, spotify_id: str) -> str:
    return f"{prefix}/{row['language']}/{row['kind']}/{row['rank']:02}-{spotify_id}.mp3"


def _duration(data: bytes) -> float:
    duration = float(MP3(BytesIO(data)).info.length)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("nonpositive_or_undecodable_duration")
    return duration


def _download_staged(bucket: str, key: str, *, attempts: int = 3) -> bytes:
    """Cache-disabled public-object read with bounded timeout and retries."""
    from backend.config import SUPABASE_URL
    if not SUPABASE_URL:
        raise RuntimeError("Supabase URL unavailable for staged validation")
    url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{quote(bucket, safe='')}/{quote(key, safe='/')}"
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, params={"v": _sha(f"{key}:{attempt}".encode())[:12]}, headers={"Cache-Control": "no-cache"}, timeout=(10, 30))
            response.raise_for_status()
            if not response.content:
                raise RuntimeError("empty staged object")
            return response.content
        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
    raise RuntimeError(f"staged download failed after {attempts} bounded attempts: {last_error}")


def _load() -> tuple[dict, list[dict], dict[int, dict]]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    rows = json.loads(TEXT_PATH.read_text(encoding="utf-8"))["records"]
    entries = {entry["proposed_rank"]: entry for entry in plan["approved_entries"]}
    if plan["catalog_id"] != CATALOG_ID or tuple(sorted(entries)) != tuple(range(1, 39)):
        raise ValueError("final contiguous catalog-64 plan required")
    counts = Counter((row["language"], row["kind"]) for row in rows)
    expected = {("en", "intro"): 38, ("es-MX", "intro"): 38, ("pt-BR", "intro"): 38,
                ("en", "short_detail"): 15, ("es-MX", "short_detail"): 15, ("pt-BR", "short_detail"): 15,
                ("en", "long_detail"): 15, ("es-MX", "long_detail"): 15, ("pt-BR", "long_detail"): 18}
    if len(rows) != 207 or counts != expected:
        raise ValueError("exact 207-record narration bundle required")
    for row in rows:
        if _sha(row["text"].encode("utf-8")) != row["text_sha256"]:
            raise ValueError(f"draft hash mismatch for {row['rank']}/{row['language']}/{row['kind']}")
        if row["kind"] == "intro" and row.get("canonical_key") != f"intro/1960s_tv_themes_{row['rank']:02}.mp3":
            raise ValueError("intro canonical-key plan mismatch")
    return plan, rows, entries


def preflight(*, resume: bool = False) -> dict:
    plan, rows, entries = _load()
    from backend.config import ELEVENLABS_ENABLE, ELEVENLABS_API_KEY, TTS_PROFILES
    from backend.services.supabase_storage import list_folder_keys
    try:
        from faster_whisper import WhisperModel
        WhisperModel("tiny", device="cpu", compute_type="int8")
    except Exception as exc:
        raise RuntimeError("local ASR model unavailable; refusing paid generation") from exc
    if not ELEVENLABS_ENABLE or not ELEVENLABS_API_KEY:
        raise RuntimeError("ElevenLabs is not configured/enabled")
    for language in LANGS:
        for kind in ("intro", "detail"):
            if not TTS_PROFILES["es" if language == "es-MX" else language][kind].get("voice_id"):
                raise RuntimeError(f"missing established voice for {language}/{kind}")
    prefix = plan["media_execution"]["staging_prefix"]
    occupied = {bucket: sorted(list_folder_keys(bucket, prefix)) for bucket in {_bucket(language) for language in LANGS}}
    if any(occupied.values()) and not resume:
        raise RuntimeError("versioned staging prefix is not empty")
    return {"plan": plan, "rows": rows, "entries": entries, "prefix": prefix, "occupied": occupied}


def _transcribe(model, data: bytes) -> tuple[str, str]:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        path = Path(tmp.name); path.write_bytes(data)
    try:
        segments, info = model.transcribe(str(path), beam_size=5)
        return " ".join(segment.text for segment in segments).strip(), getattr(info, "language", "")
    finally:
        path.unlink(missing_ok=True)


def _identity_ok(row: dict, entry: dict, transcript: str, language: str) -> list[str]:
    spoken = _tokens(transcript)
    issues = []
    required_program = _tokens(entry["program"])
    required_artist = _tokens(entry["artist"])
    if not required_program.intersection(spoken): issues.append("wrong_program")
    if not required_artist.intersection(spoken): issues.append("wrong_artist")
    if row["kind"] == "intro":
        rank_word = NUMBER_WORDS[row["language"]][row["rank"] - 1]
        rank_words = {str(row["rank"]), rank_word}
        if not rank_words.intersection(spoken): issues.append("wrong_rank")
    expected_language = "es" if row["language"] == "es-MX" else "pt" if row["language"] == "pt-BR" else "en"
    if language and language != expected_language: issues.append("wrong_language")
    return issues


def generate_and_validate(manifest_path: Path, *, resume: bool = False) -> dict:
    state = preflight(resume=resume)
    plan, rows, entries, prefix = state["plan"], state["rows"], state["entries"], state["prefix"]
    from backend.config import TTS_PROFILES
    from backend.services.supabase_storage import _walk, upload_bytes
    from backend.services.tts.elevenlabs_tts import generate_tts_mp3
    records = []
    existing = {key for language in LANGS for key in _walk(_bucket(language), prefix)} if resume else set()
    # Resume is permitted only after a fresh cache-disabled download records a
    # matching source-text identity and audio SHA-256 provenance record.
    for row in rows:
        entry = entries[row["rank"]]
        kind = "intro" if row["kind"] == "intro" else "detail"
        language_key = "es" if row["language"] == "es-MX" else row["language"]
        profile = TTS_PROFILES[language_key][kind]
        bucket, key = _bucket(row["language"]), _key(prefix, row, entry["spotify_track_id"])
        if key in existing:
            data = _download_staged(bucket, key)
            records.append({"rank": row["rank"], "spotify_track_id": entry["spotify_track_id"], "program": entry["program"], "artist": entry["artist"], "language": row["language"], "kind": row["kind"], "bucket": bucket, "staging_key": key, "text_sha256": row["text_sha256"], "audio_sha256": _sha(data), "size_bytes": len(data), "duration_seconds": _duration(data), "resumed_from_verified_staging": True})
            continue
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            generate_tts_mp3(text=row["text"], out_path=path, voice_id=profile["voice_id"], settings=profile.get("settings"), language=row["language"], overwrite=True)
            data = path.read_bytes(); duration = _duration(data)
            upload_bytes(bucket, key, data)
            records.append({"rank": row["rank"], "spotify_track_id": entry["spotify_track_id"], "program": entry["program"], "artist": entry["artist"], "language": row["language"], "kind": row["kind"], "bucket": bucket, "staging_key": key, "text_sha256": row["text_sha256"], "audio_sha256": _sha(data), "size_bytes": len(data), "duration_seconds": duration})
        finally:
            path.unlink(missing_ok=True)
    model = __import__("faster_whisper", fromlist=["WhisperModel"]).WhisperModel("tiny", device="cpu", compute_type="int8")
    errors, audio_hashes = [], set()
    for record in records:
        try:
            data = _download_staged(record["bucket"], record["staging_key"])
        except Exception as exc:
            errors.append((record["staging_key"], str(exc)))
            continue
        record["downloaded_audio_sha256"] = _sha(data)
        try: record["downloaded_duration_seconds"] = _duration(data)
        except Exception as exc: errors.append((record["staging_key"], str(exc))); continue
        if not data or record["downloaded_audio_sha256"] != record["audio_sha256"]: errors.append((record["staging_key"], "hash_or_empty"))
        if record["audio_sha256"] in audio_hashes: errors.append((record["staging_key"], "duplicate_audio"))
        audio_hashes.add(record["audio_sha256"])
        transcript, language = _transcribe(model, data)
        record["transcript"] = transcript; record["detected_language"] = language
        issues = _identity_ok(next(row for row in rows if (row["rank"], row["language"], row["kind"]) == (record["rank"], record["language"], record["kind"])), entries[record["rank"]], transcript, language)
        if record["kind"] == "intro" or issues:
            if issues: errors.append((record["staging_key"], ",".join(issues)))
    report = {"catalog_id": CATALOG_ID, "staging_prefix": prefix, "records": records, "errors": errors, "complete": not errors and len(records) == 207, "production_writes": 0, "canonical_storage_writes": 0}
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors: raise RuntimeError(f"staged validation failed: {len(errors)} errors; no promotion performed")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate-and-validate", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    if not args.generate_and_validate:
        state = preflight(resume=args.resume); print(json.dumps({"mode": "preflight", "records": len(state["rows"]), "staging_prefix": state["prefix"]}, indent=2)); return
    report = generate_and_validate(args.manifest, resume=args.resume)
    print(json.dumps({"complete": report["complete"], "records": len(report["records"]), "errors": len(report["errors"])}, indent=2))


if __name__ == "__main__": main()
