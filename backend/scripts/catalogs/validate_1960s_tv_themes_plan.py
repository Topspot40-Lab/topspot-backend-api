"""Offline validation for the catalog-64 preparation artifacts."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent / "review_manifests"
PLAN = ROOT / "1960s-tv-themes.production-plan.v1.json"
TEXT = ROOT / "1960s-tv-themes.narration-drafts.v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate() -> dict:
    plan, drafts = _load(PLAN), _load(TEXT)
    entries = plan["approved_entries"]
    assert plan["catalog_id"] == 64
    assert [entry["proposed_rank"] for entry in entries] == list(range(1, len(entries) + 1))
    assert len({entry["spotify_track_id"] for entry in entries}) == len(entries)
    assert all(re.fullmatch(r"[A-Za-z0-9]{22}", entry["spotify_track_id"]) for entry in entries)
    assert all(entry["classification"] in {"correct_original_or_broadcast_associated", "correct_contemporary_commercial_recording", "recognizable_rerecording_or_cover"} for entry in entries)
    assert all(entry["artist"] and entry["artwork_source"] for entry in entries)
    assert plan["unresolved_excluded"]
    expected = {(entry["proposed_rank"], language, kind) for entry in entries for language in ("en", "es-MX", "pt-BR") for kind in ("intro", "short_detail", "long_detail")}
    actual = {(row["rank"], row["language"], row["kind"]) for row in drafts["records"]}
    assert actual == expected
    for row in drafts["records"]:
        text = row["text"]
        assert text == text.encode("utf-8").decode("utf-8")
        assert "Unknown Artist" not in text and "�" not in text
        assert row["text_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"approved_track_count": len(entries), "draft_count": len(drafts["records"]), "expected_future_mp3_count": len(expected)}


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
