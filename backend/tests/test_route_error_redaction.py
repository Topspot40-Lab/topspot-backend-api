import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import collections_player, feedback


SENSITIVE_ERROR = "postgresql://route_user:private-password@example.test/topspot token=private-token"
SENSITIVE_FRAGMENTS = (
    "postgresql://",
    "route_user",
    "private-password",
    "example.test",
    "private-token",
)
FEEDBACK_BODY = {
    "type": "bug",
    "message": "A button did not work",
    "title": "Playback issue",
    "email": "tester@example.com",
    "route": "/player",
}


class FailingFeedbackTable:
    def insert(self, _payload):
        return self

    def execute(self):
        raise RuntimeError(SENSITIVE_ERROR)


class SuccessfulFeedbackTable:
    def insert(self, _payload):
        return self

    def execute(self):
        return None


class FeedbackClient:
    def __init__(self, table):
        self._table = table

    def table(self, name):
        assert name == "feedback"
        return self._table


def _assert_sensitive_data_is_redacted(response, caplog):
    exposed = response.text + caplog.text
    assert SENSITIVE_ERROR not in exposed
    assert "Traceback" not in exposed
    for fragment in SENSITIVE_FRAGMENTS:
        assert fragment not in exposed


def test_collection_start_failure_is_redacted_from_response_and_logs(monkeypatch, caplog):
    app = FastAPI()
    app.include_router(collections_player.router)
    app.dependency_overrides[collections_player.bind_request_user] = lambda: "test-user"

    async def fail_start(_coro):
        raise RuntimeError(SENSITIVE_ERROR)

    monkeypatch.setattr(collections_player, "start_new_sequence", fail_start)
    monkeypatch.setattr(collections_player, "run_collection_sequence", lambda **_kwargs: object())

    with TestClient(app) as client, caplog.at_level(logging.INFO, logger=collections_player.logger.name):
        response = client.get(
            "/supabase/collections/play-collection-sequence?collection_slug=private-token"
        )

    assert response.status_code == 500
    assert response.json() == {
        "error": "collection_start_failed",
        "detail": collections_player.COLLECTION_START_FAILED_DETAIL,
    }
    _assert_sensitive_data_is_redacted(response, caplog)


def test_feedback_persistence_failure_is_redacted_from_response_and_logs(monkeypatch, caplog):
    app = FastAPI()
    app.include_router(feedback.feedback_router, prefix="/api")
    monkeypatch.setattr(feedback, "supabase", FeedbackClient(FailingFeedbackTable()))

    with TestClient(app) as client, caplog.at_level(logging.ERROR, logger=feedback.logger.name):
        response = client.post("/api/feedback/", json=FEEDBACK_BODY)

    assert response.status_code == 500
    assert response.json() == {"detail": feedback.FEEDBACK_SUBMISSION_FAILED_DETAIL}
    _assert_sensitive_data_is_redacted(response, caplog)


def test_feedback_notification_failure_has_no_traceback_or_sensitive_log(monkeypatch, caplog):
    app = FastAPI()
    app.include_router(feedback.feedback_router, prefix="/api")
    monkeypatch.setattr(feedback, "supabase", FeedbackClient(SuccessfulFeedbackTable()))

    async def fail_notification(_payload):
        raise RuntimeError(SENSITIVE_ERROR)

    monkeypatch.setattr(feedback, "send_feedback_notification", fail_notification)

    with TestClient(app) as client, caplog.at_level(logging.ERROR, logger=feedback.logger.name):
        response = client.post("/api/feedback/", json=FEEDBACK_BODY)

    assert response.status_code == 200
    assert response.json()["message"] == "Feedback submitted successfully"
    assert response.json()["id"]
    _assert_sensitive_data_is_redacted(response, caplog)
