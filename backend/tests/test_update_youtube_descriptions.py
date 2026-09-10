from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.scripts import update_youtube_descriptions as updater


def _state(path: Path, uploads: dict[str, object]) -> Path:
    path.write_text(json.dumps({"schema_version": 2, "uploads": uploads}), encoding="utf-8")
    return path


def _binding(slug: str, language: str, video_id: str) -> updater.VideoBinding:
    return updater.VideoBinding(slug, language, video_id, "test")


def _resource(video_id: str, description: str = "Original\ntext") -> dict[str, object]:
    return {
        "id": video_id,
        "snippet": {"title": "Title", "description": description, "categoryId": "10", "tags": ["one", "two"], "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": "private", "publishAt": "2026-10-01T11:00:00Z", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
        "localizations": {"es": {"title": "Título", "description": "Descripción"}},
    }


class Request:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
    def execute(self) -> dict[str, object]:
        return self.result


class FakeVideos:
    def __init__(self, resources: dict[str, dict[str, object]]) -> None:
        self.resources, self.updates, self.list_calls = resources, [], []
    def list(self, **kwargs: object) -> Request:
        self.list_calls.append(kwargs)
        ids = str(kwargs["id"]).split(",")
        return Request({"items": [self.resources[item] for item in ids if item in self.resources]})
    def update(self, **kwargs: object) -> Request:
        self.updates.append(kwargs)
        return Request({"id": kwargs["body"]["id"]})  # type: ignore[index]


class FakeYoutube:
    def __init__(self, resources: dict[str, dict[str, object]]) -> None:
        self.videos_api = FakeVideos(resources)
    def videos(self) -> FakeVideos:
        return self.videos_api


class QuotaYoutube(FakeYoutube):
    def __init__(self, resources: dict[str, dict[str, object]]) -> None:
        super().__init__(resources)
        original = self.videos_api.update
        def quota_update(**kwargs: object) -> Request:
            original(**kwargs)
            error = RuntimeError("quotaExceeded")
            error.resp = SimpleNamespace(status=403)  # type: ignore[attr-defined]
            raise error
        self.videos_api.update = quota_update  # type: ignore[method-assign]


def _snapshot(path: Path, binding: updater.VideoBinding, resource: dict[str, object]) -> Path:
    records = updater._snapshot_records([binding], {binding.video_id: resource})
    updater._write_json(path, {"schema_version": 1, "records": records})
    return path


@pytest.mark.parametrize("language,expected", [("en", "Explore TopSpot40 free:"), ("es", "Explora TopSpot40 gratis:"), ("pt-BR", "Explore o TopSpot40 gratuitamente:")])
def test_localized_intro_preserves_existing_description_exactly(language: str, expected: str) -> None:
    binding = _binding("alpha", language, "abcdefghijk")
    original = "Original\r\ntext\n\nunchanged"
    desired, present = updater.desired_description(binding, original)
    assert desired.startswith("🎵 " + expected)
    assert desired.endswith(original)
    assert present is False


@pytest.mark.parametrize("language", ["en", "es", "pt-BR"])
def test_all_localized_introductions_contain_approved_music_symbol(language: str) -> None:
    assert updater.INTRODUCTIONS[language].startswith("🎵 ")


@pytest.mark.parametrize("language", ["en", "es", "pt-BR"])
def test_old_non_emoji_pilot_introduction_is_upgraded_without_duplication(language: str) -> None:
    binding = _binding("alpha", language, "abcdefghijk")
    marker = updater.canonical_url(binding.slug, binding.language)
    original_description = "Original description beneath the introduction."
    old_introduction = updater.OLD_INTRODUCTIONS[language].format(url=marker)
    approved_introduction = updater.INTRODUCTIONS[language].format(url=marker)

    desired, present = updater.desired_description(binding, old_introduction + original_description)

    assert present is False
    assert desired == approved_introduction + original_description
    assert desired.count(approved_introduction) == 1


@pytest.mark.parametrize("language", ["en", "es", "pt-BR"])
def test_complete_approved_emoji_introduction_remains_unchanged(language: str) -> None:
    binding = _binding("alpha", language, "abcdefghijk")
    original = updater.INTRODUCTIONS[language].format(url=updater.canonical_url("alpha", language)) + "Legacy description"

    desired, present = updater.desired_description(binding, original)

    assert present is True
    assert desired == original


def test_unrelated_canonical_url_occurrence_is_not_destructively_rewritten() -> None:
    binding = _binding("alpha", "en", "abcdefghijk")
    marker = updater.canonical_url(binding.slug, binding.language)
    original = f"For more details, see {marker}.\n\nOriginal description."

    desired, present = updater.desired_description(binding, original)

    assert present is False
    assert desired == updater.INTRODUCTIONS["en"].format(url=marker) + original


def test_inventory_uses_current_state_and_rejects_conflicting_supplement(tmp_path: Path) -> None:
    state = _state(tmp_path / "state.json", {"alpha|en": {"status": "uploaded", "video_id": "AAAAAAA0001"}})
    assert {item.video_id for item in updater.load_inventory(state)} >= {"AAAAAAA0001", "khdr3ZoFtCY"}
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps([{ "slug": "alpha", "language": "en", "video_id": "staleID0001"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="Conflicting"):
        updater.load_inventory(state, extra)


def test_inventory_rejects_one_video_id_assigned_to_multiple_languages(tmp_path: Path) -> None:
    state = _state(tmp_path / "state.json", {"alpha|en": {"status": "uploaded", "video_id": "AAAAAAA0001"}})
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps([{ "slug": "beta", "language": "es", "video_id": "AAAAAAA0001"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="Ambiguous"):
        updater.load_inventory(state, extra)


def test_current_release_state_does_not_use_stale_historical_replacement(tmp_path: Path) -> None:
    state = _state(tmp_path / "state.json", {"brian_epstein|en": {"status": "uploaded", "video_id": "7dfzUO_wlLI"}})
    ids = {item.video_id for item in updater.load_inventory(state)}
    assert "7dfzUO_wlLI" in ids
    assert "uZahI5-7FsE" not in ids


def test_adele_marker_is_idempotent() -> None:
    binding = _binding("adele", "en", "khdr3ZoFtCY")
    original = updater.INTRODUCTIONS["en"].format(url=updater.canonical_url("adele", "en")) + "Legacy description"
    desired, present = updater.desired_description(binding, original)
    assert present and desired == original


def test_write_json_atomic_retries_transient_replace_permission_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "ledger.json"
    original_replace = updater.os.replace
    attempts = 0

    def transient_permission_error(source: Path, destination: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("temporarily locked")
        original_replace(source, destination)

    monkeypatch.setattr(updater.os, "replace", transient_permission_error)
    monkeypatch.setattr(updater.time, "sleep", lambda _: None)

    updater._write_json_atomic(path, {"status": "saved"})

    assert attempts == 2
    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "saved"}
    assert not path.with_suffix(".json.tmp").exists()


def test_write_json_atomic_preserves_recovery_data_on_permanent_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "ledger.json"
    path.write_text('{"status": "old"}\n', encoding="utf-8")
    attempts = 0

    def permanent_permission_error(source: Path, destination: Path) -> None:
        nonlocal attempts
        attempts += 1
        raise PermissionError("locked")

    monkeypatch.setattr(updater.os, "replace", permanent_permission_error)
    monkeypatch.setattr(updater.time, "sleep", lambda _: None)

    with pytest.raises(PermissionError, match="locked"):
        updater._write_json_atomic(path, {"status": "new"})

    recovery = path.with_suffix(".json.tmp")
    assert attempts == updater.ATOMIC_WRITE_REPLACE_ATTEMPTS
    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "old"}
    assert json.loads(recovery.read_text(encoding="utf-8")) == {"status": "new"}


def test_update_body_preserves_mutable_snippet_and_avoids_status() -> None:
    resource = _resource("abcdefghijk")
    body = updater._update_body(resource, "New description")
    assert body == {"id": "abcdefghijk", "snippet": {"title": "Title", "categoryId": "10", "description": "New description", "tags": ["one", "two"], "defaultLanguage": "en"}}


def test_snapshot_writes_immutable_raw_backup_and_manifest(tmp_path: Path) -> None:
    binding = _binding("alpha", "en", "abcdefghijk")
    resource = _resource(binding.video_id)
    backup = tmp_path / "2026-09-09"
    snapshot = updater.write_snapshot(backup, updater._snapshot_records([binding], {binding.video_id: resource}))
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert snapshot.is_file() and "snapshot.json" in manifest["files"] and (backup / "videos" / "abcdefghijk.json").is_file()
    with pytest.raises(RuntimeError, match="already exists"):
        updater.write_snapshot(backup, [])


def test_preview_is_offline_and_does_not_construct_service_or_ledger(tmp_path: Path) -> None:
    binding = _binding("alpha", "en", "abcdefghijk")
    state = _state(tmp_path / "state.json", {"alpha|en": {"status": "uploaded", "video_id": binding.video_id}})
    snapshot = _snapshot(tmp_path / "snapshot.json", binding, _resource(binding.video_id))
    ledger = tmp_path / "ledger.json"
    called = []
    code = updater.main(["--state", str(state), "--snapshot", str(snapshot), "--ledger", str(ledger), "--slug", "alpha"], service_factory=lambda _: called.append(True))
    assert code == 0 and not called and not ledger.exists()


def test_apply_refuses_snapshot_fingerprint_conflict_and_writes_no_ledger(tmp_path: Path) -> None:
    binding = _binding("alpha", "en", "abcdefghijk")
    state = _state(tmp_path / "state.json", {"alpha|en": {"status": "uploaded", "video_id": binding.video_id}})
    snapshot = _snapshot(tmp_path / "snapshot.json", binding, _resource(binding.video_id, "before"))
    youtube = FakeYoutube({binding.video_id: _resource(binding.video_id, "changed after snapshot")})
    ledger = tmp_path / "ledger.json"
    code = updater.main(["--state", str(state), "--snapshot", str(snapshot), "--ledger", str(ledger), "--client-secrets", "client.json", "--apply", "--confirm-apply-description-update", "--max-updates", "1", "--slug", "alpha"], service_factory=lambda _: youtube)
    assert code == 1 and not youtube.videos_api.updates and not ledger.exists()


@pytest.mark.parametrize("change", ["etag", "thumbnail"])
def test_apply_ignores_etag_or_thumbnail_url_churn(tmp_path: Path, change: str) -> None:
    binding = _binding("alpha", "en", "abcdefghijk")
    state = _state(tmp_path / "state.json", {"alpha|en": {"status": "uploaded", "video_id": binding.video_id}})
    snapshot_resource = _resource(binding.video_id)
    snapshot_resource["etag"] = "original-etag"
    snapshot_resource["snippet"]["thumbnails"] = {"high": {"url": "https://old.example/thumb.jpg", "width": 480}}  # type: ignore[index]
    current = deepcopy(snapshot_resource)
    if change == "etag":
        current["etag"] = "new-etag"
    else:
        current["snippet"]["thumbnails"]["high"]["url"] = "https://new.example/thumb.jpg"  # type: ignore[index]
    snapshot = _snapshot(tmp_path / "snapshot.json", binding, snapshot_resource)
    youtube, ledger = FakeYoutube({binding.video_id: current}), tmp_path / "ledger.json"
    code = updater.main(["--state", str(state), "--snapshot", str(snapshot), "--ledger", str(ledger), "--client-secrets", "client.json", "--apply", "--confirm-apply-description-update", "--max-updates", "1", "--slug", "alpha"], service_factory=lambda _: youtube)
    assert code == 0 and len(youtube.videos_api.updates) == 1 and ledger.exists()


@pytest.mark.parametrize("section,key,value", [("snippet", "title", "Changed title"), ("snippet", "categoryId", "22"), ("snippet", "tags", ["changed"]), ("snippet", "defaultLanguage", "es"), ("snippet", "defaultAudioLanguage", "es"), ("status", "privacyStatus", "public"), ("localizations", "fr", {"title": "Titre", "description": "Description"}), ("recordingDetails", "recordingDate", "2026-02-02")])
def test_apply_conflicts_on_meaningful_stable_metadata_changes(tmp_path: Path, section: str, key: str, value: object) -> None:
    binding = _binding("alpha", "en", "abcdefghijk")
    state = _state(tmp_path / "state.json", {"alpha|en": {"status": "uploaded", "video_id": binding.video_id}})
    snapshot_resource = _resource(binding.video_id)
    snapshot_resource["recordingDetails"] = {"recordingDate": "2026-01-01"}
    current = deepcopy(snapshot_resource)
    current[section][key] = value  # type: ignore[index]
    snapshot = _snapshot(tmp_path / "snapshot.json", binding, snapshot_resource)
    youtube, ledger = FakeYoutube({binding.video_id: current}), tmp_path / "ledger.json"
    code = updater.main(["--state", str(state), "--snapshot", str(snapshot), "--ledger", str(ledger), "--client-secrets", "client.json", "--apply", "--confirm-apply-description-update", "--max-updates", "1", "--slug", "alpha"], service_factory=lambda _: youtube)
    assert code == 1 and not youtube.videos_api.updates and not ledger.exists()


def test_stable_resource_fingerprint_does_not_mutate_resource() -> None:
    resource = _resource("abcdefghijk")
    resource["snippet"]["thumbnails"] = {"high": {"url": "https://example.test/thumb.jpg"}}  # type: ignore[index]
    original = deepcopy(resource)
    updater.stable_resource_fingerprint(resource)
    assert resource == original


def test_apply_uses_legacy_snapshot_with_only_raw_resource_and_fingerprint(tmp_path: Path) -> None:
    binding = _binding("alpha", "en", "abcdefghijk")
    state = _state(tmp_path / "state.json", {"alpha|en": {"status": "uploaded", "video_id": binding.video_id}})
    resource = _resource(binding.video_id)
    records = updater._snapshot_records([binding], {binding.video_id: resource})
    records[0].pop("stable_fingerprint")
    snapshot = tmp_path / "legacy-snapshot.json"
    updater._write_json(snapshot, {"schema_version": 1, "records": records})
    current = deepcopy(resource)
    current["etag"] = "changed-etag"
    youtube, ledger = FakeYoutube({binding.video_id: current}), tmp_path / "ledger.json"
    code = updater.main(["--state", str(state), "--snapshot", str(snapshot), "--ledger", str(ledger), "--client-secrets", "client.json", "--apply", "--confirm-apply-description-update", "--max-updates", "1", "--slug", "alpha"], service_factory=lambda _: youtube)
    assert code == 0 and len(youtube.videos_api.updates) == 1 and ledger.exists()


def test_existing_2026_09_10_snapshot_uses_derived_stable_fingerprint() -> None:
    snapshot = Path(__file__).parents[1] / "studio" / "work" / "youtube_description_backups" / "2026-09-10" / "snapshot.json"
    record = updater.load_snapshot(snapshot)[0]
    binding = _binding(record["slug"], record["language"], record["video_id"])
    plan = updater._plan(binding, record)
    assert "stable_fingerprint" not in record
    assert plan["snapshot_fingerprint"] == updater.stable_resource_fingerprint(record["resource"])


def test_apply_records_atomic_ledger_and_honors_limit(tmp_path: Path) -> None:
    uploads = {"alpha|en": {"status": "uploaded", "video_id": "abcdefghijk"}, "beta|es": {"status": "uploaded", "video_id": "lmnopqrstuv"}}
    state = _state(tmp_path / "state.json", uploads)
    bindings = [_binding("alpha", "en", "abcdefghijk"), _binding("beta", "es", "lmnopqrstuv")]
    resources = {item.video_id: _resource(item.video_id) for item in bindings}
    records = updater._snapshot_records(bindings, resources)
    snapshot = tmp_path / "snapshot.json"; updater._write_json(snapshot, {"schema_version": 1, "records": records})
    youtube, ledger = FakeYoutube(resources), tmp_path / "ledger.json"
    code = updater.main(["--state", str(state), "--snapshot", str(snapshot), "--ledger", str(ledger), "--client-secrets", "client.json", "--apply", "--confirm-apply-description-update", "--max-updates", "1", "--slug", "alpha", "--slug", "beta"], service_factory=lambda _: youtube)
    saved = json.loads(ledger.read_text(encoding="utf-8"))
    assert code == 0 and len(youtube.videos_api.updates) == 1 and len(saved["applied"]) == 1
    assert youtube.videos_api.updates[0]["part"] == "snippet"


def test_apply_stops_on_quota_without_a_success_ledger_entry(tmp_path: Path) -> None:
    binding = _binding("alpha", "en", "abcdefghijk")
    state = _state(tmp_path / "state.json", {"alpha|en": {"status": "uploaded", "video_id": binding.video_id}})
    resource = _resource(binding.video_id)
    snapshot = _snapshot(tmp_path / "snapshot.json", binding, resource)
    ledger = tmp_path / "ledger.json"
    code = updater.main(["--state", str(state), "--snapshot", str(snapshot), "--ledger", str(ledger), "--client-secrets", "client.json", "--apply", "--confirm-apply-description-update", "--max-updates", "1", "--slug", "alpha"], service_factory=lambda _: QuotaYoutube({binding.video_id: resource}))
    assert code == 1 and not ledger.exists()


def test_apply_validation_requires_explicit_confirmation_and_cap(tmp_path: Path) -> None:
    state = _state(tmp_path / "state.json", {"alpha|en": {"status": "uploaded", "video_id": "abcdefghijk"}})
    snapshot = _snapshot(tmp_path / "snapshot.json", _binding("alpha", "en", "abcdefghijk"), _resource("abcdefghijk"))
    with pytest.raises(SystemExit):
        updater.main(["--state", str(state), "--snapshot", str(snapshot), "--client-secrets", "client.json", "--apply"])
    with pytest.raises(SystemExit):
        updater.main(["--state", str(state), "--snapshot", str(snapshot), "--client-secrets", "client.json", "--apply", "--confirm-apply-description-update", "--max-updates", "51"])
