from __future__ import annotations

import json
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
    assert desired.startswith(expected)
    assert desired.endswith(original)
    assert present is False


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
