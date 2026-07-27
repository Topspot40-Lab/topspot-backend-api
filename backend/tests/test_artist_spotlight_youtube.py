from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.routers.artist_spotlight import artist_story


def _configure_story_query(mock_engine, story_row):
    connection = (
        mock_engine.connect.return_value
        .__enter__.return_value
    )
    connection.execute.return_value.mappings.return_value.first.return_value = (
        story_row
    )


def _configure_asset_query(mock_session_class, asset):
    session = (
        mock_session_class.return_value
        .__enter__.return_value
    )
    session.exec.return_value.first.return_value = asset
    return session


@patch("backend.routers.artist_spotlight.Session")
@patch("backend.routers.artist_spotlight.engine")
def test_artist_story_with_published_youtube_video(
    mock_engine,
    mock_session_class,
):
    story = {
        "story_id": 10,
        "artist_id": 20,
        "language_code": "en",
        "title": "Artist Story",
        "story_type": "biography",
        "duration_seconds": 300,
        "tts_bucket": "audio-en",
        "tts_key": "artist-story/10.mp3",
    }
    asset = SimpleNamespace(
        youtube_video_id="video-123",
        youtube_url="https://www.youtube.com/watch?v=video-123",
    )

    _configure_story_query(mock_engine, story)
    _configure_asset_query(mock_session_class, asset)

    response = artist_story(
        artist_id=20,
        language="en",
    )

    assert response["ok"] is True
    assert response["has_story"] is True
    assert response["has_youtube_video"] is True
    assert response["youtube_video_id"] == "video-123"
    assert response["youtube_url"] == (
        "https://www.youtube.com/watch?v=video-123"
    )


@patch("backend.routers.artist_spotlight.Session")
@patch("backend.routers.artist_spotlight.engine")
def test_artist_story_without_youtube_video(
    mock_engine,
    mock_session_class,
):
    story = {
        "story_id": 10,
        "artist_id": 20,
        "language_code": "en",
        "title": "Artist Story",
        "story_type": "biography",
        "duration_seconds": 300,
        "tts_bucket": "audio-en",
        "tts_key": "artist-story/10.mp3",
    }

    _configure_story_query(mock_engine, story)
    _configure_asset_query(mock_session_class, None)

    response = artist_story(
        artist_id=20,
        language="en",
    )

    assert response["ok"] is True
    assert response["has_story"] is True
    assert response["has_youtube_video"] is False
    assert response["youtube_video_id"] is None
    assert response["youtube_url"] is None


@patch("backend.routers.artist_spotlight.Session")
@patch("backend.routers.artist_spotlight.engine")
def test_no_artist_story_with_published_youtube_video(
    mock_engine,
    mock_session_class,
):
    asset = SimpleNamespace(
        youtube_video_id="video-456",
        youtube_url="https://www.youtube.com/watch?v=video-456",
    )

    _configure_story_query(mock_engine, None)
    _configure_asset_query(mock_session_class, asset)

    response = artist_story(
        artist_id=20,
        language="en",
    )

    assert response["ok"] is False
    assert response["has_story"] is False
    assert response["has_youtube_video"] is True
    assert response["youtube_video_id"] == "video-456"
    assert response["youtube_url"] == (
        "https://www.youtube.com/watch?v=video-456"
    )


@patch("backend.routers.artist_spotlight.Session")
@patch("backend.routers.artist_spotlight.engine")
def test_no_artist_story_or_youtube_video(
    mock_engine,
    mock_session_class,
):
    _configure_story_query(mock_engine, None)
    _configure_asset_query(mock_session_class, None)

    response = artist_story(
        artist_id=20,
        language="en",
    )

    assert response == {
        "ok": False,
        "has_story": False,
        "artist_id": 20,
        "language": "en",
        "has_youtube_video": False,
        "youtube_video_id": None,
        "youtube_url": None,
    }


@patch("backend.routers.artist_spotlight.Session")
@patch("backend.routers.artist_spotlight.engine")
def test_youtube_asset_query_orders_newest_version_first(
    mock_engine,
    mock_session_class,
):
    _configure_story_query(mock_engine, None)
    session = _configure_asset_query(
        mock_session_class,
        None,
    )

    artist_story(
        artist_id=20,
        language="en",
    )

    statement = session.exec.call_args.args[0]
    sql = str(statement.compile()).lower()

    assert "order by" in sql
    assert "version_number desc" in sql
