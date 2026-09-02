from backend.scripts.catalogs.audit_decade_genre_catalog import build_report


def test_audit_reports_sequence_playability_decisions_and_audio():
    rows = [
        {
            "ranking": 1, "track_id": 11, "track_name": "Theme", "artist_id": 22,
            "artist_name": "Artist", "spotify_track_id": "track-id", "spotify_artist_id": "artist-id",
            "program_slug": "1950s-tv_themes", "intro": "A concise intro for the show.",
            "detail": " ".join(["long"] * 60), "short_detail": " ".join(["short"] * 31),
            "artist_description": "Artist context.", "source_type": "television", "source_title": "Show",
            "track_program_count": 2, "artist_program_count": 1,
        },
        {"ranking": 3, "track_id": 12, "track_name": "Incomplete", "artist_id": None,
         "spotify_track_id": None, "program_slug": "1950s-tv_themes", "track_program_count": 1},
    ]
    manifest = {"manifest_version": 1, "rank_decisions": [{"rank": 1, "decision": "approved_current_recording"}]}
    checked = []
    def exists(bucket, key):
        checked.append((bucket, key))
        return key == "detail/track-id.mp3"

    report = build_report({"id": 63, "slug": "1950s-tv_themes"}, rows, manifest, exists)

    assert report["rank_sequence"] == {"current": [1, 3], "internal_missing": [2], "duplicate_ranks": []}
    assert report["counts"] == {"database_rows": 2, "currently_playable_rows": 1, "incomplete_rows": 1}
    assert report["rows"][0]["gary_decision"] == "approved_current_recording"
    assert report["rows"][1]["gary_decision"] == "unreviewed/incomplete"
    assert report["rows"][0]["shared_with_other_programs"] is True
    assert report["rows"][0]["languages"]["en"]["audio"]["long_detail_mp3"] is True
    assert ("audio-en", "detail/track-id.mp3") in checked
