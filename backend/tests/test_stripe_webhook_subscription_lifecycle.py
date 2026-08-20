from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


class FakeResult:
    def __init__(self, data=None):
        self.data = data


class FakeQuery:
    def __init__(self, supabase, table):
        self.supabase = supabase
        self.table = table
        self.filters = []
        self.updated = None
        self.inserted = None

    def select(self, *_args, **_kwargs):
        return self

    def insert(self, payload):
        self.inserted = payload
        self.supabase.calls.append(("insert", self.table, payload, []))
        return self

    def upsert(self, payload):
        self.supabase.calls.append(("upsert", self.table, payload, list(self.filters)))
        return self

    def update(self, payload):
        self.updated = payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        if self.updated is not None:
            self.supabase.calls.append(
                ("update", self.table, self.updated, list(self.filters))
            )

        if self.table == "topspot_users" and self.updated is None:
            return FakeResult([{"id": "topspot-user-123"}])

        return FakeResult([])


class FakeSupabase:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return FakeQuery(self, name)


def test_subscription_deleted_marks_subscription_canceled():
    fake_supabase = FakeSupabase()

    event = {
        "id": "evt_deleted_123",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_123",
                "cancel_at_period_end": True,
            }
        },
    }

    with patch(
        "backend.isaiah.isaiah_router.stripe.Webhook.construct_event",
        return_value=event,
    ), patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ):
        response = client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "fake-signature"},
        )

    assert response.status_code == 200

    subscription_updates = [
        call
        for call in fake_supabase.calls
        if call[0] == "update" and call[1] == "subscriptions"
    ]

    assert len(subscription_updates) == 1

    _, _, payload, filters = subscription_updates[0]

    assert payload["status"] == "canceled"
    assert ("stripe_subscription_id", "sub_123") in filters

def test_subscription_updated_with_cancel_at_period_end_stays_active_until_period_end():
    fake_supabase = FakeSupabase()

    subscription = {
        "id": "sub_123",
        "customer": "cus_123",
        "status": "active",
        "cancel_at_period_end": True,
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_123"
                    }
                }
            ]
        },
        "current_period_start": None,
        "current_period_end": None,
        "metadata": {
            "topspot_user_id": "topspot-user-123"
        },
    }

    event = {
        "id": "evt_updated_123",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_123",
                "customer": "cus_123",
            }
        },
    }

    with patch(
        "backend.isaiah.isaiah_router.stripe.Webhook.construct_event",
        return_value=event,
    ), patch(
        "backend.isaiah.isaiah_router.stripe.Subscription.retrieve",
        return_value=subscription,
    ), patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ):
        response = client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "fake-signature"},
        )

    assert response.status_code == 200

    subscription_upserts = [
        call
        for call in fake_supabase.calls
        if call[0] == "upsert" and call[1] == "subscriptions"
    ]

    assert len(subscription_upserts) == 1

    _, _, payload, _ = subscription_upserts[0]

    assert payload["status"] == "active"
    assert payload["cancel_at_period_end"] is True
