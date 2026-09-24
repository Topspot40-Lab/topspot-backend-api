from types import SimpleNamespace
from unittest.mock import Mock

from backend.scripts.backfill_missing_ranked_durations import (
    ADDITIONAL_TV_THEMES_RANKING_IDS,
    PREVIOUSLY_BACKFILLED_RANKING_IDS,
    TARGET_RANKING_IDS,
    apply_null_only_backfill,
    build_review_rows,
)


EXPECTED_PROPOSALS = {
    3840: ("3EsN4lGtZX7TYlMyH0CcK3", 41_000), 3841: ("323Ys8qcHBgNiKvRxernN1", 144_480),
    3499: ("6I2oKAEHPCtFUPe7Tsm1Xt", 97_200), 3842: ("1nTD2cATmzFZKgufzkAHPL", 117_640),
    3843: ("2ygk3Op3lrmgjkZr1L6iby", 130_386), 3844: ("2aRxRElu4TpqWtJK4xasFk", 71_443),
    3845: ("5XeT2svrGgYWY9ItW6omKJ", 147_440), 3846: ("30RmekD1dSy913wZnryc1h", 233_986),
    3516: ("2bNADRKyZiui7TOgIFilFr", 122_240), 3847: ("6ygYhprIQI9ypKyTJo17aB", 84_513),
    3848: ("2kZzRXWdTrgxpPet4ePP9y", 98_266), 3849: ("0qIfrXXLgb7MmmrrYdhEgh", 36_594),
    3850: ("54sQ4BZgpxDD8baHHLTyOq", 62_080), 3539: ("5dxWU9epbOtZ0XHv60tydp", 140_933),
    3540: ("4Up8UssyK2nFZWVp7k0A1O", 105_880),
}


def test_review_rows_match_the_exact_null_duration_backfill_proposals():
    candidates = [{"ranking_id": ranking_id, "track_id": ranking_id + 1000, "spotify_track_id": spotify_id, "current_duration_ms": None} for ranking_id, (spotify_id, _) in EXPECTED_PROPOSALS.items()]
    durations = {spotify_id: duration_ms for spotify_id, duration_ms in EXPECTED_PROPOSALS.values()}

    rows = build_review_rows(candidates, durations)

    assert [(row["ranking_id"], row["spotify_track_id"], row["current_duration_ms"], row["proposed_duration_ms"]) for row in rows] == [
        (ranking_id, spotify_id, None, duration_ms) for ranking_id, (spotify_id, duration_ms) in EXPECTED_PROPOSALS.items()
    ]
    assert all(row["source"].startswith("Spotify Web API") for row in rows)


def test_targets_include_the_35_corrected_tv_theme_rankings_but_not_3933():
    assert TARGET_RANKING_IDS == PREVIOUSLY_BACKFILLED_RANKING_IDS + ADDITIONAL_TV_THEMES_RANKING_IDS
    assert len(TARGET_RANKING_IDS) == 35
    assert set(ADDITIONAL_TV_THEMES_RANKING_IDS) == {*range(3809, 3828), 3570}
    assert 3933 not in TARGET_RANKING_IDS


def test_apply_is_null_only_and_is_a_noop_when_every_target_is_already_backfilled():
    session = Mock()
    session.execute.return_value = SimpleNamespace(rowcount=0)
    rows = [{"track_id": 1, "spotify_track_id": "spotify-id", "proposed_duration_ms": 123_456}]

    assert apply_null_only_backfill(session, rows) == 0
    statement = session.execute.call_args.args[0]
    assert "duration_ms IS NULL" in str(statement)
    session.commit.assert_called_once_with()