from __future__ import annotations

import struct
import sys
import types
import zlib
from pathlib import Path

import pytest

from backend.studio.historical.models import HistoricalImageCandidate
from backend.studio.stations.select_historical_visuals import LiveImageTooLargeError, retrieve_live_bytes
from backend.studio.visuals import historical_visual_package
from backend.studio.visuals.historical_visual_package import BoundedSearchSettings, HistoricalCache, HistoricalVisualPackageBuilder, license_status


def image_bytes(color: tuple[int, int, int] = (80, 120, 180)) -> bytes:
    width, height = 8, 8
    raw = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def candidate(number: int, **overrides: object) -> HistoricalImageCandidate:
    values: dict[str, object] = {"provider": "wikimedia_commons", "title": f"Test Artist concert {number}", "description": "Test Artist live concert in 1970", "original_url": f"https://upload.wikimedia.org/test-{number}.png", "page_url": f"https://commons.wikimedia.org/wiki/File:test-{number}.png", "width": 1280, "height": 720, "mime_type": "image/png", "creator": "Photographer", "credit": "Photographer / Commons", "license_name": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/", "usage_terms": "CC BY 4.0"}
    values.update(overrides)
    return HistoricalImageCandidate(**values)  # type: ignore[arg-type]


class FakeProvider:
    provider_name = "wikimedia_commons"
    def __init__(self, results: list[HistoricalImageCandidate]) -> None: self.results, self.calls = results, []
    def search(self, query: str, *, limit: int = 10) -> list[HistoricalImageCandidate]:
        self.calls.append((query, limit))
        start = (len(self.calls) - 1) * limit
        return self.results[start:start + limit]


def storyboard(scene_number: int = 2) -> dict[str, object]:
    return {"production_slug": "local_documentary", "title": "Test Artist", "scenes": [{"scene_number": scene_number, "visual_shots": [{"shot_number": 1, "start_seconds": 20.0, "visual_intent": "Test Artist concert", "historical_search": "Test Artist concert 1970", "historical_plan": {"search_queries": ["one", "two", "three", "four"]}}]}]}


def test_defaults_are_a_bounded_funnel() -> None:
    settings = BoundedSearchSettings()
    assert (settings.max_queries_per_shot, settings.max_metadata_candidates_per_query, settings.max_unique_metadata_candidates_per_shot, settings.max_downloaded_finalists_per_shot) == (3, 8, 16, 2)


def test_metadata_search_and_downloads_are_capped_and_cached(tmp_path: Path) -> None:
    provider, retrieved = FakeProvider([candidate(index) for index in range(20)]), []
    def retrieve(item: HistoricalImageCandidate) -> bytes: retrieved.append(item.original_url); return image_bytes()
    cache = HistoricalCache(tmp_path / "cache")
    first = HistoricalVisualPackageBuilder(providers=[provider], retriever=retrieve, cache=cache).build(storyboard())
    assert len(provider.calls) == 3 and {limit for _, limit in provider.calls} == {8}
    assert first["summary"]["metadata_candidates"] == 16 and len(retrieved) == 2
    second = HistoricalVisualPackageBuilder(providers=[provider], retriever=retrieve, cache=cache).build(storyboard())
    assert len(provider.calls) == 3 and len(retrieved) == 2
    assert second["summary"]["provider_cache_hits"] == 3 and second["summary"]["retrieval_cache_hits"] == 2


def test_license_policy_rejects_nc_nd_and_requires_complete_attribution() -> None:
    assert license_status(candidate(1, license_name="CC BY-NC 4.0"))[0] == "reject"
    assert license_status(candidate(1, license_name="CC BY-ND 4.0"))[0] == "reject"
    assert license_status(candidate(1, credit="")) == ("review", "attribution_incomplete")
    assert license_status(candidate(1, license_name="Public domain", usage_terms="Public domain"))[0] == "eligible"


def test_public_domain_without_license_url_uses_generated_fallback(
    tmp_path: Path,
) -> None:
    incomplete = candidate(
        1,
        license_name="Public domain",
        usage_terms="Public domain",
        license_url="",
    )

    assert license_status(incomplete) == (
        "review",
        "license_provenance_incomplete",
    )

    package = HistoricalVisualPackageBuilder(
        providers=[FakeProvider([incomplete])],
        retriever=lambda _: image_bytes(),
        cache=HistoricalCache(tmp_path / "cache"),
    ).build(storyboard())

    assert package["shots"][0]["decision"]["state"] == (
        "generated_fallback_eligible"
    )
    assert package["summary"]["auto_approved"] == 0


def test_unreviewed_live_source_is_automatically_approved(tmp_path: Path) -> None:
    package = HistoricalVisualPackageBuilder(providers=[FakeProvider([candidate(1)])], retriever=lambda _: image_bytes(), cache=HistoricalCache(tmp_path / "cache")).build(storyboard())
    assert package["shots"][0]["decision"]["state"] == "approved_historical"
    assert package["shots"][0]["decision"]["reason_codes"] == ["deterministic_safety_gates", "high_confidence"]
    assert package["shots"][0]["candidates"][0]["disposition"] == "approved"
    assert package["summary"]["auto_approved"] == 1
    assert package["summary"]["review_queued"] == 0
    assert package["shared_for_languages"] == ["en", "es", "pt-BR"]

def test_provider_failure_uses_generated_fallback(tmp_path: Path) -> None:
    class FailingProvider:
        provider_name = "wikimedia_commons"

        def search(self, query: str, *, limit: int = 10):
            raise RuntimeError("provider unavailable")

    package = HistoricalVisualPackageBuilder(
        providers=[FailingProvider()],
        retriever=lambda _: image_bytes(),
        cache=HistoricalCache(tmp_path / "cache"),
    ).build(storyboard())

    assert package["shots"][0]["decision"]["state"] == "generated_fallback_eligible"
    assert package["shots"][0]["decision"]["reason_codes"] == ["provider_failure"]
    assert package["summary"]["generated_fallback_eligible"] == 1
    assert package["summary"]["review_queued"] == 0


def test_high_confidence_non_hook_candidate_is_auto_approved(tmp_path: Path) -> None:
    content = image_bytes()
    package = HistoricalVisualPackageBuilder(providers=[FakeProvider([candidate(1)])], retriever=lambda _: content, cache=HistoricalCache(tmp_path / "cache")).build(storyboard())
    assert package["shots"][0]["decision"]["state"] == "approved_historical"

def test_first_scene_is_hook_and_metadata_overlay_rejects_before_download(tmp_path: Path) -> None:
    calls = 0
    def retrieve(_: HistoricalImageCandidate) -> bytes:
        nonlocal calls; calls += 1; return image_bytes()
    package = HistoricalVisualPackageBuilder(providers=[FakeProvider([candidate(1, title="Watermark promotional poster")])], retriever=retrieve, cache=HistoricalCache(tmp_path / "cache")).build(storyboard(scene_number=1))
    assert package["shots"][0]["is_hook"] is True
    assert calls == 0 and package["shots"][0]["decision"]["state"] == "generated_fallback_eligible"


def jpeg_bytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (8, 8), (80, 120, 180)).save(output, format="JPEG")
    return output.getvalue()

def test_valid_jpeg_is_automatically_approved(tmp_path: Path) -> None:
    content = jpeg_bytes()
    jpeg = candidate(
        1,
        mime_type="image/jpeg",
        original_url="https://upload.wikimedia.org/test-1.jpg",
        page_url="https://commons.wikimedia.org/wiki/File:test-1.jpg",
    )

    package = HistoricalVisualPackageBuilder(
        providers=[FakeProvider([jpeg])],
        retriever=lambda _: content,
        cache=HistoricalCache(tmp_path / "cache"),
    ).build(storyboard())

    assert package["shots"][0]["decision"]["state"] == "approved_historical"
    assert package["summary"]["auto_approved"] == 1
    assert package["shots"][0]["candidates"][0]["fingerprints"]["perceptual_hash"]

def test_mislabeled_jpeg_uses_generated_fallback(tmp_path: Path) -> None:
    content = image_bytes()
    mislabeled = candidate(
        1,
        mime_type="image/jpeg",
        original_url="https://upload.wikimedia.org/test-1.jpg",
        page_url="https://commons.wikimedia.org/wiki/File:test-1.jpg",
    )

    package = HistoricalVisualPackageBuilder(
        providers=[FakeProvider([mislabeled])],
        retriever=lambda _: content,
        cache=HistoricalCache(tmp_path / "cache"),
    ).build(storyboard())

    record = package["shots"][0]["candidates"][0]
    assert package["shots"][0]["decision"]["state"] == "generated_fallback_eligible"
    assert record["disposition"] == "generated_fallback"
    assert record["fingerprints"] is None
    assert package["summary"]["review_queued"] == 0

def storyboard_with_plan(plan: dict[str, object]) -> dict[str, object]:
    return storyboard() | {"scenes": [{"scene_number": 2, "visual_shots": [{"shot_number": 1, "start_seconds": 20.0, "visual_intent": "Test Artist concert", "historical_search": "Test Artist concert 1970", "historical_plan": plan}]}]}


def test_avoid_term_hard_exclusion_skips_finalists_and_retrieval(tmp_path: Path) -> None:
    calls = 0

    def retrieve(_: HistoricalImageCandidate) -> bytes:
        nonlocal calls
        calls += 1
        return image_bytes()

    package = HistoricalVisualPackageBuilder(
        providers=[FakeProvider([candidate(1, title="Test Artist studio portrait")])],
        retriever=retrieve,
        cache=HistoricalCache(tmp_path / "cache"),
    ).build(
        storyboard_with_plan({"search_queries": ["one"], "avoid_terms": ["studio"]})
    )

    shot = package["shots"][0]
    assert calls == 0
    assert package["summary"]["downloaded_finalists"] == 0
    assert shot["decision"]["state"] == "generated_fallback_eligible"
    assert [record["disposition"] for record in shot["candidates"]] == ["rejected_historical_plan"]


def test_missing_life_stage_evidence_hard_exclusion_preserves_fallback(tmp_path: Path) -> None:
    calls = 0

    def retrieve(_: HistoricalImageCandidate) -> bytes:
        nonlocal calls
        calls += 1
        return image_bytes()

    package = HistoricalVisualPackageBuilder(
        providers=[FakeProvider([candidate(1, title="Test Artist concert", description="Live concert in 1970")])],
        retriever=retrieve,
        cache=HistoricalCache(tmp_path / "cache"),
    ).build(
        storyboard_with_plan({"search_queries": ["one"], "era": "childhood"})
    )

    shot = package["shots"][0]
    assert calls == 0
    assert package["summary"]["downloaded_finalists"] == 0
    assert shot["decision"]["state"] == "generated_fallback_eligible"
    assert shot["candidates"][0]["disposition"] == "rejected_historical_plan"
class FakeStreamResponse:
    def __init__(self, chunks: list[bytes], *, content_length: str | None = None) -> None:
        self.chunks = chunks
        self.headers = {} if content_length is None else {"Content-Length": content_length}
        self.chunk_size: int | None = None
        self.yielded: list[bytes] = []
        self.closed = False

    @property
    def content(self) -> bytes:
        raise AssertionError("retrieve_live_bytes must stream instead of reading response.content")

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, *, chunk_size: int) -> object:
        self.chunk_size = chunk_size
        for chunk in self.chunks:
            self.yielded.append(chunk)
            yield chunk

    def close(self) -> None:
        self.closed = True


def install_fake_requests(monkeypatch: pytest.MonkeyPatch, response: FakeStreamResponse) -> None:
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=lambda *_args, **_kwargs: response))


def test_live_retriever_streams_normal_image_within_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeStreamResponse([b"small", b"-image"], content_length="11")
    install_fake_requests(monkeypatch, response)

    assert retrieve_live_bytes(candidate(1), max_bytes=12) == b"small-image"
    assert response.chunk_size == 64 * 1024
    assert response.closed is True


def test_live_retriever_rejects_oversized_content_length_before_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeStreamResponse([b"must-not-be-read"], content_length="13")
    install_fake_requests(monkeypatch, response)

    with pytest.raises(LiveImageTooLargeError, match="Content-Length"):
        retrieve_live_bytes(candidate(1), max_bytes=12)

    assert response.yielded == []
    assert response.closed is True


def test_live_retriever_stops_stream_when_length_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeStreamResponse([b"12345678", b"90", b"must-not-be-read"])
    install_fake_requests(monkeypatch, response)

    with pytest.raises(LiveImageTooLargeError, match="stream"):
        retrieve_live_bytes(candidate(1), max_bytes=9)

    assert response.yielded == [b"12345678", b"90"]
    assert response.closed is True


def test_oversized_live_finalist_is_not_cached_or_decoded_and_next_finalist_is_tried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    normal = image_bytes()
    maximum = len(normal) + 1
    oversized = FakeStreamResponse([b"x" * maximum, b"must-not-be-read"])
    usable = FakeStreamResponse([normal])
    responses = {"https://upload.wikimedia.org/test-1.png": oversized, "https://upload.wikimedia.org/test-2.png": usable}
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=lambda url, **_kwargs: responses[url]))
    decoded: list[bytes] = []
    original_phash = historical_visual_package.phash

    def track_decode(content: bytes, *, expected_mime_type: str) -> str:
        decoded.append(content)
        return original_phash(content, expected_mime_type=expected_mime_type)

    monkeypatch.setattr(historical_visual_package, "phash", track_decode)
    package = HistoricalVisualPackageBuilder(
        providers=[FakeProvider([candidate(1), candidate(2)])],
        retriever=lambda item: retrieve_live_bytes(item, max_bytes=maximum - 1),
        cache=HistoricalCache(tmp_path / "cache"),
    ).build(storyboard_with_plan({"search_queries": ["one"]}))

    records = package["shots"][0]["candidates"]
    assert [record["disposition"] for record in records] == ["generated_fallback", "approved"]
    assert oversized.yielded == [b"x" * maximum]
    assert decoded == [normal]
    assert usable.closed is True and oversized.closed is True
    assert [path.read_bytes() for path in (tmp_path / "cache" / "objects").glob("*.bin")] == [normal]
    assert len(list((tmp_path / "cache" / "urls").glob("*.json"))) == 1
