from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.scripts import generate_music_docuseries_tts as script


def _generate_one(*, session, item, locale, overwrite=False):
    return script.generate_one(
        session=session,
        item=item,
        locale=locale,
        language="en",
        bucket="audio-en",
        voice_id="voice-id",
        settings={"stability": 0.5},
        model_id="eleven_turbo_v2_5",
        overwrite=overwrite,
        play=False,
    )


def _item_and_locale():
    item = SimpleNamespace(slug="hip_hop_goes_global", title="Hip-Hop Goes Global")
    locale = SimpleNamespace(
        id=301,
        story_text="A reviewed documentary story.",
        duration_seconds=514,
        tts_bucket=None,
        tts_key=None,
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return item, locale


@patch.object(script, "upload_bytes")
@patch.object(script, "measure_mp3_duration_seconds", return_value=544.627)
@patch.object(script, "generate_tts_mp3")
def test_generate_one_stores_ceiling_of_measured_mp3_duration(
    generate_tts_mp3,
    measure_duration,
    upload_bytes,
):
    session = MagicMock()
    item, locale = _item_and_locale()
    generated_bytes = b"completed-mp3-bytes"
    generate_tts_mp3.side_effect = (
        lambda **kwargs: kwargs["out_path"].write_bytes(generated_bytes)
    )

    assert _generate_one(session=session, item=item, locale=locale) is True

    measure_duration.assert_called_once_with(generated_bytes)
    upload_bytes.assert_called_once_with(
        bucket="audio-en",
        key="music-docuseries/301.mp3",
        data=generated_bytes,
        content_type="audio/mpeg",
    )
    assert locale.duration_seconds == 545
    assert locale.tts_bucket == "audio-en"
    assert locale.tts_key == "music-docuseries/301.mp3"
    session.add.assert_called_once_with(locale)
    session.commit.assert_called_once_with()


@pytest.mark.parametrize("duration", [0.0, -1.0, float("nan"), float("inf")])
@patch.object(script, "MP3")
def test_measure_mp3_duration_rejects_invalid_values(mp3, duration):
    mp3.return_value.info.length = duration

    with pytest.raises(RuntimeError, match="no valid duration"):
        script.measure_mp3_duration_seconds(b"invalid-duration")


@patch.object(script, "upload_bytes")
@patch.object(
    script,
    "measure_mp3_duration_seconds",
    side_effect=RuntimeError("invalid MP3"),
)
@patch.object(script, "generate_tts_mp3")
def test_invalid_mp3_is_not_uploaded_or_committed(
    generate_tts_mp3,
    _measure_duration,
    upload_bytes,
):
    session = MagicMock()
    item, locale = _item_and_locale()
    original_updated_at = locale.updated_at
    generate_tts_mp3.side_effect = (
        lambda **kwargs: kwargs["out_path"].write_bytes(b"invalid")
    )

    with pytest.raises(RuntimeError, match="invalid MP3"):
        _generate_one(session=session, item=item, locale=locale)

    upload_bytes.assert_not_called()
    session.add.assert_not_called()
    session.commit.assert_not_called()
    assert locale.duration_seconds == 514
    assert locale.tts_bucket is None
    assert locale.tts_key is None
    assert locale.updated_at == original_updated_at


@patch.object(script, "upload_bytes", side_effect=RuntimeError("upload failed"))
@patch.object(script, "measure_mp3_duration_seconds", return_value=544.627)
@patch.object(script, "generate_tts_mp3")
def test_upload_failure_does_not_update_or_commit_locale(
    generate_tts_mp3,
    _measure_duration,
    _upload_bytes,
):
    session = MagicMock()
    item, locale = _item_and_locale()
    original_updated_at = locale.updated_at
    generate_tts_mp3.side_effect = (
        lambda **kwargs: kwargs["out_path"].write_bytes(b"completed-mp3")
    )

    with pytest.raises(RuntimeError, match="upload failed"):
        _generate_one(session=session, item=item, locale=locale)

    session.add.assert_not_called()
    session.commit.assert_not_called()
    assert locale.duration_seconds == 514
    assert locale.tts_bucket is None
    assert locale.tts_key is None
    assert locale.updated_at == original_updated_at


@patch.object(script, "upload_bytes")
@patch.object(script, "measure_mp3_duration_seconds")
@patch.object(script, "generate_tts_mp3")
def test_existing_audio_is_skipped_without_overwrite(
    generate_tts_mp3,
    measure_duration,
    upload_bytes,
):
    session = MagicMock()
    item, locale = _item_and_locale()
    locale.tts_bucket = "audio-en"
    locale.tts_key = "music-docuseries/301.mp3"

    assert _generate_one(session=session, item=item, locale=locale) is False

    generate_tts_mp3.assert_not_called()
    measure_duration.assert_not_called()
    upload_bytes.assert_not_called()
    session.add.assert_not_called()
    session.commit.assert_not_called()
