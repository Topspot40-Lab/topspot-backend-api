import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.models.feedback import FeedbackCreate
from backend.routers import feedback
from backend.services import feedback_notifications


class RecordingFeedbackTable:
    def __init__(self):
        self.payloads = []

    def insert(self, payload):
        self.payloads.append(payload)
        return self

    def execute(self):
        return None


class FeedbackClient:
    def __init__(self, table):
        self._table = table

    def table(self, name):
        assert name == "feedback"
        return self._table


def _feedback_client(monkeypatch):
    table = RecordingFeedbackTable()
    app = FastAPI()
    app.include_router(feedback.feedback_router, prefix="/api")
    monkeypatch.setattr(feedback, "supabase", FeedbackClient(table))
    return table, TestClient(app)


def test_old_feedback_payload_uses_category_and_metadata_defaults(monkeypatch):
    table, client = _feedback_client(monkeypatch)

    async def notify(_payload):
        return None

    monkeypatch.setattr(feedback, "send_feedback_notification", notify)
    with client:
        response = client.post("/api/feedback/", json={"type": "feedback", "message": "Hello"})

    assert response.status_code == 200
    assert table.payloads[0]["category"] == "general_feedback"
    assert table.payloads[0]["metadata"] == {}


def test_feedback_metadata_default_is_not_shared():
    first = FeedbackCreate(type="feedback", message="First")
    second = FeedbackCreate(type="feedback", message="Second")

    first.metadata["source"] = "test"

    assert second.metadata == {}


def test_contact_feedback_persists_contact_category(monkeypatch):
    table, client = _feedback_client(monkeypatch)

    async def notify(_payload):
        return None

    monkeypatch.setattr(feedback, "send_feedback_notification", notify)
    with client:
        response = client.post(
            "/api/feedback/",
            json={"type": "feedback", "message": "Please call me", "category": "contact"},
        )

    assert response.status_code == 200
    assert table.payloads[0]["category"] == "contact"


def test_content_issue_persists_bug_category_and_metadata(monkeypatch):
    table, client = _feedback_client(monkeypatch)
    metadata = {"content_id": "song-42", "timestamp": 123, "details": {"source": "player"}}

    async def notify(_payload):
        return None

    monkeypatch.setattr(feedback, "send_feedback_notification", notify)
    with client:
        response = client.post(
            "/api/feedback/",
            json={
                "type": "bug",
                "message": "Incorrect artist credit",
                "category": "content_issue",
                "metadata": metadata,
            },
        )

    assert response.status_code == 200
    assert table.payloads[0]["type"] == "bug"
    assert table.payloads[0]["category"] == "content_issue"
    assert table.payloads[0]["metadata"] == metadata


def test_invalid_feedback_category_returns_validation_failure(monkeypatch):
    _table, client = _feedback_client(monkeypatch)

    with client:
        response = client.post(
            "/api/feedback/",
            json={"type": "feedback", "message": "Hello", "category": "other"},
        )

    assert response.status_code == 422


class FakeResponse:
    def raise_for_status(self):
        return None


class FakeAsyncClient:
    def __init__(self, **_kwargs):
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *args, **kwargs):
        self.post_calls.append((args, kwargs))
        return FakeResponse()


@pytest.mark.asyncio
async def test_notification_includes_category_and_pretty_metadata(monkeypatch):
    fake_client = FakeAsyncClient()
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("FEEDBACK_NOTIFICATION_FROM", "feedback@example.com")
    monkeypatch.setenv("FEEDBACK_NOTIFICATION_RECIPIENTS", "team@example.com")
    monkeypatch.setattr(feedback_notifications.httpx, "AsyncClient", lambda **_kwargs: fake_client)

    metadata = {"content_id": "song-42", "details": {"source": "player"}}
    await feedback_notifications.send_feedback_notification(
        {
            "id": "feedback-id",
            "type": "bug",
            "category": "content_issue",
            "title": "Bad credit",
            "message": "Artist name is incorrect.",
            "metadata": metadata,
        }
    )

    email = fake_client.post_calls[0][1]["json"]
    assert "[content_issue]" in email["subject"]
    assert "Category: content_issue" in email["text"]
    assert "Metadata:\n" in email["text"]
    assert json.dumps(metadata, indent=2, sort_keys=True) in email["text"]


@pytest.mark.asyncio
async def test_notification_displays_none_supplied_for_empty_metadata(monkeypatch):
    fake_client = FakeAsyncClient()
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("FEEDBACK_NOTIFICATION_FROM", "feedback@example.com")
    monkeypatch.setenv("FEEDBACK_NOTIFICATION_RECIPIENTS", "team@example.com")
    monkeypatch.setattr(feedback_notifications.httpx, "AsyncClient", lambda **_kwargs: fake_client)

    await feedback_notifications.send_feedback_notification({"type": "feedback", "message": "Hello"})

    assert "Metadata:\n(None supplied)" in fake_client.post_calls[0][1]["json"]["text"]


def test_feedback_category_metadata_migration_has_required_contract():
    migration_path = (
        Path(__file__).parents[2]
        / "supabase/migrations/202609010001_add_feedback_category_metadata.sql"
    )
    migration = migration_path.read_text(encoding="utf-8").lower()

    assert migration.strip().startswith("begin;")
    assert migration.strip().endswith("commit;")
    assert "add column if not exists category text" in migration
    assert "add column if not exists metadata jsonb" in migration
    assert "set default 'general_feedback'" in migration
    assert "set default '{}'::jsonb" in migration
    assert "set not null" in migration
    assert "contact us" in migration
    assert "landing page contact message" in migration
    assert "feedback_category_check" in migration
    assert "'contact', 'general_feedback', 'content_issue'" in migration
    assert "create index if not exists idx_feedback_category_status_created_at" in migration
