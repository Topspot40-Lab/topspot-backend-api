import base64
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://fake-project.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.resend_webhook import router as resend_webhook_router
from svix.webhooks import Webhook


FAKE_WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"fake-test-secret-32-bytes-long!").decode()

app = FastAPI()
app.include_router(resend_webhook_router, prefix="/api")
client = TestClient(app)


def _signed_headers(body: bytes, secret: str = FAKE_WEBHOOK_SECRET) -> dict:
    msg_id = "msg_test_123"
    timestamp = datetime.now(timezone.utc)
    signature = Webhook(secret).sign(msg_id=msg_id, timestamp=timestamp, data=body.decode())

    return {
        "svix-id": msg_id,
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": signature,
    }


def _post_webhook(payload: bytes, headers: dict):
    return client.post(
        "/api/webhooks/resend",
        content=payload,
        headers=headers,
    )


CONTACT_UPDATED_UNSUBSCRIBED_BODY = (
    b'{"type":"contact.updated","data":'
    b'{"email":"  Existing@Example.com  ","unsubscribed":true}}'
)

CONTACT_UPDATED_RESUBSCRIBED_BODY = (
    b'{"type":"contact.updated","data":'
    b'{"email":"existing@example.com","unsubscribed":false}}'
)

CONTACT_UPDATED_UNKNOWN_EMAIL_BODY = (
    b'{"type":"contact.updated","data":'
    b'{"email":"unknown@example.com","unsubscribed":true}}'
)


def _mock_supabase_for_existing_user_and_existing_pref():
    mock_supabase = MagicMock()

    users_query = mock_supabase.table.return_value.select.return_value.ilike.return_value.limit.return_value.execute
    users_query.return_value.data = [{"id": "topspot_user_1"}]

    pref_select_query = mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute
    pref_select_query.return_value.data = [{"marketing_opt_in_at": "2024-01-01T00:00:00+00:00"}]

    return mock_supabase


def _mock_supabase_for_existing_user_and_no_pref():
    mock_supabase = MagicMock()

    users_query = mock_supabase.table.return_value.select.return_value.ilike.return_value.limit.return_value.execute
    users_query.return_value.data = [{"id": "topspot_user_1"}]

    pref_select_query = mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute
    pref_select_query.return_value.data = []

    return mock_supabase


def _mock_supabase_for_unknown_user():
    mock_supabase = MagicMock()

    users_query = mock_supabase.table.return_value.select.return_value.ilike.return_value.limit.return_value.execute
    users_query.return_value.data = []

    return mock_supabase


# =====================================================
# a) unsubscribed=true updates an existing preference row
# =====================================================

def test_contact_updated_unsubscribed_updates_existing_row():
    mock_supabase = _mock_supabase_for_existing_user_and_existing_pref()
    headers = _signed_headers(CONTACT_UPDATED_UNSUBSCRIBED_BODY)

    with patch("backend.routers.resend_webhook.supabase", mock_supabase), \
         patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": FAKE_WEBHOOK_SECRET}):
        response = _post_webhook(CONTACT_UPDATED_UNSUBSCRIBED_BODY, headers)

    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    # Email lookup normalized (stripped + lowercased)
    mock_supabase.table.return_value.select.return_value.ilike.assert_any_call(
        "email", "existing@example.com"
    )

    # Preference row updated, not inserted
    mock_supabase.table.return_value.update.assert_called_once()
    update_payload = mock_supabase.table.return_value.update.call_args[0][0]
    assert update_payload["marketing_opt_in"] is False
    assert update_payload["marketing_opt_in_at"] == "2024-01-01T00:00:00+00:00"
    assert update_payload["marketing_unsubscribed_at"] is not None
    assert update_payload["consent_source"] == "resend_unsubscribe"
    mock_supabase.table.return_value.update.return_value.eq.assert_called_once_with(
        "user_id", "topspot_user_1"
    )
    mock_supabase.table.return_value.insert.assert_not_called()


# =====================================================
# b) unsubscribed=true creates a missing preference row
# =====================================================

def test_contact_updated_unsubscribed_creates_missing_row():
    mock_supabase = _mock_supabase_for_existing_user_and_no_pref()
    headers = _signed_headers(CONTACT_UPDATED_UNSUBSCRIBED_BODY)

    with patch("backend.routers.resend_webhook.supabase", mock_supabase), \
         patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": FAKE_WEBHOOK_SECRET}):
        response = _post_webhook(CONTACT_UPDATED_UNSUBSCRIBED_BODY, headers)

    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    mock_supabase.table.return_value.insert.assert_called_once()
    insert_payload = mock_supabase.table.return_value.insert.call_args[0][0]
    assert insert_payload["user_id"] == "topspot_user_1"
    assert insert_payload["marketing_opt_in"] is False
    assert insert_payload["marketing_opt_in_at"] is None
    assert insert_payload["marketing_unsubscribed_at"] is not None
    assert insert_payload["consent_source"] == "resend_unsubscribe"
    mock_supabase.table.return_value.update.assert_not_called()


# =====================================================
# c) unsubscribed=false makes no marketing-consent change
# =====================================================

def test_contact_updated_resubscribed_makes_no_change():
    mock_supabase = _mock_supabase_for_existing_user_and_existing_pref()
    headers = _signed_headers(CONTACT_UPDATED_RESUBSCRIBED_BODY)

    with patch("backend.routers.resend_webhook.supabase", mock_supabase), \
         patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": FAKE_WEBHOOK_SECRET}):
        response = _post_webhook(CONTACT_UPDATED_RESUBSCRIBED_BODY, headers)

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"

    mock_supabase.table.return_value.update.assert_not_called()
    mock_supabase.table.return_value.insert.assert_not_called()


# =====================================================
# d) email not found in topspot_users is ignored successfully
# =====================================================

def test_contact_updated_unknown_email_is_ignored():
    mock_supabase = _mock_supabase_for_unknown_user()
    headers = _signed_headers(CONTACT_UPDATED_UNKNOWN_EMAIL_BODY)

    with patch("backend.routers.resend_webhook.supabase", mock_supabase), \
         patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": FAKE_WEBHOOK_SECRET}):
        response = _post_webhook(CONTACT_UPDATED_UNKNOWN_EMAIL_BODY, headers)

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "no_matching_user"

    mock_supabase.table.return_value.update.assert_not_called()
    mock_supabase.table.return_value.insert.assert_not_called()


# =====================================================
# e) missing Svix signature headers returns HTTP 400
# =====================================================

def test_missing_svix_headers_returns_400():
    mock_supabase = MagicMock()

    with patch("backend.routers.resend_webhook.supabase", mock_supabase), \
         patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": FAKE_WEBHOOK_SECRET}):
        response = client.post(
            "/api/webhooks/resend",
            content=CONTACT_UPDATED_UNSUBSCRIBED_BODY,
        )

    assert response.status_code == 400
    mock_supabase.table.assert_not_called()


# =====================================================
# f) invalid Svix signature returns HTTP 400
# =====================================================

def test_invalid_svix_signature_returns_400():
    mock_supabase = MagicMock()

    wrong_secret = "whsec_" + base64.b64encode(b"a-completely-different-secret!!").decode()
    headers = _signed_headers(CONTACT_UPDATED_UNSUBSCRIBED_BODY, secret=wrong_secret)

    with patch("backend.routers.resend_webhook.supabase", mock_supabase), \
         patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": FAKE_WEBHOOK_SECRET}):
        response = _post_webhook(CONTACT_UPDATED_UNSUBSCRIBED_BODY, headers)

    assert response.status_code == 400
    mock_supabase.table.assert_not_called()
