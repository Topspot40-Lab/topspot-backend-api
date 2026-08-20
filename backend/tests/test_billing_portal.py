from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeSupabase:
    def __init__(self, user):
        self.user = user
        self.calls = []

    def table(self, name):
        self.calls.append({
            "table": name,
            "filters": [],
            "single": False,
        })
        return FakeQuery(self, self.calls[-1])

    def execute(self, call):
        if call["table"] == "topspot_users":
            return FakeResult(self.user)
        return FakeResult(None)


class FakeQuery:
    def __init__(self, supabase, call):
        self.supabase = supabase
        self.call = call

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self.call["filters"].append((column, value))
        return self

    def single(self):
        self.call["single"] = True
        return self

    def execute(self):
        return self.supabase.execute(self.call)


def test_create_billing_portal_session_uses_authenticated_users_stripe_customer():
    fake_supabase = FakeSupabase({
        "id": "topspot-user-123",
        "stripe_customer_id": "cus_topspot_123",
    })

    fake_portal_session = MagicMock()
    fake_portal_session.url = "https://billing.stripe.com/p/session/test"

    with patch(
        "backend.isaiah.isaiah_router.decode_jwt_token",
        return_value={"user_id": "topspot-user-123"},
    ), patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ), patch(
        "backend.isaiah.isaiah_router.stripe.billing_portal.Session.create",
        return_value=fake_portal_session,
    ) as mock_create:
        response = client.post(
            "/api/create-billing-portal-session",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "url": "https://billing.stripe.com/p/session/test"
    }

    mock_create.assert_called_once_with(
        customer="cus_topspot_123",
        return_url="https://topspot40.com/dashboard",
    )

    user_call = fake_supabase.calls[0]
    assert user_call["table"] == "topspot_users"
    assert ("id", "topspot-user-123") in user_call["filters"]

def test_create_billing_portal_session_rejects_invalid_session():
    with patch(
        "backend.isaiah.isaiah_router.decode_jwt_token",
        return_value=None,
    ), patch(
        "backend.isaiah.isaiah_router.stripe.billing_portal.Session.create"
    ) as mock_create:
        response = client.post(
            "/api/create-billing-portal-session",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid or expired JWT Session"
    }
    mock_create.assert_not_called()


def test_create_billing_portal_session_returns_404_when_user_missing():
    fake_supabase = FakeSupabase(None)

    with patch(
        "backend.isaiah.isaiah_router.decode_jwt_token",
        return_value={"user_id": "topspot-user-123"},
    ), patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ), patch(
        "backend.isaiah.isaiah_router.stripe.billing_portal.Session.create"
    ) as mock_create:
        response = client.post(
            "/api/create-billing-portal-session",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "User not found"
    }
    mock_create.assert_not_called()


def test_create_billing_portal_session_rejects_user_without_stripe_customer():
    fake_supabase = FakeSupabase({
        "id": "topspot-user-123",
        "stripe_customer_id": None,
    })

    with patch(
        "backend.isaiah.isaiah_router.decode_jwt_token",
        return_value={"user_id": "topspot-user-123"},
    ), patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ), patch(
        "backend.isaiah.isaiah_router.stripe.billing_portal.Session.create"
    ) as mock_create:
        response = client.post(
            "/api/create-billing-portal-session",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "No Stripe customer found for this account"
    }
    mock_create.assert_not_called()

def test_create_billing_portal_session_handles_stripe_failure():
    fake_supabase = FakeSupabase({
        "id": "topspot-user-123",
        "stripe_customer_id": "cus_topspot_123",
    })

    with patch(
        "backend.isaiah.isaiah_router.decode_jwt_token",
        return_value={"user_id": "topspot-user-123"},
    ), patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ), patch(
        "backend.isaiah.isaiah_router.stripe.billing_portal.Session.create",
        side_effect=RuntimeError("simulated Stripe failure"),
    ):
        response = client.post(
            "/api/create-billing-portal-session",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Could not create billing portal session"
    }
