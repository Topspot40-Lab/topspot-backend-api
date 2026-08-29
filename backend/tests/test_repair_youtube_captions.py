from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from backend.scripts import repair_youtube_captions as repair
from backend.studio.studio_config import (
    HOOK_PAUSE_SECONDS,
    INTRO_PAUSE_SECONDS,
    OUTRO_PAUSE_SECONDS,
)
from backend.studio.youtube.caption_alignment import AlignmentError
from backend.studio.youtube.publishing_package import build_aligned_captions


def _write_authoritative_inputs(factory: Path, language: str) -> None:
    narration = factory / "delivery" / language / "narration"
    narration.mkdir(parents=True)
    hashes: dict[str, str] = {}
    for part in ("hook", "intro", "story", "outro"):
        audio = narration / f"{part}.mp3"
        audio.write_bytes(f"{language}:{part}".encode())
        hashes[part] = hashlib.sha256(audio.read_bytes()).hexdigest()
    (factory / "delivery" / language / "narration.inputs.json").write_text(
        json.dumps(
            {
                "version": 3,
                "source_sha256": hashes,
                "transcripts": {
                    "hook": "The authoritative hook.",
                    "story": "The authoritative story.",
                },
            }
        ),
        encoding="utf-8",
    )
    opening = factory / "shared" / "opening.mp4"
    opening.parent.mkdir(parents=True)
    opening.write_bytes(b"opening")
    (factory / "delivery" / language / "documentary.mp4").write_bytes(b"documentary")


def _write_legacy_v2_inputs(factory: Path, language: str) -> None:
    _write_authoritative_inputs(factory, language)
    sidecar = factory / "delivery" / language / "narration.inputs.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload.pop("transcripts")
    payload["version"] = 2
    sidecar.write_text(json.dumps(payload), encoding="utf-8")


def _legacy_texts() -> dict[str, str]:
    return {
        "hook": "The original hook.",
        "story": "The original story.",
    }


def _patch_durations(monkeypatch: pytest.MonkeyPatch) -> None:
    def duration(path: Path) -> float:
        if path.name == "opening.mp4":
            return 3.0
        if path.name == "documentary.mp4":
            return 3.0 + 40.0 + HOOK_PAUSE_SECONDS + INTRO_PAUSE_SECONDS + OUTRO_PAUSE_SECONDS + 2.0
        return 10.0

    monkeypatch.setattr(
        "backend.studio.youtube.publishing_package.media_duration", duration
    )


def test_dry_run_uses_valid_external_factory_root_without_importing_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    language = "en"
    factory = tmp_path / "external-production" / "music_in_the_new_millennium" / "factory"
    _write_authoritative_inputs(factory, language)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "backend.database", None)
    captured: dict[str, str] = {}

    def captions(**kwargs: object) -> str:
        captured["hook"] = str(kwargs["hook_text"])
        captured["story"] = str(kwargs["story_text"])
        with pytest.raises(RuntimeError, match="ElevenLabs is not called"):
            kwargs["requester"]()  # type: ignore[index, operator]
        return "WEBVTT\n"

    _patch_durations(monkeypatch)
    monkeypatch.setattr(
        "backend.studio.youtube.publishing_package.build_aligned_captions", captions
    )

    assert repair.main([
        "--slug", "music_in_the_new_millennium",
        "--language", language,
        "--factory-root", str(factory),
    ]) == 0
    assert captured == {
        "hook": "The authoritative hook.",
        "story": "The authoritative story.",
    }
    assert (factory / "publishing_repair" / language / "captions.vtt").read_text(encoding="utf-8") == "WEBVTT\n"
    output = capsys.readouterr().out
    assert "SLUG: music_in_the_new_millennium" in output
    assert "LANGUAGE: en" in output
    assert f"FACTORY ROOT: {factory.resolve()}" in output
    assert "VIDEO ID: tTiah5ncQsw" in output
    assert f"CAPTION PATH: {factory.resolve() / 'publishing_repair' / language / 'captions.vtt'}" in output


def test_align_authorizes_alignment_and_never_builds_youtube_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = tmp_path / "external-production" / "music_in_the_new_millennium" / "factory"
    _write_authoritative_inputs(factory, "en")
    _patch_durations(monkeypatch)
    called: dict[str, bool] = {}

    def captions(**kwargs: object) -> str:
        assert "requester" not in kwargs
        called["alignment"] = True
        return "WEBVTT\n"

    monkeypatch.setattr(
        "backend.studio.youtube.publishing_package.build_aligned_captions", captions
    )
    monkeypatch.setattr(
        "backend.studio.youtube.auth.get_credentials",
        lambda *_: pytest.fail("--align must not build YouTube credentials"),
    )

    assert repair.main([
        "--slug", "music_in_the_new_millennium",
        "--language", "en",
        "--factory-root", str(factory),
        "--align",
    ]) == 0
    assert called == {"alignment": True}
    output = capsys.readouterr().out
    assert "ALIGNMENT CACHE:" in output
    assert f"CAPTION PATH: {factory.resolve() / 'publishing_repair' / 'en' / 'captions.vtt'}" in output


def test_apply_uses_only_validated_cache_and_existing_vtt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = tmp_path / "external-production" / "music_in_the_new_millennium" / "factory"
    _write_authoritative_inputs(factory, "en")
    output = factory / "publishing_repair" / "en" / "captions.vtt"
    output.parent.mkdir(parents=True)
    output.write_text("WEBVTT\n", encoding="utf-8")
    _patch_durations(monkeypatch)
    uploaded: dict[str, object] = {}

    def captions(**kwargs: object) -> str:
        assert "requester" in kwargs
        return "WEBVTT\n"

    monkeypatch.setattr(
        "backend.studio.youtube.publishing_package.build_aligned_captions", captions
    )
    monkeypatch.setattr(
        "backend.studio.youtube.auth.get_credentials", lambda _: "credentials"
    )
    monkeypatch.setattr(
        "backend.studio.youtube.uploader.build_youtube_service", lambda _: "service"
    )
    monkeypatch.setattr(
        "backend.studio.youtube.uploader.upload_captions",
        lambda service, video_id, language, path: uploaded.update(
            service=service, video_id=video_id, language=language, path=path
        ),
    )

    assert repair.main([
        "--slug", "music_in_the_new_millennium",
        "--language", "en",
        "--factory-root", str(factory),
        "--apply",
        "--client-secrets", "unused.json",
    ]) == 0
    assert uploaded == {
        "service": "service",
        "video_id": "tTiah5ncQsw",
        "language": "en",
        "path": output,
    }


def test_align_and_apply_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit, match="2"):
        repair.main([
            "--slug", "music_in_the_new_millennium",
            "--language", "en",
            "--align",
            "--apply",
        ])


def test_apply_fails_before_youtube_when_narration_binding_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = tmp_path / "external-production" / "music_in_the_new_millennium" / "factory"
    _write_authoritative_inputs(factory, "en")
    (factory / "delivery" / "en" / "narration" / "story.mp3").write_bytes(b"changed")
    monkeypatch.setattr(
        "backend.studio.youtube.auth.get_credentials",
        lambda *_: pytest.fail("invalid cache inputs must not reach YouTube credentials"),
    )

    with pytest.raises(RuntimeError, match="source hash mismatch for fields: story"):
        repair.main([
            "--slug", "music_in_the_new_millennium",
            "--language", "en",
            "--factory-root", str(factory),
            "--apply",
            "--client-secrets", "unused.json",
        ])


def test_factory_root_rejects_slug_mismatch(tmp_path: Path) -> None:
    factory = tmp_path / "another_topic" / "factory"
    factory.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="exact music_in_the_new_millennium/factory"):
        repair._factory_root(
            factory, work_root=tmp_path, slug="music_in_the_new_millennium"
        )


def test_factory_root_rejects_malformed_path(tmp_path: Path) -> None:
    topic = tmp_path / "music_in_the_new_millennium"
    topic.mkdir()

    with pytest.raises(RuntimeError, match="exact music_in_the_new_millennium/factory"):
        repair._factory_root(
            topic, work_root=tmp_path, slug="music_in_the_new_millennium"
        )


def test_localized_transcripts_fail_closed_when_assets_are_missing(tmp_path: Path) -> None:
    factory = tmp_path / "factory"
    _write_authoritative_inputs(factory, "en")
    (factory / "delivery" / "en" / "narration" / "outro.mp3").unlink()

    with pytest.raises(RuntimeError, match="narration MP3 is missing or invalid"):
        repair._localized_transcripts(factory, "en")


def test_localized_transcripts_fail_closed_when_audio_changes(tmp_path: Path) -> None:
    factory = tmp_path / "factory"
    _write_authoritative_inputs(factory, "en")
    (factory / "delivery" / "en" / "narration" / "story.mp3").write_bytes(b"different")

    with pytest.raises(RuntimeError, match="source hash mismatch for fields: story"):
        repair._localized_transcripts(factory, "en")


def test_legacy_env_prefers_database_url_over_postgres_url(tmp_path: Path) -> None:
    env_file = tmp_path / "legacy.env"
    env_file.write_text(
        "POSTGRES_URL=postgresql://fallback.example.test/database\n"
        "DATABASE_URL=postgresql://preferred.example.test/database\n",
        encoding="utf-8",
    )

    assert repair._database_url_from_legacy_env(env_file) == "postgresql://preferred.example.test/database"


def test_legacy_env_uses_postgres_url_as_database_url_fallback(tmp_path: Path) -> None:
    env_file = tmp_path / "legacy.env"
    env_file.write_text("POSTGRES_URL=postgresql://fallback.example.test/database\n", encoding="utf-8")

    assert repair._database_url_from_legacy_env(env_file) == "postgresql://fallback.example.test/database"


def test_legacy_env_rejects_missing_database_url_and_postgres_url(tmp_path: Path) -> None:
    env_file = tmp_path / "legacy.env"
    env_file.write_text("UNRELATED_TOKEN=secret\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="^DATABASE_URL/POSTGRES_URL is missing$"):
        repair._database_url_from_legacy_env(env_file)


def test_legacy_v2_recovers_only_after_exact_four_audio_hashes_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = tmp_path / "factory"
    _write_legacy_v2_inputs(factory, "en")
    env_file = tmp_path / "legacy.env"
    env_file.write_text("DATABASE_URL=postgresql://user:secret@example.test/database\n", encoding="utf-8")
    called: dict[str, str] = {}

    def locale_texts(slug: str, language: str, database_url: str) -> dict[str, str]:
        called.update(slug=slug, language=language, database_url=database_url)
        return _legacy_texts()

    monkeypatch.setattr(repair, "_legacy_locale_texts", locale_texts)
    assert repair._localized_transcripts(
        factory, "en", slug="music_in_the_new_millennium", legacy_env_file=env_file
    ) == repair.LocalizedTranscripts("The original hook.", "The original story.")
    assert called == {
        "slug": "music_in_the_new_millennium",
        "language": "en",
        "database_url": "postgresql://user:secret@example.test/database",
    }


def test_legacy_v2_rejects_one_mismatched_field_before_database_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = tmp_path / "factory"
    _write_legacy_v2_inputs(factory, "en")
    (factory / "delivery" / "en" / "narration" / "intro.mp3").write_bytes(b"changed")
    env_file = tmp_path / "legacy.env"
    env_file.write_text("DATABASE_URL=postgresql://example.test/database\n", encoding="utf-8")
    monkeypatch.setattr(repair, "_legacy_locale_texts", lambda *_: pytest.fail("database must not be called"))
    with pytest.raises(RuntimeError, match="source hash mismatch for fields: intro"):
        repair._localized_transcripts(
            factory, "en", slug="music_in_the_new_millennium", legacy_env_file=env_file
        )


def test_legacy_v2_reports_missing_database_locale_without_disclosing_connection_details(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    factory = tmp_path / "factory"
    _write_legacy_v2_inputs(factory, "en")
    env_file = tmp_path / "legacy.env"
    env_file.write_text("DATABASE_URL=postgresql://example.test/database\n", encoding="utf-8")
    monkeypatch.setattr(
        repair, "_legacy_locale_texts", lambda *_: (_ for _ in ()).throw(repair._LegacyRecoveryError("Legacy database language/locale not found"))
    )
    with pytest.raises(RuntimeError, match="^Legacy database language/locale not found$"):
        repair._localized_transcripts(
            factory, "en", slug="music_in_the_new_millennium", legacy_env_file=env_file
        )


def test_legacy_v2_requires_explicit_env_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    factory = tmp_path / "factory"
    _write_legacy_v2_inputs(factory, "en")
    monkeypatch.setattr(repair, "_legacy_locale_texts", lambda *_: pytest.fail("database must not be called"))
    with pytest.raises(RuntimeError, match="requires --legacy-env-file"):
        repair._localized_transcripts(factory, "en", slug="music_in_the_new_millennium")


def test_legacy_database_credentials_are_not_disclosed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "do-not-disclose-this-password"
    env_file = tmp_path / "legacy.env"
    env_file.write_text(
        f"DATABASE_URL=postgresql://user:{secret}@example.test/database\nUNRELATED_TOKEN=also-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        repair, "_legacy_locale_texts", lambda *_: (_ for _ in ()).throw(ValueError(secret))
    )
    with pytest.raises(RuntimeError) as excinfo:
        repair._recover_legacy_v2_texts("music_in_the_new_millennium", "en", env_file)
    assert secret not in str(excinfo.value)
    assert "UNRELATED_TOKEN" not in str(excinfo.value)
    assert str(excinfo.value) == "Legacy database connection/query failure"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Legacy database slug not found", "Legacy database slug not found"),
        ("Legacy database language/locale not found", "Legacy database language/locale not found"),
        (
            "Legacy database locale is missing text fields: hook_text, story_text",
            "Legacy database locale is missing text fields: hook_text, story_text",
        ),
    ],
)
def test_legacy_recovery_preserves_safe_specific_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str, expected: str
) -> None:
    env_file = tmp_path / "legacy.env"
    env_file.write_text("POSTGRES_URL=postgresql://example.test/database\n", encoding="utf-8")
    monkeypatch.setattr(
        repair,
        "_legacy_locale_texts",
        lambda *_: (_ for _ in ()).throw(repair._LegacyRecoveryError(message)),
    )

    with pytest.raises(RuntimeError, match=f"^{re.escape(expected)}$"):
        repair._recover_legacy_v2_texts("music_in_the_new_millennium", "en", env_file)


def test_legacy_v2_reports_all_mismatched_source_hash_fields(tmp_path: Path) -> None:
    factory = tmp_path / "factory"
    _write_legacy_v2_inputs(factory, "en")
    narration = factory / "delivery" / "en" / "narration"
    (narration / "hook.mp3").write_bytes(b"changed hook")
    (narration / "outro.mp3").write_bytes(b"changed outro")
    sidecar = factory / "delivery" / "en" / "narration.inputs.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))

    with pytest.raises(RuntimeError, match="source hash mismatch for fields: hook, outro"):
        repair._verify_narration_hashes(narration, payload["source_sha256"], sidecar)


@pytest.mark.parametrize("missing", ("hook_text", "story_text"))
def test_legacy_locale_requires_only_hook_and_story_text(missing: str) -> None:
    locale = {"hook_text": "Hook", "story_text": "Story"}
    locale[missing] = ""

    with pytest.raises(RuntimeError, match=rf"missing text fields: {missing}"):
        repair._transcripts_from_legacy_locale(locale)


def test_legacy_locale_neither_requests_nor_requires_intro_or_outro_text() -> None:
    assert repair._transcripts_from_legacy_locale(
        {"hook_text": "Hook", "story_text": "Story"}
    ) == {"hook": "Hook", "story": "Story"}


def test_changed_legacy_database_text_is_rejected_by_incomplete_alignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = tmp_path / "factory"
    _write_legacy_v2_inputs(factory, "en")
    env_file = tmp_path / "legacy.env"
    env_file.write_text("DATABASE_URL=postgresql://example.test/database\n", encoding="utf-8")
    monkeypatch.setattr(
        repair,
        "_legacy_locale_texts",
        lambda *_: {"hook": "Changed hook text", "story": "Changed story text"},
    )
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-only-key")
    transcripts = repair._localized_transcripts(
        factory, "en", slug="music_in_the_new_millennium", legacy_env_file=env_file
    )
    narration = factory / "delivery" / "en" / "narration"

    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {
                "loss": 0.01,
                "words": [{"text": "Changed", "start": 0, "end": 0.2, "loss": 0.01}],
            }

    with pytest.raises(AlignmentError, match="do not exactly cover"):
        build_aligned_captions(
            factory=factory,
            hook_audio=narration / "hook.mp3",
            hook_text=transcripts.hook,
            hook_start=0,
            hook_duration=10,
            story_audio=narration / "story.mp3",
            story_text=transcripts.story,
            story_start=10,
            story_duration=10,
            requester=lambda *_args, **_kwargs: Response(),
        )
