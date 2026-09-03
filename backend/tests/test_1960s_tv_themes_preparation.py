from backend.scripts.catalogs.validate_1960s_tv_themes_plan import validate
from backend.scripts.catalogs.narration_media_validation import validate_media_records


def test_1960s_tv_themes_preparation_plan_is_complete_and_utf8_safe():
    assert validate() == {
        "approved_track_count": 27,
        "draft_count": 243,
        "expected_future_mp3_count": 243,
    }


def test_future_media_validation_requires_hashes_identity_urls_and_artwork():
    entry = {"proposed_rank": 1, "program": "Doctor Who", "artist": "Ron Grainer", "artwork_source": "Spotify"}
    text = {"rank": 1, "language": "en", "kind": "intro", "text": "Doctor Who", "text_sha256": "wrong"}
    asset = {"rank": 1, "language": "en", "kind": "intro"}
    report = validate_media_records([entry], [text], [asset])
    codes = {code for _, code in report["errors"]}
    assert {"text_hash_mismatch", "missing_audio_hash", "missing_authoritative_playback_url", "missing_artwork", "spoken_program_identity_not_verified"} <= codes
