"""Offline validation for the rank-preserving catalog-64 preparation artifacts."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from backend.scripts.catalogs.prepare_1960s_tv_themes_review import ADDITIONS, DETAIL_REPLACEMENTS, RETAINED_RANKS

ROOT = Path(__file__).parent / "review_manifests"
PLAN = ROOT / "1960s-tv-themes.production-plan.v1.json"
TEXT = ROOT / "1960s-tv-themes.narration-drafts.v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate() -> dict:
    plan, drafts = _load(PLAN), _load(TEXT)
    entries = plan["approved_entries"]
    assert plan["catalog_id"] == 64
    assert [entry["sequence_order"] for entry in entries] == list(range(1, 39))
    assert [entry["proposed_rank"] for entry in entries] == list(range(1, 39))
    assert len({entry["proposed_rank"] for entry in entries}) == 38
    assert all(1 <= entry["proposed_rank"] <= 38 for entry in entries)
    assert len({entry["spotify_track_id"] for entry in entries}) == len(entries)
    assert all(re.fullmatch(r"[A-Za-z0-9]{22}", entry["spotify_track_id"]) for entry in entries)
    assert all(entry["classification"] in {"correct_original_or_broadcast_associated", "correct_contemporary_commercial_recording", "recognizable_rerecording_or_cover"} for entry in entries)
    assert all(entry["artist"] and entry["artwork_source"] for entry in entries)
    assert len(RETAINED_RANKS) == 27 and len(ADDITIONS) == 11
    assert plan["gap_filler_research"]["status"] == "deferred_without_verified_candidates"
    expected_intro = {(entry["proposed_rank"], language, "intro") for entry in entries for language in ("en", "es-MX", "pt-BR")}
    final_rank_for_source = {entry["source_rank"]: entry["proposed_rank"] for entry in entries}
    expected_detail = {(final_rank_for_source[rank], language, kind) for rank, language, kind in DETAIL_REPLACEMENTS}
    expected = expected_intro | expected_detail
    actual = {(row["rank"], row["language"], row["kind"]) for row in drafts["records"]}
    assert actual == expected
    for row in drafts["records"]:
        text = row["text"]
        assert text == text.encode("utf-8").decode("utf-8")
        assert "Unknown Artist" not in text and "\ufffd" not in text and "Ã" not in text
        assert not re.search(r"\b(?:TBD|TODO|N/A|placeholder)\b", text, re.I)
        entry = next(entry for entry in entries if entry["proposed_rank"] == row["rank"])
        assert all(identity.casefold() in text.casefold() for identity in (entry["program"], entry["track_name"], entry["artist"]))
        assert row["text_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert not re.search(r"\b(?:40|41|44|45)\b", text)
    intro_texts = [row["text"] for row in drafts["records"] if row["kind"] == "intro"]
    assert len(set(intro_texts)) == len(intro_texts)
    intros = [row for row in drafts["records"] if row["kind"] == "intro"]
    assert len(intros) == 114
    assert {row["rank"] for row in intros} == set(range(1, 39))
    assert all(row["canonical_key"] == f"intro/1960s_tv_themes_{row['rank']:02}.mp3" for row in intros)
    assert all(str(row["rank"]) in row["text"] for row in intros)
    for language in ("en", "es-MX", "pt-BR"):
        for kind in ("short_detail", "long_detail"):
            texts = [row["text"] for row in drafts["records"] if row["language"] == language and row["kind"] == kind]
            assert len(texts) == len(set(texts))
    shorts = [row["text"] for row in drafts["records"] if row["kind"] == "short_detail"]
    assert all(20 <= len(text.replace(",", "").replace(".", "").split()) <= 35 for text in shorts)
    longs = [row["text"] for row in drafts["records"] if row["kind"] == "long_detail"]
    assert all(len(re.findall(r"(?<![A-Z])\.(?:\s|$)", text)) == 4 for text in longs)
    assert plan["intro_rewrite"]["record_count"] == len(expected_intro)
    assert plan["detail_preservation"]["replacement_mapping_count"] == len(expected_detail)
    assert plan["detail_preservation"]["retain_mapping_count"] == 135
    assert plan["database_delta"]["retained_track_artist_rows"] == 23
    assert plan["database_delta"]["replaced_rankings_in_place"] == 4
    assert plan["database_delta"]["new_tracks"] == 11
    assert plan["database_delta"]["duplicate_rankings_removed"] == 8
    assert plan["database_delta"]["unresolved_rankings_removed"] == 3
    assert plan["database_delta"]["final_ranks"] == [entry["proposed_rank"] for entry in entries]
    assert plan["media_execution"]["staged_mp3_count"] == len(expected)
    assert plan["media_execution"]["staging_prefix"].startswith("staging/catalog-64/")
    assert "114" in plan["intro_rewrite"]["promotion_rule"]
    assert "eligible for reuse" in plan["intro_rewrite"]["reuse_rule"]
    assert "locally transcribe" in plan["intro_rewrite"]["promotion_rule"]
    assert "Re-download all 114" in plan["intro_rewrite"]["post_promotion_rule"]
    return {
        "approved_track_count": len(entries),
        "intro_draft_count": len(expected_intro),
        "detail_draft_count": len(expected_detail),
        "expected_future_mp3_count": len(expected),
    }


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
