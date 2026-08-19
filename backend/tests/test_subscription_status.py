from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.isaiah.offer_access import OFFER_CODE
from backend.main import app


client = TestClient(app)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeSupabase:
    def __init__(self, *, user, subscription_rows=None, entitlement_rows=None, fail_entitlement=False):
        self.user = user
        self.subscription_rows = subscription_rows or []
        self.entitlement_rows = entitlement_rows or []
        self.fail_entitlement = fail_entitlement
        self.calls = []

    def table(self, name):
        self.calls.append({"table": name, "filters": [], "limit": None, "single": False})
        return FakeQuery(self, self.calls[-1])

    def execute(self, call):
        table = call["table"]
        if table == "topspot_users":
            return FakeResult(self.user)
        if table == "subscriptions":
            return FakeResult(self.subscription_rows)
        if table == "topspot_offer_entitlements":
            if self.fail_entitlement:
                raise RuntimeError("entitlement query failed")
            return FakeResult(self.entitlement_rows)
        return FakeResult(None)

    def calls_for(self, table):
        return [call for call in self.calls if call["table"] == table]


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

    def limit(self, value):
        self.call["limit"] = value
        return self

    def execute(self):
        return self.supabase.execute(self.call)


def entitlement(**overrides):
    now = datetime.now(timezone.utc)
    base = {
        "offer_code": OFFER_CODE,
        "free_access_expires_at": (now + timedelta(days=1)).isoformat(),
        "grace_access_expires_at": (now + timedelta(days=31)).isoformat(),
        "standard_transition_at": (now + timedelta(days=366)).isoformat(),
        "discount_consumed_at": None,
    }
    base.update(overrides)
    return base


def get_status(fake_supabase, user_id="topspot-user-123"):
    with patch("backend.isaiah.isaiah_router.decode_jwt_token") as mock_decode, \
            patch("backend.isaiah.isaiah_router.supabase", fake_supabase):
        mock_decode.return_value = {"user_id": user_id}
        response = client.get(
            "/api/subscription-status",
            cookies={"access_token": "fake_jwt"},
        )
    return response


def test_tester_bypass_returns_tester_fields_and_does_not_need_entitlement_access():
    fake_supabase = FakeSupabase(user={"id": "topspot-user-123", "is_tester": True})

    response = get_status(fake_supabase)

    assert response.status_code == 200
    assert response.json() == {
        "is_subscribed": True,
        "status": "tester",
        "access_state": "tester",
        "access_source": "tester",
        "requires_checkout": False,
    }
    assert fake_supabase.calls_for("topspot_offer_entitlements") == []


def test_active_stripe_returns_paid_fields_and_does_not_need_entitlement_access():
    fake_supabase = FakeSupabase(
        user={"id": "topspot-user-123", "is_tester": False},
        subscription_rows=[{
            "status": "active",
            "current_period_start": "2026-08-01T00:00:00+00:00",
            "current_period_end": "2026-09-01T00:00:00+00:00",
            "cancel_at_period_end": False,
        }],
    )

    response = get_status(fake_supabase)

    assert response.status_code == 200
    assert response.json() == {
        "is_subscribed": True,
        "status": "active",
        "access_state": "paid",
        "access_source": "stripe",
        "requires_checkout": False,
        "plan_kind": "standard",
        "current_period_start": "2026-08-01T00:00:00+00:00",
        "current_period_end": "2026-09-01T00:00:00+00:00",
        "cancel_at_period_end": False,
    }
    assert fake_supabase.calls_for("topspot_offer_entitlements") == []


def test_free_entitlement_returns_helper_free_2026_response():
    fake_supabase = FakeSupabase(
        user={"id": "topspot-user-123", "is_tester": False},
        entitlement_rows=[entitlement()],
    )

    response = get_status(fake_supabase)
    data = response.json()

    assert response.status_code == 200
    assert data["is_subscribed"] is True
    assert data["status"] == "free_2026"
    assert data["access_state"] == "free_2026"
    assert data["access_source"] == "offer"
    assert data["requires_checkout"] is False
    assert data["offer_code"] == OFFER_CODE


def test_grace_entitlement_returns_helper_grace_2027_response():
    now = datetime.now(timezone.utc)
    fake_supabase = FakeSupabase(
        user={"id": "topspot-user-123", "is_tester": False},
        entitlement_rows=[
            entitlement(
                free_access_expires_at=(now - timedelta(days=1)).isoformat(),
                grace_access_expires_at=(now + timedelta(days=1)).isoformat(),
            )
        ],
    )

    response = get_status(fake_supabase)
    data = response.json()

    assert response.status_code == 200
    assert data["is_subscribed"] is True
    assert data["status"] == "grace_2027"
    assert data["access_state"] == "grace_2027"
    assert data["access_source"] == "offer_grace"
    assert data["requires_checkout"] is True
    assert data["offer_code"] == OFFER_CODE


def test_expired_entitlement_returns_unsubscribed_expired():
    now = datetime.now(timezone.utc)
    fake_supabase = FakeSupabase(
        user={"id": "topspot-user-123", "is_tester": False},
        entitlement_rows=[
            entitlement(
                free_access_expires_at=(now - timedelta(days=2)).isoformat(),
                grace_access_expires_at=(now - timedelta(days=1)).isoformat(),
            )
        ],
    )

    response = get_status(fake_supabase)

    assert response.status_code == 200
    assert response.json()["is_subscribed"] is False
    assert response.json()["status"] == "expired"
    assert response.json()["access_state"] == "expired"


def test_no_entitlement_returns_inactive_none():
    fake_supabase = FakeSupabase(user={"id": "topspot-user-123", "is_tester": False})

    response = get_status(fake_supabase)

    assert response.status_code == 200
    assert response.json() == {
        "access_state": "none",
        "access_source": "none",
        "is_subscribed": False,
        "status": "inactive",
        "requires_checkout": True,
        "eligible_for_2027_discount": False,
        "discount_used": False,
        "discount_available": False,
    }


def test_entitlement_query_failure_returns_http_500():
    fake_supabase = FakeSupabase(
        user={"id": "topspot-user-123", "is_tester": False},
        fail_entitlement=True,
    )

    response = get_status(fake_supabase)

    assert response.status_code == 500
    assert response.json() == {"detail": "Could not determine subscription status"}


def test_canonical_jwt_user_id_is_used_in_entitlement_filter():
    fake_supabase = FakeSupabase(user={"id": "different-row-id", "is_tester": False})

    response = get_status(fake_supabase, user_id="canonical-jwt-user-id")

    assert response.status_code == 200
    entitlement_call = fake_supabase.calls_for("topspot_offer_entitlements")[0]
    assert ("user_id", "canonical-jwt-user-id") in entitlement_call["filters"]


def test_offer_code_filter_uses_offer_code_constant():
    fake_supabase = FakeSupabase(user={"id": "topspot-user-123", "is_tester": False})

    response = get_status(fake_supabase)

    assert response.status_code == 200
    entitlement_call = fake_supabase.calls_for("topspot_offer_entitlements")[0]
    assert ("offer_code", OFFER_CODE) in entitlement_call["filters"]
    assert entitlement_call["limit"] == 1


def test_existing_is_subscribed_compatibility_remains_intact():
    cases = [
        (FakeSupabase(user={"id": "u1", "is_tester": True}), True),
        (FakeSupabase(user={"id": "u1", "is_tester": False}, subscription_rows=[{"status": "active"}]), True),
        (FakeSupabase(user={"id": "u1", "is_tester": False}, entitlement_rows=[entitlement()]), True),
        (FakeSupabase(user={"id": "u1", "is_tester": False}), False),
    ]

    for fake_supabase, expected in cases:
        response = get_status(fake_supabase)

        assert response.status_code == 200
        assert response.json()["is_subscribed"] is expected
