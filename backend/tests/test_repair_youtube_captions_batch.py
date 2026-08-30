from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.scripts import repair_youtube_captions_batch as batch
from backend.studio.studio_config import (
    HOOK_PAUSE_SECONDS,
    INTRO_PAUSE_SECONDS,
    OUTRO_PAUSE_SECONDS,
)
from backend.studio.youtube.caption_alignment import clean_transcript
from backend.studio.youtube.publishing_package import (
    LEGACY_V2_FINAL_TAIL_SECONDS,
    build_aligned_captions,
    documentary_timing,
)


class HttpError(Exception):
    """Mock shaped like googleapiclient.errors.HttpError; it never makes a call."""

    def __init__(self, status: int, content: bytes) -> None:
        super().__init__("unsafe request URL and response body must not be reported")
        self.resp = SimpleNamespace(status=status)
        self.content = content


HttpError.__module__ = "googleapiclient.errors"


def _state(path: Path, uploads: dict[str, object]) -> Path:
    path.write_text(json.dumps({"schema_version": 2, "uploads": uploads}), encoding="utf-8")
    return path


def _uploaded(video_id: str = "video") -> dict[str, object]:
    return {"status": "uploaded", "video_id": video_id, "captions_uploaded": True}


def _run(tmp_path: Path, uploads: dict[str, object], extra: list[str] | None = None, engine=None, binding=None) -> tuple[int, list[list[str]], dict[str, object]]:
    state = _state(tmp_path / "state.json", uploads)
    report = tmp_path / "report.json"
    calls: list[list[str]] = []
    if engine is None:
        def engine(argv: list[str] | None) -> int:
            calls.append(list(argv or []))
            return 0
    if binding is None and "--apply" in (extra or []):
        binding = lambda item, _args: f"test-binding:{item.slug}:{item.language}:{item.video_id}"
    code = batch.main([
        "--factory-work-root", str(tmp_path / "factories"), "--state", str(state), "--report", str(report), "--ledger", str(tmp_path / "youtube_caption_repair_ledger.json"), *(extra or [])
    ], repair_main=engine, binding_for_item=binding)
    return code, calls, json.loads(report.read_text(encoding="utf-8"))


def _write_sidecar(root: Path, slug: str, language: str, version: int) -> None:
    path = root / slug / "factory" / "delivery" / language
    path.mkdir(parents=True)
    (path / "narration.inputs.json").write_text(json.dumps({"version": version}), encoding="utf-8")


def test_mixed_v2_v3_catalog_forwards_legacy_env_only_to_v2(tmp_path: Path) -> None:
    factories = tmp_path / "factories"
    _write_sidecar(factories, "alpha", "en", 2)
    _write_sidecar(factories, "beta", "es", 3)
    code, calls, report = _run(tmp_path, {"beta|es": _uploaded("b"), "alpha|en": _uploaded("a")}, ["--legacy-env-file", str(tmp_path / "legacy.env")])
    assert code == 0
    assert [call[0] for call in calls] == ["--slug=alpha", "--slug=beta"]
    assert f"--legacy-env-file={tmp_path / 'legacy.env'}" in calls[0]
    assert not any(call.startswith("--legacy-env-file=") for call in calls[1])
    assert [item["status"] for item in report["items"]] == ["ready", "ready"]


def test_v2_requires_legacy_env_but_v3_does_not(tmp_path: Path) -> None:
    factories = tmp_path / "factories"
    _write_sidecar(factories, "alpha", "en", 2)
    _write_sidecar(factories, "beta", "es", 3)
    code, calls, report = _run(tmp_path, {"alpha|en": _uploaded(), "beta|es": _uploaded()})
    assert code == 1
    assert [call[0] for call in calls] == ["--slug=beta"]
    assert report["items"][0]["error_message"].startswith("Version-2 narration recovery requires")


def test_missing_factory_is_reported_and_batch_continues(tmp_path: Path) -> None:
    seen: list[list[str]] = []
    def engine(argv: list[str] | None) -> int:
        seen.append(list(argv or []))
        if "--slug=broken" in argv:
            raise FileNotFoundError("missing factory")
        return 0
    code, _, report = _run(tmp_path, {"broken|en": _uploaded(), "good|es": _uploaded()}, engine=engine)
    assert code == 1
    assert [call[0] for call in seen] == ["--slug=broken", "--slug=good"]
    assert [(item["slug"], item["status"]) for item in report["items"]] == [("broken", "failed"), ("good", "ready")]


def test_generic_rendered_missing_cache_message_is_not_classified(tmp_path: Path) -> None:
    def engine(_: list[str] | None) -> int:
        raise RuntimeError("A validated alignment cache is required for caption repair; ElevenLabs is not called.")
    code, _, report = _run(tmp_path, {"alpha|en": _uploaded()}, engine=engine)
    assert code == 1
    assert report["items"][0]["status"] == "failed"


def _write_cache_only_factory(root: Path, slug: str, language: str) -> Path:
    """Create the real repair inputs with deliberately absent alignment cache."""
    factory = root / slug / "factory"
    narration = factory / "delivery" / language / "narration"
    narration.mkdir(parents=True)
    hashes: dict[str, str] = {}
    for part in ("hook", "intro", "story", "outro"):
        audio = narration / f"{part}.mp3"
        audio.write_bytes(f"{slug}:{language}:{part}".encode())
        hashes[part] = hashlib.sha256(audio.read_bytes()).hexdigest()
    (factory / "delivery" / language / "narration.inputs.json").write_text(
        json.dumps(
            {
                "version": 3,
                "source_sha256": hashes,
                "transcripts": {"hook": "An authoritative hook.", "story": "An authoritative story."},
            }
        ),
        encoding="utf-8",
    )
    opening = factory / "shared" / "opening.mp4"
    opening.parent.mkdir(parents=True)
    opening.write_bytes(b"opening")
    (factory / "delivery" / language / "documentary.mp4").write_bytes(b"documentary")
    return factory


def test_real_cache_only_audit_maps_typed_missing_cache_to_alignment_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise batch -> repair CLI -> alignment cache lookup without network access."""
    factories = tmp_path / "factories"
    _write_cache_only_factory(factories, "ahmet_ertegun", "en")

    def duration(path: Path) -> float:
        if path.name == "opening.mp4":
            return 3.0
        if path.name == "documentary.mp4":
            return 50.0
        return 10.0

    monkeypatch.setattr("backend.studio.youtube.publishing_package.media_duration", duration)
    monkeypatch.setattr(
        "backend.studio.youtube.caption_alignment.requests.post",
        lambda *_args, **_kwargs: pytest.fail("cache-only audit must not make an external request"),
    )
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    code, _, report = _run(
        tmp_path,
        {"ahmet_ertegun|en": _uploaded("9XmW9xz5erQ")},
        engine=batch.repair.main,
    )
    assert code == 0
    assert report["items"] == [
        {
            "slug": "ahmet_ertegun",
            "language": "en",
            "video_id": "9XmW9xz5erQ",
            "status": "alignment_required",
            "error_category": "alignment_cache_missing",
            "error_message": "A validated alignment cache is required for caption repair; ElevenLabs is not called.",
        }
    ]


def test_alignment_required_accepts_a_typed_exception_only_in_its_chain(tmp_path: Path) -> None:
    from backend.studio.youtube.caption_alignment import AlignmentCacheMissing

    def engine(_: list[str] | None) -> int:
        try:
            raise AlignmentCacheMissing("cache miss")
        except AlignmentCacheMissing as exc:
            raise RuntimeError("wrapped repair failure") from exc

    code, _, report = _run(tmp_path, {"alpha|en": _uploaded()}, engine=engine)
    assert code == 0
    assert report["items"][0]["status"] == "alignment_required"
    assert report["items"][0]["error_category"] == "alignment_cache_missing"


@pytest.mark.parametrize("extra", [["--align", "--env-file", "alignment.env"], ["--apply", "--client-secrets", "client.json", "--confirm-apply-existing-captions"]])
def test_missing_cache_remains_failed_outside_audit(tmp_path: Path, extra: list[str]) -> None:
    from backend.studio.youtube.caption_alignment import AlignmentCacheMissing

    def engine(_: list[str] | None) -> int:
        raise AlignmentCacheMissing(
            "A validated alignment cache is required for caption repair; ElevenLabs is not called."
        )
    code, _, report = _run(tmp_path, {"alpha|en": _uploaded()}, extra, engine)
    assert code == 1
    assert report["items"][0]["status"] == "failed"


def test_alignment_is_only_permitted_with_align_and_youtube_only_with_confirmed_apply(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _run(tmp_path, {"alpha|en": _uploaded()}, ["--env-file", "alignment.env"])
    with pytest.raises(SystemExit):
        _run(tmp_path, {"alpha|en": _uploaded()}, ["--apply", "--client-secrets", "client.json"])
    _, align_calls, _ = _run(tmp_path, {"alpha|en": _uploaded()}, ["--align", "--env-file", "alignment.env"])
    _, apply_calls, _ = _run(tmp_path, {"alpha|en": _uploaded()}, ["--apply", "--client-secrets", "client.json", "--confirm-apply-existing-captions"])
    assert "--align" in align_calls[0] and "--apply" not in align_calls[0]
    assert "--apply" in apply_calls[0] and "--align" not in apply_calls[0]
    assert any(call.startswith("--env-file=") for call in align_calls[0])
    assert any(call.startswith("--client-secrets=") for call in apply_calls[0])


def test_uses_atomic_exact_state_video_id_and_ignores_caption_uploaded_claim(tmp_path: Path) -> None:
    _, calls, _ = _run(tmp_path, {"alpha|pt-BR": _uploaded("-exact-video-id")})
    call = calls[0]
    assert "--video-id=-exact-video-id" in call


def test_delegated_system_exit_is_reported_and_batch_continues(tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def engine(argv: list[str] | None) -> int:
        seen.append(list(argv or []))
        if "--slug=broken" in (argv or []):
            raise SystemExit(2)
        return 0
    code, _, report = _run(tmp_path, {"broken|en": _uploaded(), "good|es": _uploaded()}, engine=engine)
    assert code == 1
    assert ["--slug=broken" in call for call in seen] == [True, False]
    assert [(item["slug"], item["status"]) for item in report["items"]] == [("broken", "failed"), ("good", "ready")]


def test_invalid_alignment_cache_remains_failed(tmp_path: Path) -> None:
    from backend.studio.youtube.caption_alignment import AlignmentError

    def engine(_: list[str] | None) -> int:
        raise AlignmentError("Cached alignment is invalid: local cache entry")
    code, _, report = _run(tmp_path, {"alpha|en": _uploaded()}, engine=engine)
    assert code == 1
    assert report["items"][0]["status"] == "failed"
    assert report["items"][0]["error_category"] == "alignment_cache_invalid"


def test_filters_max_items_and_deterministic_order(tmp_path: Path) -> None:
    uploads = {"zeta|es": _uploaded(), "alpha|pt-BR": _uploaded(), "alpha|en": _uploaded(), "draft|en": {"status": "draft", "video_id": "no"}}
    _, calls, report = _run(tmp_path, uploads, ["--slug", "alpha", "--language", "en", "--max-items", "1"])
    assert [call[:2] for call in calls] == [["--slug=alpha", "--language=en"]]
    assert report["summary"] == {"ready": 1}
    _, calls, _ = _run(tmp_path, uploads)
    assert [tuple(call[:2]) for call in calls] == [
        ("--slug=alpha", "--language=en"),
        ("--slug=alpha", "--language=pt-BR"),
        ("--slug=zeta", "--language=es"),
    ]


def test_report_is_atomic_redacted_and_reruns_are_idempotent(tmp_path: Path) -> None:
    def engine(_: list[str] | None) -> int:
        raise RuntimeError("DATABASE_URL=postgresql://user:password@example.test/database transcript only here")
    for _ in range(2):
        code, _, report = _run(tmp_path, {"alpha|en": _uploaded()}, engine=engine)
        assert code == 1
        assert "password" not in json.dumps(report)
        assert "transcript only here" not in json.dumps(report)
        assert not (tmp_path / "report.json.tmp").exists()
        assert report["items"][0]["status"] == "failed"


@pytest.mark.parametrize(
    ("status", "reason", "category"),
    [
        (403, "quotaExceeded", "youtube_quota_exceeded"),
        (429, "rateLimitExceeded", "youtube_rate_limit_exceeded"),
        (401, "authError", "youtube_auth_error"),
        (403, "forbidden", "youtube_permission_denied"),
        (400, "invalidValue", "youtube_invalid_request"),
        (500, "backendError", "youtube_http_failure"),
    ],
)
def test_google_http_failures_are_classified_safely_and_batch_continues(
    tmp_path: Path, status: int, reason: str, category: str
) -> None:
    """Use a mock HttpError only; no YouTube, ElevenLabs, or database call occurs."""
    unsafe = "https://youtube.example/private?access_token=secret caption text transcript text"
    content = json.dumps(
        {"error": {"errors": [{"reason": reason, "message": unsafe}], "message": unsafe}}
    ).encode()
    seen: list[list[str]] = []

    def engine(argv: list[str] | None) -> int:
        seen.append(list(argv or []))
        if "--slug=broken" in (argv or []):
            try:
                raise HttpError(status, content)
            except HttpError as exc:
                # This mirrors a future one-video wrapper while retaining its cause.
                raise RuntimeError("local wrapper") from exc
        return 0

    code, _, report = _run(
        tmp_path,
        {"broken|en": _uploaded(), "good|es": _uploaded()},
        ["--apply", "--client-secrets", "client.json", "--confirm-apply-existing-captions"],
        engine,
    )
    assert code == 1
    expected_calls = ["--slug=broken"] if reason == "quotaExceeded" else ["--slug=broken", "--slug=good"]
    assert [call[0] for call in seen] == expected_calls
    failed = report["items"][0]
    assert failed["error_category"] == category
    assert failed["error_message"] == f"YouTube captions API request failed with HTTP {status}" + (
        f" ({reason})." if reason != "backendError" else "."
    )
    serialized = json.dumps(report)
    assert unsafe not in serialized
    assert "secret" not in serialized


def test_audit_never_authorizes_elevenlabs_or_youtube_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.studio.youtube.uploader.upload_video", lambda *_: pytest.fail("video upload must not run"))
    monkeypatch.setattr("backend.studio.youtube.uploader.set_thumbnail", lambda *_: pytest.fail("metadata must not run"))
    monkeypatch.setattr("backend.studio.youtube.uploader.add_to_playlist", lambda *_: pytest.fail("playlist mutation must not run"))
    def engine(argv: list[str] | None) -> int:
        assert "--align" not in (argv or [])
        assert "--apply" not in (argv or [])
        return 0
    code, _, report = _run(tmp_path, {"alpha|en": _uploaded()}, engine=engine)
    assert code == 0
    assert report["items"][0]["status"] == "ready"


def test_apply_ledger_skips_only_an_exact_successful_binding_and_records_each_success(tmp_path: Path) -> None:
    seen: list[list[str]] = []
    def engine(argv: list[str] | None) -> int:
        seen.append(list(argv or [])); return 0
    binding = lambda item, _args: f"binding:{item.video_id}"
    extra = ["--apply", "--client-secrets", "client.json", "--confirm-apply-existing-captions"]
    code, _, report = _run(tmp_path, {"alpha|en": _uploaded("one")}, extra, engine, binding)
    assert code == 0 and report["items"][0]["status"] == "applied"
    code, calls, report = _run(tmp_path, {"alpha|en": _uploaded("one")}, extra, engine, binding)
    assert code == 0 and not calls and report["items"][0]["status"] == "already_applied"
    code, calls, report = _run(tmp_path, {"alpha|en": _uploaded("two")}, extra, engine, binding)
    assert code == 0 and len(seen) == 2 and report["items"][0]["status"] == "applied"
    changed_binding = lambda item, _args: f"binding:changed-vtt-audio-transcript-alignment:{item.video_id}"
    code, _, report = _run(tmp_path, {"alpha|en": _uploaded("two")}, extra, engine, changed_binding)
    assert code == 0 and len(seen) == 3 and report["items"][0]["status"] == "applied"
    ledger = json.loads((tmp_path / "youtube_caption_repair_ledger.json").read_text(encoding="utf-8"))
    assert ledger["applied"]["alpha|en"]["video_id"] == "two"


def test_max_updates_counts_youtube_calls_not_skipped_items(tmp_path: Path) -> None:
    extra = ["--apply", "--client-secrets", "client.json", "--confirm-apply-existing-captions", "--max-updates", "1"]
    binding = lambda item, _args: f"binding:{item.slug}"
    # Seed alpha: it must not consume the one permitted update.
    _run(tmp_path, {"alpha|en": _uploaded()}, extra[:-2], lambda _: 0, binding)
    seen: list[list[str]] = []
    def engine(argv: list[str] | None) -> int:
        seen.append(list(argv or [])); return 0
    code, _, report = _run(tmp_path, {"alpha|en": _uploaded(), "beta|es": _uploaded(), "gamma|pt-BR": _uploaded()}, extra, engine, binding)
    assert code == 0 and len(seen) == 1
    assert [item["status"] for item in report["items"]] == ["already_applied", "applied", "ready"]


def test_quota_exceeded_stops_calls_and_never_records_failure(tmp_path: Path) -> None:
    quota = json.dumps({"error": {"errors": [{"reason": "quotaExceeded"}]}}).encode()
    seen: list[list[str]] = []
    def engine(argv: list[str] | None) -> int:
        seen.append(list(argv or []))
        raise HttpError(403, quota)
    extra = ["--apply", "--client-secrets", "client.json", "--confirm-apply-existing-captions", "--max-updates", "1"]
    code, calls, report = _run(tmp_path, {"alpha|en": _uploaded(), "beta|es": _uploaded()}, extra, engine, lambda item, _: item.slug)
    assert code == 1 and len(seen) == 1 and not calls
    assert report["items"] == [{"slug": "alpha", "language": "en", "video_id": "video", "status": "quota_exceeded", "error_category": "youtube_quota_exceeded", "error_message": "YouTube captions API request failed with HTTP 403 (quotaExceeded)."}]
    assert not (tmp_path / "youtube_caption_repair_ledger.json").exists()


def test_offline_bootstrap_requires_confirmation_and_only_records_allowlisted_tracks(tmp_path: Path) -> None:
    assert len(batch.BOOTSTRAP_APPLIED) == 20
    with pytest.raises(SystemExit):
        _run(tmp_path, {"ahmet_ertegun|en": _uploaded()}, ["--bootstrap-applied"])
    code, calls, report = _run(
        tmp_path, {"ahmet_ertegun|en": _uploaded(), "not_confirmed|es": _uploaded()},
        ["--bootstrap-applied", "--confirm-bootstrap-applied"],
        lambda _: pytest.fail("bootstrap must not call repair/YouTube"), lambda item, _: "offline:" + item.slug,
    )
    assert code == 1 and not calls
    assert [item["status"] for item in report["items"]] == ["bootstrapped", "failed"]
    ledger = json.loads((tmp_path / "youtube_caption_repair_ledger.json").read_text(encoding="utf-8"))
    assert set(ledger["applied"]) == {"ahmet_ertegun|en"}


def test_real_v2_bootstrap_records_once_and_cache_only_audit_recognizes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise batch -> offline fingerprint -> real cache/VTT validation with no credentials."""
    slug, language, video_id = "music_in_the_new_millennium", "en", "tTiah5ncQsw"
    factories = tmp_path / "factories"
    factory = _write_cache_only_factory(factories, slug, language)
    sidecar = factory / "delivery" / language / "narration.inputs.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload.pop("transcripts")
    payload["version"] = 2
    sidecar.write_text(json.dumps(payload), encoding="utf-8")

    narration = factory / "delivery" / language / "narration"
    transcripts = {"hook": "The legacy hook.", "story": "The legacy story."}
    cache = factory / "cache" / "caption_alignment"
    cache.mkdir(parents=True)
    for part, text in transcripts.items():
        words = [
            {"text": word, "start": index * 2.0, "end": index * 2.0 + 1.0, "loss": 0.0}
            for index, word in enumerate(text.split())
        ]
        key = batch.repair._alignment_cache_key(narration / f"{part}.mp3", clean_transcript(text))
        (cache / f"{key}.json").write_text(json.dumps({"loss": 0.0, "words": words}), encoding="utf-8")

    timing_calls: list[Path] = []
    def duration(path: Path) -> float:
        timing_calls.append(path)
        if path.name == "opening.mp4":
            return 3.0
        if path.name == "documentary.mp4":
            return 3.0 + 40.0 + HOOK_PAUSE_SECONDS + INTRO_PAUSE_SECONDS + OUTRO_PAUSE_SECONDS + LEGACY_V2_FINAL_TAIL_SECONDS
        return 10.0

    monkeypatch.setattr("backend.studio.youtube.publishing_package.media_duration", duration)
    monkeypatch.setattr("backend.studio.youtube.caption_alignment.requests.post", lambda *_a, **_k: pytest.fail("no ElevenLabs call"))
    monkeypatch.setattr("backend.studio.youtube.uploader.upload_captions", lambda *_a, **_k: pytest.fail("no YouTube call"))
    timing = documentary_timing(factory, language=language, probe=duration)
    vtt = build_aligned_captions(
        factory=factory, hook_audio=narration / "hook.mp3", hook_text=transcripts["hook"],
        hook_start=timing.hook_start, hook_duration=timing.durations["hook"],
        story_audio=narration / "story.mp3", story_text=transcripts["story"],
        story_start=timing.story_start, story_duration=timing.durations["story"],
        requester=batch.repair._cached_alignment_only,
    )
    output = factory / "publishing_repair" / language / "captions.vtt"
    output.parent.mkdir(parents=True)
    output.write_text(vtt, encoding="utf-8")
    timing_calls.clear()

    state = _state(tmp_path / "state.json", {f"{slug}|{language}": _uploaded(video_id)})
    report, ledger = tmp_path / "report.json", tmp_path / "ledger.json"
    args = ["--factory-work-root", str(factories), "--state", str(state), "--report", str(report), "--ledger", str(ledger), "--slug", slug, "--language", language]
    assert batch.main([*args, "--bootstrap-applied", "--confirm-bootstrap-applied"], repair_main=batch.repair.main) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["items"][0]["status"] == "bootstrapped"
    saved = json.loads(ledger.read_text(encoding="utf-8"))["applied"]
    assert list(saved) == [f"{slug}|{language}"]
    assert len(timing_calls) == 6  # one documentary_timing invocation, not two

    assert batch.main(args, repair_main=batch.repair.main) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["items"][0]["status"] == "already_applied"
