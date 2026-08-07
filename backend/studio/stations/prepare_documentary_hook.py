"""Resumable, dependency-injected localized documentary hook preparation."""
from __future__ import annotations

import hashlib
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlmodel import Session
from backend.config.tts_config import TTS_PROFILES
from backend.database import engine
from backend.models.dbmodels import ArtistStory, MusicDocuseriesLocale

HookWriter = Callable[..., str]
MAX_HOOK_ATTEMPTS = 3
Synthesizer = Callable[[str, dict[str, Any]], bytes]
Uploader = Callable[[str, str, bytes], None]
SessionFactory = Callable[[], Session]


def hook_text_digest(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def hook_key(documentary: Any, language: str, text: str) -> str:
    return f"documentary-hooks/{documentary.source_type}/{documentary.source_id}/{language}/hook-{hook_text_digest(text)[:16]}.mp3"


def validate_hook(text: str, story: str, language: str) -> str:
    value = " ".join(text.split())
    if language not in {"en", "es", "pt-BR"}:
        raise ValueError(f"Unsupported hook language: {language}")
    if not 30 <= len(value.split()) <= 85:
        raise ValueError("Hook must target approximately 15-25 seconds")
    continuation = ("the answer unfolds", "keep watching", "what came next", "the story continues", "the rest of the story")
    if not value.endswith(("?", "!")) and not any(phrase in value.casefold() for phrase in continuation):
        raise ValueError("Hook must end with an unanswered question or strong reason to continue")
    story_terms = {word.casefold() for word in re.findall(r"[\w'-]+", story) if len(word) >= 4}
    hook_terms = {word.casefold() for word in re.findall(r"[\w'-]+", value) if len(word) >= 4}
    if len(story_terms & hook_terms) < 2:
        raise ValueError("Hook must use at least two source-story facts")
    if not re.search(r"\d|[A-Z][\w'-]+", value):
        raise ValueError("Hook must include a concrete source detail")
    return value


def default_hook_writer(story: str, language: str, correction: str | None = None) -> str:
    from backend.services.xai_client import ask_xai
    prompt = f"""Write only a natural {language} documentary hook, 15-25 seconds.
Use two specific moments or facts in the supplied story. Contrast an earlier moment with a later consequence. Include a concrete name, number, place, event, or surprising detail. End with an unanswered question or an equally compelling reason to continue. Never invent facts.

SOURCE STORY:
{story}

CORRECTION REQUIRED:
{correction or "None; write the hook now."}"""
    return ask_xai("You are a precise multilingual documentary writer.", prompt, temperature=0.25)


def fallback_hook(story: str, language: str) -> str:
    """Deterministic safe fallback when bounded model corrections fail."""
    words = re.findall(r"[\w'-]+|[.,;:]", story)
    excerpt = " ".join(words[:52]).strip(" ,;:")
    return f"{excerpt}. The clues in these moments point to the consequence that followed; the rest of the story unfolds."


def generate_validated_hook(story: str, language: str, writer: HookWriter) -> str:
    error = ""
    for _ in range(MAX_HOOK_ATTEMPTS):
        try:
            try:
                candidate = writer(story, language, correction=error or None)
            except TypeError:
                candidate = writer(story, language)
            return validate_hook(candidate, story, language)
        except ValueError as exc:
            error = str(exc)
    return validate_hook(fallback_hook(story, language), story, language)


def default_synthesizer(text: str, profile: dict[str, Any]) -> bytes:
    from backend.services.tts.elevenlabs_tts import generate_tts_mp3
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "hook.mp3"
        generate_tts_mp3(text=text, out_path=output, **profile)
        return output.read_bytes()


def default_uploader(bucket: str, key: str, data: bytes) -> None:
    from backend.services.supabase_client import supabase
    supabase.storage.from_(bucket).upload(key, data, {"content-type": "audio/mpeg", "upsert": "true"})


def prepare_documentary_hooks(documentary: Any, *, writer: HookWriter = default_hook_writer, synthesizer: Synthesizer = default_synthesizer, uploader: Uploader = default_uploader, session_factory: SessionFactory = lambda: Session(engine)) -> bool:
    model = MusicDocuseriesLocale if documentary.source_type == "music_docuseries" else ArtistStory
    changed = False
    with session_factory() as db:
        for locale in documentary.languages:
            row = db.get(model, locale.locale_id)
            if row is None:
                raise LookupError(f"Locale {locale.locale_id} disappeared while preparing hooks")
            text = getattr(row, "hook_text", None)
            if text:
                text = validate_hook(text, locale.story_text, locale.language_code)
            else:
                text = generate_validated_hook(locale.story_text, locale.language_code, writer)
                row.hook_text = text
                row.hook_tts_bucket = row.hook_tts_key = None
                changed = True
            expected_key = hook_key(documentary, locale.language_code, text)
            if row.hook_tts_bucket != row.tts_bucket or row.hook_tts_key != expected_key:
                bucket = str(row.tts_bucket or "")
                if not bucket:
                    raise RuntimeError(f"Missing TTS bucket for {locale.language_code} hook")
                audio = synthesizer(text, dict(TTS_PROFILES[locale.language_code]["artist_story"]))
                if not audio:
                    raise RuntimeError("Hook TTS returned empty audio")
                uploader(bucket, expected_key, audio)
                row.hook_tts_bucket, row.hook_tts_key = bucket, expected_key
                changed = True
            db.add(row)
        if changed:
            db.commit()
    return changed
