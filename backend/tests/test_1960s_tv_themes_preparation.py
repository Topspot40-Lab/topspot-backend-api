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


def test_asr_identity_normalization_keeps_numeric_ranks_and_documented_variants_strict():
    from backend.scripts.catalogs.stage_1960s_tv_themes_narration import _identity_ok
    row = {"rank": 20, "language": "en", "kind": "intro"}
    assert _identity_ok(row, {"program": "Ironside", "artist": "Quincy Jones"}, "Here at number 20, it is iron side, performed by Quincy Jones.", "en") == []
    assert _identity_ok({"rank": 5, "language": "en", "kind": "short_detail"}, {"program": "I Spy", "artist": "Hugo Montenegro & His Orchestra"}, "Theme from iSpy, performed by Hugo Montenegro and his orchestra.", "en") == []
    assert _identity_ok({"rank": 9, "language": "es-MX", "kind": "short_detail"}, {"program": "The F.B.I.", "artist": "Hugo Montenegro & His Orchestra"}, "FBI, interpretado por Hugo Montenegro y his orchestra.", "es") == []
    assert _identity_ok({"rank": 4, "language": "pt-BR", "kind": "short_detail"}, {"program": "Hawaii Five-O", "artist": "Morton Stevens"}, "Hawai 5O, interpretado por Morton Stevens.", "pt") == []
    assert _identity_ok({"rank": 14, "language": "en", "kind": "long_detail"}, {"program": "The Outer Limits", "artist": "TV Tunesters"}, "The Outer Limits, credited to TV tunisters.", "en") == []
    assert "wrong_rank" in _identity_ok(row, {"program": "Ironside", "artist": "Quincy Jones"}, "Here at number 19, it is iron side, performed by Quincy Jones.", "en")
    assert "wrong_program" in _identity_ok(row, {"program": "Ironside", "artist": "Quincy Jones"}, "Here at number 20, it is Batman, performed by Quincy Jones.", "en")


def test_closed_set_identity_rejects_a_competing_rank():
    from backend.scripts.catalogs.stage_1960s_tv_themes_narration import closed_set_decision
    entries = {1: {"program": "Ironside", "artist": "Quincy Jones"}, 2: {"program": "Batman", "artist": "Neal Hefti"}}
    row = {"rank": 1, "language": "en", "kind": "intro"}
    decision = closed_set_decision(row, entries, "Number 2, Batman, performed by Neal Hefti.")
    assert decision["nearest_rank"] == 2
    assert decision["automatic_pass"] is False
