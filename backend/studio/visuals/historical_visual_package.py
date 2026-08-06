"""Bounded, deterministic historical visual-package selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit, urlunsplit

from backend.studio.historical.models import HistoricalImageCandidate
from backend.studio.historical.ranking import (
    is_hard_rejection_score,
    score_candidate,
)

MAX_QUERIES_PER_SHOT = 3
MAX_METADATA_CANDIDATES_PER_QUERY = 8
MAX_UNIQUE_METADATA_CANDIDATES_PER_SHOT = 16
MAX_DOWNLOADED_FINALISTS_PER_SHOT = 2
HOOK_WINDOW_SECONDS = 15.0
ALLOWED_PROVIDERS = frozenset({"wikimedia_commons"})
ALLOWED_MIME_TYPES = frozenset({"image/jpeg", "image/png"})


class HistoricalProvider(Protocol):
    provider_name: str

    def search(self, query: str, *, limit: int = 10) -> list[HistoricalImageCandidate]: ...


Retriever = Callable[[HistoricalImageCandidate], bytes]


@dataclass(frozen=True, slots=True)
class BoundedSearchSettings:
    max_queries_per_shot: int = MAX_QUERIES_PER_SHOT
    max_metadata_candidates_per_query: int = MAX_METADATA_CANDIDATES_PER_QUERY
    max_unique_metadata_candidates_per_shot: int = MAX_UNIQUE_METADATA_CANDIDATES_PER_SHOT
    max_downloaded_finalists_per_shot: int = MAX_DOWNLOADED_FINALISTS_PER_SHOT
    hook_window_seconds: float = HOOK_WINDOW_SECONDS


def canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path, parts.query, "")) if value.strip() else ""


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _from_dict(payload: dict[str, Any]) -> HistoricalImageCandidate:
    fields = HistoricalImageCandidate.__dataclass_fields__
    values = {key: value for key, value in payload.items() if key in fields}
    if isinstance(values.get("categories"), list):
        values["categories"] = tuple(str(value) for value in values["categories"])
    return HistoricalImageCandidate(**values)


class HistoricalCache:
    """Caches provider responses and immutable bytes for cross-shot reuse."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def search(self, provider: HistoricalProvider, query: str, limit: int) -> tuple[list[HistoricalImageCandidate], bool]:
        path = self.root / "provider-results" / f"{digest(provider.provider_name + '\\n' + query + '\\n' + str(limit))}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return [_from_dict(item) for item in data["candidates"]], True
        results = provider.search(query, limit=limit)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"candidates": [item.to_dict() for item in results]}, indent=2) + "\n", encoding="utf-8")
        return results, False

    def retrieve(self, candidate: HistoricalImageCandidate, retriever: Retriever) -> tuple[bytes, str, bool]:
        identity = canonical_url(candidate.original_url) or canonical_url(candidate.page_url)
        mapping = self.root / "urls" / f"{digest(identity)}.json"
        if mapping.exists():
            sha256 = str(json.loads(mapping.read_text(encoding="utf-8"))["sha256"])
            object_path = self.root / "objects" / f"{sha256}.bin"
            if object_path.exists():
                return object_path.read_bytes(), sha256, True
        content = retriever(candidate)
        if not content:
            raise RuntimeError("Historical image retrieval returned no data")
        sha256 = hashlib.sha256(content).hexdigest()
        object_path = self.root / "objects" / f"{sha256}.bin"
        object_path.parent.mkdir(parents=True, exist_ok=True)
        if not object_path.exists():
            object_path.write_bytes(content)
        mapping.parent.mkdir(parents=True, exist_ok=True)
        mapping.write_text(json.dumps({"canonical_url": identity, "sha256": sha256}) + "\n", encoding="utf-8")
        return content, sha256, False


def license_status(candidate: HistoricalImageCandidate) -> tuple[str, str]:
    text = " ".join((candidate.license_name, candidate.license_url, candidate.usage_terms)).casefold()
    if any(value in text for value in ("noncommercial", "cc by-nc", "cc-by-nc", "no derivatives", "no-derivatives", "cc by-nd", "cc-by-nd", "all rights reserved", "editorial only")):
        return "reject", "commercial_license_rejected"
    source_complete = bool(candidate.page_url and candidate.original_url and candidate.license_name)
    if "public domain" in text or "cc0" in text:
        return ("eligible", "public_domain_or_cc0") if source_complete else ("review", "license_provenance_incomplete")
    if "cc by" in text or "cc-by" in text:
        complete = bool(source_complete and candidate.creator and candidate.credit and candidate.license_url)
        return ("eligible", "attribution_license_complete") if complete else ("review", "attribution_incomplete")
    return "review", "license_uncertain"


def metadata_gates(candidate: HistoricalImageCandidate) -> tuple[str, list[dict[str, Any]]]:
    overlay_text = " ".join((candidate.title, candidate.description, *candidate.categories)).casefold()
    overlay = any(value in overlay_text for value in ("watermark", "promotional", "promo", "advertisement", "album cover", "poster", "logo"))
    license_state, license_reason = license_status(candidate)
    gates = [
        {"name": "permitted_source", "passed": candidate.provider in ALLOWED_PROVIDERS, "reason": "permitted_provider" if candidate.provider in ALLOWED_PROVIDERS else "provider_not_permitted"},
        {"name": "safe_retrievable_urls", "passed": candidate.page_url.startswith("https://") and candidate.original_url.startswith("https://"), "reason": "https_urls" if candidate.page_url.startswith("https://") and candidate.original_url.startswith("https://") else "missing_or_non_https_url"},
        {"name": "image_suitability", "passed": candidate.mime_type in ALLOWED_MIME_TYPES and candidate.width >= 800 and candidate.height >= 500, "reason": "metadata_suitable" if candidate.mime_type in ALLOWED_MIME_TYPES and candidate.width >= 800 and candidate.height >= 500 else "mime_or_resolution_unsuitable"},
        {"name": "commercial_license", "passed": license_state == "eligible", "reason": license_reason},
        {"name": "metadata_overlay_signal", "passed": not overlay, "reason": "no_metadata_overlay_signal" if not overlay else "metadata_overlay_signal_detected"},
    ]
    if not all(gate["passed"] for gate in gates if gate["name"] != "commercial_license") or license_state == "reject":
        return "rejected", gates
    return ("eligible", gates) if license_state == "eligible" else ("review", gates)


def phash(content: bytes, *, expected_mime_type: str) -> str:
    """Decode a permitted image locally and return a deterministic perceptual hash."""
    from PIL import Image

    with Image.open(BytesIO(content)) as source:
        actual_mime_type = {"JPEG": "image/jpeg", "PNG": "image/png"}.get(source.format)
        if actual_mime_type != expected_mime_type:
            raise ValueError("Retrieved image MIME type does not match candidate metadata")
        source.verify()
    with Image.open(BytesIO(content)) as source:
        source.load()
        image = source.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
        values = list(image.get_flattened_data())
    average = sum(values) / len(values)
    return "".join("1" if value >= average else "0" for value in values)

def phash_distance(first: str, second: str) -> int:
    return sum(one != two for one, two in zip(first, second, strict=True))


def queries_for(shot: dict[str, Any], title: str, settings: BoundedSearchSettings) -> list[str]:
    plan = shot.get("historical_plan") if isinstance(shot.get("historical_plan"), dict) else {}
    values = [str(value).strip() for value in plan.get("search_queries", [])]
    values += [str(shot.get("historical_search") or "").strip(), f"{title} {str(shot.get('visual_intent') or '').strip()}".strip(), title]
    result: list[str] = []
    for value in values:
        value = " ".join(value.split())
        if value and value.casefold() not in {item.casefold() for item in result}:
            result.append(value)
        if len(result) == settings.max_queries_per_shot:
            break
    return result


class HistoricalVisualPackageBuilder:
    def __init__(self, *, providers: list[HistoricalProvider], retriever: Retriever, cache: HistoricalCache, settings: BoundedSearchSettings = BoundedSearchSettings()) -> None:
        self.providers, self.retriever, self.cache, self.settings = providers, retriever, cache, settings
        self.selected: list[tuple[str, str]] = []
        self.counts = {"provider_searches": 0, "provider_cache_hits": 0, "metadata_candidates": 0, "metadata_rejected": 0, "downloaded_finalists": 0, "retrieval_cache_hits": 0, "auto_approved": 0, "review_queued": 0, "generated_fallback_eligible": 0, "duplicates": 0}

    def _record(self, candidate: HistoricalImageCandidate, query: str, state: str, gates: list[dict[str, Any]], score: float | None = None) -> dict[str, Any]:
        return {"candidate_id": digest(canonical_url(candidate.page_url) or canonical_url(candidate.original_url)), "query": query, "candidate": candidate.to_dict(), "disposition": state, "gates": gates, "deterministic_score": score, "retrieval": None, "fingerprints": None}

    def _shot(self, scene: dict[str, Any], shot: dict[str, Any], title: str) -> dict[str, Any]:
        queries = queries_for(shot, title, self.settings)
        merged: dict[str, tuple[HistoricalImageCandidate, str]] = {}
        failures: list[str] = []
        for query in queries:
            for provider in self.providers:
                try:
                    candidates, hit = self.cache.search(provider, query, self.settings.max_metadata_candidates_per_query)
                    self.counts["provider_cache_hits" if hit else "provider_searches"] += 1
                except Exception as exc:
                    failures.append(f"{provider.provider_name}:{type(exc).__name__}")
                    continue
                for candidate in candidates[:self.settings.max_metadata_candidates_per_query]:
                    key = canonical_url(candidate.page_url) or canonical_url(candidate.original_url)
                    if key and key not in merged and len(merged) < self.settings.max_unique_metadata_candidates_per_shot:
                        merged[key] = (candidate, query)
        self.counts["metadata_candidates"] += len(merged)
        records: list[dict[str, Any]] = []
        finalists: list[tuple[HistoricalImageCandidate, str, dict[str, Any], float]] = []
        plan = shot.get("historical_plan") if isinstance(shot.get("historical_plan"), dict) else None
        for candidate, query in merged.values():
            state, gates = metadata_gates(candidate)
            if state != "eligible":
                records.append(self._record(candidate, query, state, gates))
                self.counts["metadata_rejected"] += state == "rejected"
                continue
            relevance_query = str(shot.get("historical_search") or shot.get("visual_intent") or title)
            score = score_candidate(candidate, relevance_query, historical_plan=plan)
            if is_hard_rejection_score(score):
                rejected_gates = [
                    *gates,
                    {
                        "name": "historical_plan",
                        "passed": False,
                        "reason": "hard_ranking_exclusion",
                    },
                ]
                records.append(
                    self._record(
                        candidate,
                        query,
                        "rejected_historical_plan",
                        rejected_gates,
                        score,
                    )
                )
                self.counts["metadata_rejected"] += 1
                continue
            finalists.append((candidate, query, self._record(candidate, query, "metadata_eligible", gates, score), score))
        finalists.sort(key=lambda item: item[3], reverse=True)
        downloaded: list[tuple[dict[str, Any], HistoricalImageCandidate, float, str]] = []
        for candidate, query, record, score in finalists[:self.settings.max_downloaded_finalists_per_shot]:
            try:
                content, sha256, hit = self.cache.retrieve(candidate, self.retriever)
                self.counts["retrieval_cache_hits" if hit else "downloaded_finalists"] += 1
                fingerprint = phash(content, expected_mime_type=candidate.mime_type)
                record["retrieval"] = {"sha256": sha256, "bytes": len(content), "cache_hit": hit}
                record["fingerprints"] = {"sha256": sha256, "perceptual_hash": fingerprint}
                if any(sha256 == previous_sha or phash_distance(fingerprint, previous_phash) <= 2 for previous_sha, previous_phash in self.selected):
                    record["disposition"] = "rejected_duplicate"
                    record["gates"].append({"name": "duplicate", "passed": False, "reason": "exact_or_perceptual_duplicate"})
                    self.counts["duplicates"] += 1
                else:
                    record["disposition"] = "downloaded_finalist"
                    downloaded.append((record, candidate, score, sha256))
            except Exception as exc:
                record["disposition"] = "review"
                record["gates"].append({"name": "retrieval_and_decode", "passed": False, "reason": type(exc).__name__})
            records.append(record)
        hook = int(scene.get("scene_number") or 0) == 1 or float(shot.get("start_seconds") or 0) < self.settings.hook_window_seconds
        decision, reasons, selected_id, score_value, margin = "generated_fallback_eligible", [], None, None, None
        if failures or any(record["disposition"] == "review" for record in records):
            decision, reasons = "needs_review", ["provider_failure" if failures else "candidate_requires_review"]
        elif downloaded:
            record, candidate, score, sha256 = downloaded[0]
            score_value = round(score, 3)
            margin = round(score - downloaded[1][2], 3) if len(downloaded) > 1 else 100.0
            trusted = bool(candidate.overlay_reviewed and candidate.overlay_reviewed_at and candidate.overlay_reviewer and candidate.overlay_reviewed_sha256 == sha256)
            threshold, required_margin = (93.0, 15.0) if hook else (88.0, 10.0)
            if trusted and score >= threshold and margin >= required_margin:
                decision, selected_id, reasons, record["disposition"] = "approved_historical", record["candidate_id"], ["trusted_hash_review", "high_confidence"], "approved"
                self.selected.append((sha256, str(record["fingerprints"]["perceptual_hash"])))
                self.counts["auto_approved"] += 1
            else:
                decision = "generated_fallback_eligible"
                reasons = [
                    "overlay_unverified"
                    if not trusted
                    else "confidence_below_auto_approval_threshold"
                ]
                record["disposition"] = "generated_fallback"
        if decision == "needs_review": self.counts["review_queued"] += 1
        if decision == "generated_fallback_eligible": self.counts["generated_fallback_eligible"] += 1
        return {"scene_number": int(scene["scene_number"]), "shot_number": int(shot["shot_number"]), "is_hook": hook, "queries": queries, "provider_failures": failures, "candidates": records, "decision": {"state": decision, "selected_candidate_id": selected_id, "deterministic_score": score_value, "score_margin": margin, "reason_codes": reasons, "reuse_scope": "shared_all_languages"}}

    def build(self, storyboard: dict[str, Any]) -> dict[str, Any]:
        title = str(storyboard.get("title") or "")
        shots = [self._shot(scene, shot, title) for scene in storyboard.get("scenes", []) for shot in scene.get("visual_shots", [])]
        return {"version": 1, "production_slug": storyboard.get("production_slug"), "created_at": datetime.now(UTC).isoformat(), "shared_for_languages": ["en", "es", "pt-BR"], "bounded_search": asdict(self.settings), "shots": shots, "summary": self.counts}
