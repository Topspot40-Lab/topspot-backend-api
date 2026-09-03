from backend.scripts.catalogs.validate_1960s_tv_themes_plan import validate
from backend.scripts.catalogs.narration_media_validation import validate_media_records
from backend.scripts.catalogs.tv_themes_1960s_apply import FINAL_RANKS, NEW_RANKS, REPLACED_RANKS, RETAINED_RANKS, load_entries


def test_1960s_tv_themes_preparation_plan_is_complete_and_utf8_safe():
    assert validate() == {
        "approved_track_count": 38,
        "intro_draft_count": 114,
        "detail_draft_count": 93,
        "expected_future_mp3_count": 207,
    }


def test_future_media_validation_requires_hashes_identity_urls_and_artwork():
    entry = {"proposed_rank": 1, "program": "Doctor Who", "artist": "Ron Grainer", "artwork_source": "Spotify"}
    text = {"rank": 1, "language": "en", "kind": "intro", "text": "Doctor Who", "text_sha256": "wrong"}
    asset = {"rank": 1, "language": "en", "kind": "intro"}
    report = validate_media_records([entry], [text], [asset])
    codes = {code for _, code in report["errors"]}
    assert {"text_hash_mismatch", "missing_audio_hash", "missing_authoritative_playback_url", "missing_artwork", "spoken_program_identity_not_verified"} <= codes


def test_apply_contract_is_exactly_preservation_first_and_catalog_64_scoped():
    entries = load_entries()
    assert len(RETAINED_RANKS) == 23
    assert len(REPLACED_RANKS) == 4
    assert len(NEW_RANKS) == 11
    assert tuple(entry["proposed_rank"] for entry in entries) == FINAL_RANKS
    assert FINAL_RANKS == tuple(range(1, 39))
    source = (__import__("pathlib").Path(__file__).parents[1] / "scripts/catalogs/tv_themes_1960s_apply.py").read_text(encoding="utf-8")
    assert "TrackRanking.decade_genre_id == CATALOG_ID" in source
    assert "session.delete(ranking)" in source
    assert "session.delete(track)" not in source
    assert "session.delete(artist)" not in source
    assert "session.rollback()" in source and "session.commit()" in source
    assert "source_rank + 100" in source


def test_contiguous_intro_regeneration_contract_rejects_stale_or_reused_media():
    from backend.scripts.catalogs.validate_1960s_tv_themes_plan import validate
    report = validate()
    assert report["intro_draft_count"] == 114
    source = (__import__("pathlib").Path(__file__).parents[1] / "scripts/catalogs/prepare_1960s_tv_themes_review.py").read_text(encoding="utf-8")
    assert "contiguous-intros-v2" in source
    assert "No existing, staged, or canonical" in source
    assert "wrong-rank, wrong-program, blank, truncated, duplicate, or undecodable" in source
    assert "Re-download all 114 live" in source
