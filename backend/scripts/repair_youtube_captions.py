"""Regenerate and, only with --apply, replace one existing YouTube caption track."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


KNOWN_VIDEO_IDS = {("music_in_the_new_millennium", "en"): "tTiah5ncQsw"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--language", required=True, choices=("en", "es", "pt-BR"))
    parser.add_argument("--video-id", help="required unless this slug/language has a registered existing video ID")
    parser.add_argument("--work-root", type=Path, default=Path("backend/studio/work"))
    parser.add_argument(
        "--factory-root",
        type=Path,
        help="exact <slug>/factory directory containing the authoritative production assets",
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--legacy-env-file",
        type=Path,
        help=(
            "required only to recover a version-2 narration sidecar; the file is "
            "read solely for DATABASE_URL or POSTGRES_URL"
        ),
    )
    parser.add_argument("--client-secrets", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--align", action="store_true", help="authorize ElevenLabs only to fill missing alignment cache entries")
    mode.add_argument("--apply", action="store_true", help="replace only this non-ASR caption track")
    args = parser.parse_args(argv)
    if args.apply and not args.client_secrets:
        parser.error("--client-secrets is required with --apply")
    if args.env_file and args.align:
        from dotenv import load_dotenv
        load_dotenv(args.env_file.resolve(), override=False)

    video_id = args.video_id or KNOWN_VIDEO_IDS.get((args.slug, args.language))
    if not video_id:
        parser.error("--video-id is required for this slug/language")
    factory = _factory_root(args.factory_root, work_root=args.work_root, slug=args.slug)
    transcripts = _localized_transcripts(
        factory,
        args.language,
        slug=args.slug,
        legacy_env_file=args.legacy_env_file,
    )
    from backend.studio.youtube.publishing_package import build_aligned_captions, documentary_timing, media_duration
    narration = factory / "delivery" / args.language / "narration"
    timing = documentary_timing(factory, language=args.language, probe=media_duration)
    hook_duration = timing.durations["hook"]
    story_duration = timing.durations["story"]
    hook_start = timing.hook_start
    story_start = timing.story_start
    output = factory / "publishing_repair" / args.language / "captions.vtt"
    build_kwargs = {
        "factory": factory,
        "hook_audio": narration / "hook.mp3",
        "hook_text": transcripts.hook,
        "hook_start": hook_start,
        "hook_duration": hook_duration,
        "story_audio": narration / "story.mp3",
        "story_text": transcripts.story,
        "story_start": story_start,
        "story_duration": story_duration,
    }
    alignment_paths = _alignment_cache_paths(factory, narration, transcripts)
    if args.align:
        corrected_vtt = build_aligned_captions(**build_kwargs)
    else:
        corrected_vtt = build_aligned_captions(
            **build_kwargs, requester=_cached_alignment_only
        )
    print(f"SLUG: {args.slug}")
    print(f"LANGUAGE: {args.language}")
    print(f"FACTORY ROOT: {factory}")
    print(f"VIDEO ID: {video_id}")
    print(f"CAPTION PATH: {output}")
    if args.align:
        for path in alignment_paths:
            print(f"ALIGNMENT CACHE: {path}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(corrected_vtt, encoding="utf-8")
        print("ALIGNMENT COMPLETE: corrected VTT was generated locally; no YouTube API call was made.")
        return 0
    if not args.apply:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(corrected_vtt, encoding="utf-8")
        print("DRY RUN: cached alignment was validated and corrected VTT was generated locally; no API call was made.")
        return 0
    if not output.is_file() or output.read_text(encoding="utf-8") != corrected_vtt:
        raise RuntimeError(
            f"Corrected VTT is missing or does not match the validated alignment cache: {output}"
        )
    from backend.studio.youtube.auth import get_credentials
    from backend.studio.youtube.uploader import build_youtube_service, upload_captions
    upload_captions(build_youtube_service(get_credentials(args.client_secrets)), video_id, args.language, output)
    print("APPLIED: only the existing non-ASR caption track was updated; the video and metadata were not changed.")
    return 0


@dataclass(frozen=True)
class LocalizedTranscripts:
    hook: str
    story: str


SEGMENTS = ("hook", "intro", "story", "outro")


def validated_repair_fingerprint(
    *, factory: Path, slug: str, language: str, legacy_env_file: Path | None = None
) -> str:
    """Return a stable proof of the exact repair that may be sent to YouTube.

    This validates the authoritative narration/transcript source, both cached
    alignments, timing, and the already-generated VTT.  It performs no remote
    request; v2 transcript recovery is only available when the caller has
    explicitly supplied its legacy environment file.
    """
    transcripts = _localized_transcripts(factory, language, slug=slug, legacy_env_file=legacy_env_file)
    return _validated_fingerprint(factory, language, transcripts)


def offline_validated_repair_fingerprint(*, factory: Path, language: str) -> str:
    """Validate a local repair binding without database or network access.

    V3 uses its authoritative transcript sidecar.  For historical v2 work the
    existing VTT is the locally retained transcript representation; its two
    timeline regions are independently revalidated against their cache keys.
    """
    sidecar = factory / "delivery" / language / "narration.inputs.json"
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        version = payload.get("version")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        raise RuntimeError("Authoritative narration inputs are invalid") from exc
    if version == 3:
        transcripts = _localized_transcripts(factory, language)
    elif version == 2:
        hashes = payload.get("source_sha256") if isinstance(payload, dict) else None
        if not isinstance(hashes, dict) or set(hashes) != set(SEGMENTS):
            raise RuntimeError("Authoritative narration audio digests are missing")
        _verify_narration_hashes(factory / "delivery" / language / "narration", hashes, sidecar)
        transcripts = _transcripts_from_repair_vtt(factory, language)
    else:
        raise RuntimeError("Authoritative narration inputs have an unsupported schema")
    return _validated_fingerprint(factory, language, transcripts)


def _validated_fingerprint(factory: Path, language: str, transcripts: LocalizedTranscripts) -> str:
    from backend.studio.youtube.publishing_package import build_aligned_captions, documentary_timing, media_duration

    narration = factory / "delivery" / language / "narration"
    timing = documentary_timing(factory, language=language, probe=media_duration)
    alignment_paths = _alignment_cache_paths(factory, narration, transcripts)
    # A bootstrap/audit must only validate existing primary cache entries.  Do
    # not promote a quarantine file as a side effect of proving a repair.
    if any(not path.is_file() or path.stat().st_size == 0 for path in alignment_paths):
        raise RuntimeError("A validated alignment cache is required for caption repair")
    vtt = build_aligned_captions(
        factory=factory, hook_audio=narration / "hook.mp3", hook_text=transcripts.hook,
        hook_start=timing.hook_start, hook_duration=timing.durations["hook"],
        story_audio=narration / "story.mp3", story_text=transcripts.story,
        story_start=timing.story_start, story_duration=timing.durations["story"],
        requester=_cached_alignment_only,
    )
    output = factory / "publishing_repair" / language / "captions.vtt"
    if not output.is_file() or output.read_text(encoding="utf-8") != vtt:
        raise RuntimeError("Corrected VTT is missing or does not match the validated alignment cache")
    components = {
        "vtt_sha256": _sha256(output),
        # All four audio inputs are bound.  Intro/outro do not have captions,
        # but changing either means this is no longer the exact assembled
        # repair context (and intro can also move story timing).
        "narration_sha256": {part: _sha256(narration / f"{part}.mp3") for part in SEGMENTS},
        "hook_transcript_sha256": hashlib.sha256(transcripts.hook.encode("utf-8")).hexdigest(),
        "story_transcript_sha256": hashlib.sha256(transcripts.story.encode("utf-8")).hexdigest(),
        "hook_alignment_sha256": _sha256(alignment_paths[0]),
        "story_alignment_sha256": _sha256(alignment_paths[1]),
        "hook_start": timing.hook_start,
        "story_start": timing.story_start,
        "expected_duration": timing.expected_duration,
        "documentary_duration": timing.documentary_duration,
    }
    return hashlib.sha256(json.dumps(components, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _transcripts_from_repair_vtt(factory: Path, language: str) -> LocalizedTranscripts:
    """Recover only the cleaned hook/story text encoded in a repair VTT."""
    from backend.studio.youtube.publishing_package import documentary_timing, media_duration

    path = factory / "publishing_repair" / language / "captions.vtt"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError("Corrected VTT is missing") from exc
    timing = documentary_timing(factory, language=language, probe=media_duration)
    hook: list[str] = []
    story: list[str] = []
    for index, line in enumerate(lines):
        if " --> " not in line or index + 1 >= len(lines):
            continue
        try:
            start = _vtt_seconds(line.split(" --> ", 1)[0])
        except ValueError as exc:
            raise RuntimeError("Corrected VTT has an invalid cue timeline") from exc
        text = lines[index + 1].strip()
        if not text:
            raise RuntimeError("Corrected VTT has an empty cue")
        if start < timing.story_start:
            hook.append(text)
        else:
            story.append(text)
    if not hook or not story:
        raise RuntimeError("Corrected VTT does not contain both repaired transcript regions")
    return LocalizedTranscripts(" ".join(hook), " ".join(story))


def _vtt_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _factory_root(factory_root: Path | None, *, work_root: Path, slug: str) -> Path:
    """Resolve an exact topic factory directory and reject cross-topic inputs."""
    candidate = factory_root if factory_root is not None else work_root / slug / "factory"
    factory = candidate.expanduser().resolve()
    if factory.name != "factory" or factory.parent.name != slug:
        raise RuntimeError(
            f"Factory root must be the exact {slug}/factory directory: {factory}"
        )
    if not factory.is_dir():
        raise RuntimeError(f"Factory root does not exist or is not a directory: {factory}")
    return factory


def _cached_alignment_only(*_: object, **__: object) -> object:
    """Repairs must never create alignments by contacting ElevenLabs."""
    from backend.studio.youtube.caption_alignment import AlignmentCacheMissing

    raise AlignmentCacheMissing(
        "A validated alignment cache is required for caption repair; ElevenLabs is not called."
    )


# The alignment layer recognizes this explicit capability marker before it
# checks credentials, ensuring cache-only audits never depend on an API key.
_cached_alignment_only._alignment_cache_only = True  # type: ignore[attr-defined]


def _alignment_cache_paths(
    factory: Path, narration: Path, transcripts: LocalizedTranscripts
) -> tuple[Path, Path]:
    """Return the cache entries the caption builder will use for this repair."""
    from backend.studio.youtube.caption_alignment import clean_transcript

    cache = factory / "cache" / "caption_alignment"
    return (
        cache / f"{_alignment_cache_key(narration / 'hook.mp3', clean_transcript(transcripts.hook))}.json",
        cache / f"{_alignment_cache_key(narration / 'story.mp3', clean_transcript(transcripts.story))}.json",
    )


def _alignment_cache_key(audio: Path, transcript: str) -> str:
    digest = hashlib.sha256()
    digest.update(audio.read_bytes())
    digest.update(b"\0")
    digest.update(transcript.encode("utf-8"))
    digest.update(b"\0forced-alignment-v1")
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _localized_transcripts(
    factory: Path,
    language: str,
    *,
    slug: str | None = None,
    legacy_env_file: Path | None = None,
) -> LocalizedTranscripts:
    """Load v3 locally, or explicitly recover a verified legacy-v2 binding."""
    narration = factory / "delivery" / language / "narration"
    sidecar = factory / "delivery" / language / "narration.inputs.json"
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Authoritative narration inputs are missing: {sidecar}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Authoritative narration inputs are invalid: {sidecar}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"Authoritative narration inputs have an unsupported schema: {sidecar}")
    hashes = payload.get("source_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(SEGMENTS):
        raise RuntimeError(f"Authoritative narration audio digests are missing: {sidecar}")

    # Commit 358d41c's v2 writer used hashlib.sha256(raw_mp3_bytes) for each
    # segment.  It did not normalize or hash transcript text.  Verify that
    # exact binding before any database recovery can provide text for captions.
    _verify_narration_hashes(narration, hashes, sidecar)

    if payload.get("version") == 2:
        if legacy_env_file is None:
            raise RuntimeError(
                "Version-2 narration recovery requires --legacy-env-file; "
                "database access is disabled without it."
            )
        if not slug:
            raise RuntimeError("Version-2 narration recovery requires the production slug")
        texts = _recover_legacy_v2_texts(slug, language, legacy_env_file)
        # August 7 v2 stored text only for the hook and story.  Intro/outro
        # were shared prerecorded assets, but their MP3 hashes above remain
        # part of the mandatory v2 source binding.
        required_segments = ("hook", "story")
    elif payload.get("version") == 3:
        texts = payload.get("transcripts")
        required_segments = ("hook", "story")
    else:
        raise RuntimeError(f"Authoritative narration inputs have an unsupported schema: {sidecar}")

    if not isinstance(texts, dict):
        raise RuntimeError(f"Authoritative localized transcripts are missing: {sidecar}")
    values = {part: texts.get(part) for part in required_segments}
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise RuntimeError(f"Authoritative localized transcript is missing: {sidecar}")
    return LocalizedTranscripts(hook=values["hook"], story=values["story"])


def _verify_narration_hashes(narration: Path, hashes: dict[str, Any], sidecar: Path) -> None:
    """Verify the exact raw-byte algorithm used by the v2 sidecar writer."""
    invalid: list[str] = []
    mismatched: list[str] = []
    for part in SEGMENTS:
        audio = narration / f"{part}.mp3"
        expected = hashes[part]
        if not isinstance(expected, str) or len(expected) != 64 or not audio.is_file() or audio.stat().st_size == 0:
            invalid.append(part)
        elif _sha256(audio) != expected:
            mismatched.append(part)
    if invalid:
        raise RuntimeError(
            "Authoritative narration MP3 is missing or invalid for fields: "
            + ", ".join(invalid)
        )
    if mismatched:
        # Do not stop at the first mismatch: every v2 source binding remains
        # mandatory, while the diagnostic stays free of paths and transcript text.
        raise RuntimeError(
            "Authoritative narration source hash mismatch for fields: "
            + ", ".join(mismatched)
        )


def _database_url_from_legacy_env(path: Path) -> str:
    """Read DATABASE_URL, then POSTGRES_URL; do not load the env file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError("Legacy database environment file cannot be read") from exc
    values: dict[str, str] = {}
    for line in lines:
        match = re.match(
            r"\s*(?:export\s+)?(DATABASE_URL|POSTGRES_URL)\s*=\s*(.*)\s*$",
            line,
        )
        if match:
            value = match.group(2).strip()
            if len(value) >= 2 and value[:1] == value[-1:] and value[:1] in {"'", '"'}:
                value = value[1:-1]
            if value:
                values.setdefault(match.group(1), value)
    if database_url := values.get("DATABASE_URL"):
        return database_url
    if postgres_url := values.get("POSTGRES_URL"):
        return postgres_url
    raise RuntimeError("DATABASE_URL/POSTGRES_URL is missing")


def _recover_legacy_v2_texts(slug: str, language: str, env_file: Path) -> dict[str, str]:
    """Fetch the original hook/story locale texts after v2 audio verifies."""
    database_url = _database_url_from_legacy_env(env_file)
    try:
        return _legacy_locale_texts(slug, language, database_url)
    except _LegacyRecoveryError as exc:
        raise RuntimeError(str(exc)) from None
    except Exception:
        # Database drivers often include their connection URL in diagnostics.
        raise RuntimeError("Legacy database connection/query failure") from None


class _LegacyRecoveryError(RuntimeError):
    """A safe, actionable legacy-recovery failure message."""


def _legacy_locale_texts(slug: str, language: str, database_url: str) -> dict[str, str]:
    """Read the docuseries locale through the legacy narration lookup.

    The August 7 narrator first selected ``music_docuseries`` by slug, then
    selected ``music_docuseries_locale`` by ``docuseries_id`` and
    ``language_code``.  It synthesized ``hook_text`` and ``story_text``;
    intro/outro were shared prerecorded assets with no database transcript.
    Do not use the similarly shaped artist-story fallback: it was never a
    source for a music-docuseries narration.
    """
    from sqlalchemy import text
    from sqlalchemy.pool import NullPool
    from sqlmodel import create_engine

    engine = create_engine(database_url, poolclass=NullPool, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            document = connection.execute(
                text("SELECT id FROM music_docuseries WHERE slug = :slug"),
                {"slug": slug},
            ).mappings().first()
            if document is None:
                raise _LegacyRecoveryError("Legacy database slug not found")
            locale = connection.execute(
                text(
                    "SELECT hook_text, story_text "
                    "FROM music_docuseries_locale "
                    "WHERE docuseries_id = :docuseries_id AND language_code = :language"
                ),
                {"docuseries_id": document["id"], "language": language},
            ).mappings().first()
    finally:
        engine.dispose()
    if locale is None:
        raise _LegacyRecoveryError("Legacy database language/locale not found")
    return _transcripts_from_legacy_locale(locale)


def _transcripts_from_legacy_locale(locale: Any) -> dict[str, str]:
    """Return only the two database texts the v2 narrator actually used."""
    texts = {part: locale.get(part) for part in ("hook_text", "story_text")}
    missing = [part for part, value in texts.items() if not isinstance(value, str) or not value.strip()]
    if missing:
        raise _LegacyRecoveryError(
            "Legacy database locale is missing text fields: "
            + ", ".join(missing)
        )
    return {"hook": texts["hook_text"], "story": texts["story_text"]}  # type: ignore[return-value]


if __name__ == "__main__":
    raise SystemExit(main())
