from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.studio.factory.batch_controller import (
    DEFAULT_BATCH_SIZE,
    DocumentarySource,
    parse_args,
    run_batch,
)
from backend.studio.factory.batch_state import BatchItem, BatchLedger, now
from backend.studio.factory.production_contract import SUPPORTED_LANGUAGE_CODES


def _documentary(slug: str, *, valid: bool = True) -> SimpleNamespace:
    languages = tuple(
        SimpleNamespace(
            language_code=language_code,
            story_text="story" if valid else "",
            duration_seconds=30,
            tts_bucket="bucket",
            tts_key="key",
        )
        for language_code in SUPPORTED_LANGUAGE_CODES
    )
    return SimpleNamespace(languages=languages, slug=slug)


def _source(
    source_type: str,
    source_id: int,
    *,
    valid: bool = True,
) -> DocumentarySource:
    slug = f"{source_type}_{source_id}"
    return DocumentarySource(source_type, source_id, slug, _documentary(slug, valid=valid))


def _run(
    tmp_path: Path,
    sources: list[DocumentarySource],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    retry_failed: bool = False,
    creator_calls: list[tuple[str, int]] | None = None,
    factory_calls: list[str] | None = None,
    factory_error: str | None = None,
) -> object:
    root = tmp_path / "productions"
    ledger = tmp_path / "state" / "ledger.json"

    def discovery() -> tuple[DocumentarySource, ...]:
        return tuple(sources)

    def creator(source_type: str, source_id: int) -> Path:
        if creator_calls is not None:
            creator_calls.append((source_type, source_id))
        path = root / f"{source_type}_{source_id}"
        path.mkdir(parents=True, exist_ok=True)
        (path / "manifest.json").write_text("{}", encoding="utf-8")
        return path

    def factory(slug: str) -> object:
        if factory_calls is not None:
            factory_calls.append(slug)
        if factory_error is not None:
            raise RuntimeError(factory_error)
        return object()

    return run_batch(
        batch_size=batch_size,
        dry_run=dry_run,
        retry_failed=retry_failed,
        ledger_path=ledger,
        discovery=discovery,
        manifest_creator=creator,
        documentary_factory=factory,
        production_root=lambda slug: root / slug,
    )


def _ledger(tmp_path: Path) -> BatchLedger:
    return BatchLedger.load(tmp_path / "state" / "ledger.json")


def test_deterministic_cross_source_order_and_default_batch_size(tmp_path: Path) -> None:
    calls: list[str] = []
    creators: list[tuple[str, int]] = []
    sources = [
        _source("artist_story", 2),
        _source("music_docuseries", 8),
        _source("artist_story", 1),
        _source("music_docuseries", 3),
    ]

    result = _run(tmp_path, sources, creator_calls=creators, factory_calls=calls)

    assert result.selected == 4
    assert calls == [
        "music_docuseries_3",
        "music_docuseries_8",
        "artist_story_1",
        "artist_story_2",
    ]
    assert creators == [
        ("music_docuseries", 3),
        ("music_docuseries", 8),
        ("artist_story", 1),
        ("artist_story", 2),
    ]
    assert parse_args([]).batch_size == DEFAULT_BATCH_SIZE


def test_eligibility_filtering_records_preflight_reason(tmp_path: Path) -> None:
    calls: list[str] = []

    _run(tmp_path, [_source("music_docuseries", 1, valid=False)], factory_calls=calls)

    item = _ledger(tmp_path).items[("music_docuseries", 1)]
    assert item.status == "skipped"
    assert item.eligible is False
    assert "story_text" in item.reason
    assert calls == []


def test_batch_size_explicit_zero_and_negative_values(tmp_path: Path) -> None:
    calls: list[str] = []
    sources = [_source("music_docuseries", number) for number in range(1, 4)]

    result = _run(tmp_path, sources, batch_size=1, factory_calls=calls)
    assert result.selected == 1
    assert calls == ["music_docuseries_1"]

    zero_calls: list[str] = []
    zero = _run(tmp_path / "zero", sources, batch_size=0, factory_calls=zero_calls)
    assert zero.selected == 0
    assert zero_calls == []

    with pytest.raises(ValueError, match="non-negative"):
        _run(tmp_path / "negative", sources, batch_size=-1)
    with pytest.raises(SystemExit):
        parse_args(["--batch-size", "-1"])


def test_manifest_creation_only_occurs_for_absent_production_directory(tmp_path: Path) -> None:
    creators: list[tuple[str, int]] = []
    calls: list[str] = []
    root = tmp_path / "productions" / "music_docuseries_1"
    root.mkdir(parents=True)
    (root / "manifest.json").write_text("{}", encoding="utf-8")

    _run(
        tmp_path,
        [_source("music_docuseries", 1)],
        creator_calls=creators,
        factory_calls=calls,
    )

    assert creators == []
    assert calls == ["music_docuseries_1"]


def test_partial_production_directory_is_skipped_without_overwrite(tmp_path: Path) -> None:
    creators: list[tuple[str, int]] = []
    calls: list[str] = []
    root = tmp_path / "productions" / "music_docuseries_1"
    root.mkdir(parents=True)
    marker = root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    result = _run(
        tmp_path,
        [_source("music_docuseries", 1)],
        creator_calls=creators,
        factory_calls=calls,
    )

    item = _ledger(tmp_path).items[("music_docuseries", 1)]
    assert result.skipped == 1
    assert item.status == "skipped"
    assert "without manifest.json" in item.reason
    assert creators == []
    assert calls == []
    assert marker.read_text(encoding="utf-8") == "keep"


def test_one_failure_is_recorded_and_later_item_completes(tmp_path: Path) -> None:
    sources = [_source("music_docuseries", 1), _source("music_docuseries", 2)]
    root = tmp_path / "productions"
    ledger = tmp_path / "state" / "ledger.json"
    calls: list[str] = []

    def factory(slug: str) -> object:
        calls.append(slug)
        if slug.endswith("_1"):
            raise RuntimeError("first failed")
        return object()

    def creator(source_type: str, source_id: int) -> Path:
        path = root / f"{source_type}_{source_id}"
        path.mkdir(parents=True)
        (path / "manifest.json").write_text("{}", encoding="utf-8")
        return path

    result = run_batch(
        ledger_path=ledger,
        discovery=lambda: tuple(sources),
        manifest_creator=creator,
        documentary_factory=factory,
        production_root=lambda slug: root / slug,
    )

    state = BatchLedger.load(ledger)
    assert result.failed == 1
    assert result.completed == 1
    assert calls == ["music_docuseries_1", "music_docuseries_2"]
    assert state.items[("music_docuseries", 1)].status == "failed"
    assert state.items[("music_docuseries", 2)].status == "completed"


def test_completed_items_are_not_rerun_and_failed_items_need_retry(tmp_path: Path) -> None:
    calls: list[str] = []
    source = _source("music_docuseries", 1)
    _run(tmp_path, [source], factory_calls=calls)
    _run(tmp_path, [source], factory_calls=calls)
    assert calls == ["music_docuseries_1"]

    failed_calls: list[str] = []
    _run(tmp_path / "failed", [source], factory_calls=failed_calls, factory_error="failure")
    _run(tmp_path / "failed", [source], factory_calls=failed_calls)
    assert failed_calls == ["music_docuseries_1"]
    _run(tmp_path / "failed", [source], factory_calls=failed_calls, retry_failed=True)
    assert failed_calls == ["music_docuseries_1", "music_docuseries_1"]


def test_interrupted_running_item_returns_to_pending_and_resumes(tmp_path: Path) -> None:
    path = tmp_path / "state" / "ledger.json"
    timestamp = now()
    item = BatchItem(
        source_type="music_docuseries",
        source_id=1,
        slug="music_docuseries_1",
        eligible=True,
        reason="Eligible",
        status="running",
        attempts=1,
        created_at=timestamp,
        started_at=timestamp,
        finished_at=None,
        updated_at=timestamp,
        error=None,
    )
    ledger = BatchLedger(path, {item.identity: item})
    ledger.save()
    calls: list[str] = []

    _run(tmp_path, [_source("music_docuseries", 1)], factory_calls=calls)

    resumed = BatchLedger.load(path).items[item.identity]
    assert calls == ["music_docuseries_1"]
    assert resumed.status == "completed"
    assert resumed.attempts == 2


def test_atomic_ledger_resume_appends_new_discovery_without_losing_prior_state(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    first = _source("music_docuseries", 1)
    second = _source("artist_story", 2)

    _run(tmp_path, [first], factory_calls=calls)
    _run(tmp_path, [first, second], factory_calls=calls)

    state = _ledger(tmp_path)
    assert calls == ["music_docuseries_1", "artist_story_2"]
    assert set(state.items) == {("music_docuseries", 1), ("artist_story", 2)}
    assert state.items[("music_docuseries", 1)].status == "completed"


def test_dry_run_creates_no_directories_ledger_or_factory_work(tmp_path: Path) -> None:
    calls: list[str] = []
    creators: list[tuple[str, int]] = []

    result = _run(
        tmp_path,
        [_source("music_docuseries", 1)],
        dry_run=True,
        creator_calls=creators,
        factory_calls=calls,
    )

    assert result.dry_run is True
    assert result.selected == 1
    assert creators == []
    assert calls == []
    assert not (tmp_path / "productions").exists()
    assert not (tmp_path / "state" / "ledger.json").exists()


def test_concise_error_and_batch_size_apply_only_to_eligible_pending_items(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    sources = [
        _source("music_docuseries", 1, valid=False),
        _source("music_docuseries", 2),
        _source("music_docuseries", 3),
    ]

    _run(tmp_path, sources, batch_size=1, factory_calls=calls)
    assert calls == ["music_docuseries_2"]

    _run(
        tmp_path / "error",
        [_source("music_docuseries", 1)],
        factory_error="broken\n" + "detail " * 200,
    )
    item = _ledger(tmp_path / "error").items[("music_docuseries", 1)]
    assert item.status == "failed"
    assert "\n" not in item.error
    assert len(item.error) <= 400


def test_ledger_json_is_versioned_and_factory_is_the_only_worker(tmp_path: Path) -> None:
    calls: list[str] = []
    _run(tmp_path, [_source("artist_story", 4)], factory_calls=calls)

    payload = json.loads((tmp_path / "state" / "ledger.json").read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert calls == ["artist_story_4"]


def test_absent_discovery_items_remain_preserved_and_never_run(tmp_path: Path) -> None:
    path = tmp_path / "state" / "ledger.json"
    timestamp = now()
    failed = BatchItem(
        "music_docuseries", 1, "music_docuseries_1", True, "failed", "failed",
        1, timestamp, timestamp, timestamp, timestamp, "failure",
    )
    running = BatchItem(
        "artist_story", 2, "artist_story_2", True, "running", "running",
        1, timestamp, timestamp, None, timestamp, None,
    )
    BatchLedger(path, {failed.identity: failed, running.identity: running}).save()
    calls: list[str] = []

    _run(tmp_path, [_source("music_docuseries", 3)], retry_failed=True, factory_calls=calls)

    state = BatchLedger.load(path)
    assert calls == ["music_docuseries_3"]
    assert state.items[failed.identity].status == "failed"
    assert state.items[running.identity].status == "running"


def test_dry_run_prints_only_selected_current_actions_without_mutating_ledger(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "productions"
    partial = root / "music_docuseries_3"
    partial.mkdir(parents=True)
    existing = root / "artist_story_4"
    existing.mkdir(parents=True)
    (existing / "manifest.json").write_text("{}", encoding="utf-8")
    path = tmp_path / "state" / "ledger.json"
    timestamp = now()
    completed = BatchItem(
        "music_docuseries", 1, "music_docuseries_1", True, "Eligible", "completed",
        1, timestamp, timestamp, timestamp, timestamp, None,
    )
    failed = BatchItem(
        "music_docuseries", 2, "music_docuseries_2", True, "Eligible", "failed",
        1, timestamp, timestamp, timestamp, timestamp, "failure",
    )
    BatchLedger(path, {completed.identity: completed, failed.identity: failed}).save()
    before = path.read_bytes()
    calls: list[str] = []

    result = _run(
        tmp_path,
        [
            _source("artist_story", 4),
            _source("music_docuseries", 3),
            _source("music_docuseries", 2),
            _source("music_docuseries", 1),
        ],
        batch_size=1,
        dry_run=True,
        factory_calls=calls,
    )

    output = capsys.readouterr().out
    assert result.selected == 1
    assert "PLAN artist_story:4" in output
    assert "PLAN music_docuseries" not in output
    assert "SKIP music_docuseries:3" in output
    assert calls == []
    assert path.read_bytes() == before
    assert not path.with_name(f"{path.name}.lock").exists()


def test_dry_run_respects_ordering_batch_size_and_retry_failed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run(
        tmp_path,
        [_source("music_docuseries", 2)],
        factory_error="failure",
    )
    capsys.readouterr()

    _run(
        tmp_path,
        [
            _source("artist_story", 1),
            _source("music_docuseries", 2),
            _source("music_docuseries", 3),
        ],
        batch_size=1,
        dry_run=True,
    )
    first = capsys.readouterr().out
    assert "PLAN music_docuseries:3" in first
    assert "PLAN artist_story:1" not in first
    assert "PLAN music_docuseries:2" not in first

    _run(
        tmp_path,
        [
            _source("artist_story", 1),
            _source("music_docuseries", 2),
            _source("music_docuseries", 3),
        ],
        batch_size=1,
        dry_run=True,
        retry_failed=True,
    )
    retried = capsys.readouterr().out
    assert "PLAN music_docuseries:2" in retried
    assert "PLAN music_docuseries:3" not in retried


def test_manual_manifest_repair_requeues_partial_directory_without_creation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "productions" / "music_docuseries_1"
    root.mkdir(parents=True)
    creators: list[tuple[str, int]] = []
    calls: list[str] = []
    _run(
        tmp_path,
        [_source("music_docuseries", 1)],
        creator_calls=creators,
        factory_calls=calls,
    )
    (root / "manifest.json").write_text("{}", encoding="utf-8")

    _run(
        tmp_path,
        [_source("music_docuseries", 1)],
        creator_calls=creators,
        factory_calls=calls,
    )

    assert creators == []
    assert calls == ["music_docuseries_1"]
    assert _ledger(tmp_path).items[("music_docuseries", 1)].status == "completed"


def test_batch_lock_rejects_same_process_reentry(tmp_path: Path) -> None:
    from backend.studio.factory.batch_state import BatchWorkflowLock

    path = tmp_path / "state" / "ledger.json"
    with BatchWorkflowLock(path), pytest.raises(RuntimeError, match="already running"):
        run_batch(
            ledger_path=path,
            discovery=lambda: (_source("music_docuseries", 1),),
            manifest_creator=lambda *_: tmp_path,
            documentary_factory=lambda _: object(),
            production_root=lambda slug: tmp_path / slug,
        )


def test_manifest_creator_must_produce_expected_manifest(tmp_path: Path) -> None:
    path = tmp_path / "state" / "ledger.json"
    calls: list[str] = []

    result = run_batch(
        ledger_path=path,
        discovery=lambda: (_source("music_docuseries", 1),),
        manifest_creator=lambda *_: tmp_path / "unexpected",
        documentary_factory=lambda slug: calls.append(slug),
        production_root=lambda slug: tmp_path / "productions" / slug,
    )

    item = BatchLedger.load(path).items[("music_docuseries", 1)]
    assert result.failed == 1
    assert calls == []
    assert "did not produce expected manifest" in item.error


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_id", True, "source ID"),
        ("source_id", 0, "source ID"),
        ("attempts", True, "attempts"),
        ("attempts", -1, "attempts"),
        ("source_type", "unsupported", "source type"),
        ("slug", "   ", "slug"),
    ],
)
def test_invalid_ledger_identity_fields_are_rejected(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    timestamp = now()
    payload = {
        "version": 1,
        "items": [
            {
                "source_type": "music_docuseries",
                "source_id": 1,
                "slug": "slug",
                "eligible": True,
                "reason": "Eligible",
                "status": "pending",
                "attempts": 0,
                "created_at": timestamp,
                "started_at": None,
                "finished_at": None,
                "updated_at": timestamp,
                "error": None,
            }
        ],
    }
    payload["items"][0][field] = value
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        BatchLedger.load(path)
