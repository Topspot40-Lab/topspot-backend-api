"""Strict, offline validation contract for future catalog narration media.

An audio object is not accepted merely because it exists: the generation/audit
record must carry byte and text hashes plus an ASR identity check.  Callers
collect URLs and Storage facts separately; this module makes no network calls.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable


def validate_media_records(
    entries: Iterable[dict], narration_records: Iterable[dict], media_records: Iterable[dict]
) -> dict:
    entries = list(entries)
    narration = {(r["rank"], r["language"], r["kind"]): r for r in narration_records}
    media = {(r["rank"], r["language"], r["kind"]): r for r in media_records}
    expected = {
        (entry["proposed_rank"], language, kind): entry
        for entry in entries
        for language in ("en", "es-MX", "pt-BR")
        for kind in ("intro", "short_detail", "long_detail")
    }
    errors = []
    for key, entry in expected.items():
        text = narration.get(key)
        asset = media.get(key)
        if text is None or asset is None:
            errors.append((key, "missing_record")); continue
        if text["text_sha256"] != hashlib.sha256(text["text"].encode("utf-8")).hexdigest():
            errors.append((key, "text_hash_mismatch"))
        if not entry.get("artist"):
            errors.append((key, "missing_artist_metadata"))
        if not entry.get("artwork_source") or not asset.get("artwork_url"):
            errors.append((key, "missing_artwork"))
        if not asset.get("authoritative_playback_url"):
            errors.append((key, "missing_authoritative_playback_url"))
        if not asset.get("audio_sha256"):
            errors.append((key, "missing_audio_hash"))
        if asset.get("text_sha256") != text["text_sha256"]:
            errors.append((key, "resume_text_hash_mismatch"))
        if key[2] == "intro":
            spoken = {token.casefold() for token in asset.get("spoken_identity_tokens", [])}
            required = {token.casefold() for token in entry["program"].split() if len(token) > 2}
            if not required.intersection(spoken):
                errors.append((key, "spoken_program_identity_not_verified"))
    unexpected = sorted(set(narration) | set(media) - set(expected))
    if unexpected:
        errors.extend((key, "unexpected_record") for key in unexpected)
    return {"expected": len(expected), "errors": errors, "complete": not errors}
