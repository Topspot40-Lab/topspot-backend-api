import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

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

    def is_(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, _value):
        return self

    def execute(self):
        if self.updated is not None:
            self.supabase.calls.append(
                ("update", self.table, self.updated, list(self.filters))
            )

        if self.table == "topspot_users" and self.updated is None:
            return FakeResult([{"id": "topspot-user-123"}])

        if self.table == "topspot_offer_entitlements" and self.updated is None:
            return FakeResult([{
                "standard_transition_at": "2028-01-01T06:00:00+00:00"
            }])

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

def test_invoice_payment_failed_uses_basil_parent_subscription():
    fake_supabase = FakeSupabase()

    event = {
        "id": "evt_payment_failed_123",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "id": "in_123",
                "parent": {
                    "type": "subscription_details",
                    "subscription_details": {
                        "subscription": "sub_123"
                    }
                }
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

    assert payload["status"] == "past_due"
    assert ("stripe_subscription_id", "sub_123") in filters

def test_invoice_payment_succeeded_uses_basil_parent_subscription():
    fake_supabase = FakeSupabase()

    subscription = {
        "id": "sub_123",
        "customer": "cus_123",
        "status": "active",
        "cancel_at_period_end": False,
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
        "id": "evt_payment_succeeded_123",
        "type": "invoice.payment_succeeded",
        "data": {
            "object": {
                "id": "in_123",
                "parent": {
                    "type": "subscription_details",
                    "subscription_details": {
                        "subscription": "sub_123"
                    }
                }
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

    assert payload["stripe_subscription_id"] == "sub_123"
    assert payload["status"] == "active"



def test_subscription_updated_uses_basil_item_period_dates():
    fake_supabase = FakeSupabase()

    subscription = {
        "id": "sub_123",
        "customer": "cus_123",
        "status": "active",
        "cancel_at_period_end": False,
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_123"
                    },
                    "current_period_start": 1767225600,
                    "current_period_end": 1769904000,
                }
            ]
        },
        "metadata": {
            "topspot_user_id": "topspot-user-123"
        },
    }

    event = {
        "id": "evt_updated_period_123",
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

    assert payload["current_period_start"] == "2026-01-01T00:00:00+00:00"
    assert payload["current_period_end"] == "2026-02-01T00:00:00+00:00"


def test_invoice_paid_uses_basil_parent_subscription():
    fake_supabase = FakeSupabase()

    subscription = {
        "id": "sub_123",
        "customer": "cus_123",
        "status": "active",
        "cancel_at_period_end": False,
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_123"
                    },
                    "current_period_start": 1767225600,
                    "current_period_end": 1769904000,
                }
            ]
        },
        "metadata": {
            "topspot_user_id": "topspot-user-123"
        },
    }

    event = {
        "id": "evt_invoice_paid_123",
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": "in_123",
                "parent": {
                    "type": "subscription_details",
                    "subscription_details": {
                        "subscription": "sub_123"
                    }
                },
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

    assert payload["stripe_subscription_id"] == "sub_123"
    assert payload["status"] == "active"


def test_invoice_paid_consumes_2027_promotional_discount():
    fake_supabase = FakeSupabase()

    subscription = {
        "id": "sub_promo_123",
        "customer": "cus_promo_123",
        "status": "active",
        "cancel_at_period_end": False,
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_promo_monthly"
                    },
                    "current_period_start": 1767225600,
                    "current_period_end": 1769904000,
                }
            ]
        },
        "metadata": {
            "topspot_user_id": "topspot-user-123",
            "topspot_plan_kind": "promo_2027_monthly",
        },
    }

    event = {
        "id": "evt_invoice_paid_promo_123",
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": "in_promo_123",
                "parent": {
                    "type": "subscription_details",
                    "subscription_details": {
                        "subscription": "sub_promo_123"
                    }
                },
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

    entitlement_updates = [
        call
        for call in fake_supabase.calls
        if call[0] == "update" and call[1] == "topspot_offer_entitlements"
    ]

    assert len(entitlement_updates) == 1

    _, _, payload, filters = entitlement_updates[0]

    assert payload["discount_redeemed_at"]
    assert payload["discount_consumed_at"]
    assert payload["discount_redeemed_at"] == payload["discount_consumed_at"]
    assert payload["discount_stripe_subscription_id"] == "sub_promo_123"
    assert payload["discount_stripe_customer_id"] == "cus_promo_123"

    assert ("user_id", "topspot-user-123") in filters
    assert ("offer_code", "topspot_2026_free_2027_discount") in filters
    assert ("discount_consumed_at", None) in filters


def test_create_2027_promo_monthly_schedule_preserves_billing_anchor():
    from backend.isaiah import isaiah_router

    fake_supabase = FakeSupabase()

    subscription = {
        "id": "sub_promo_monthly_123",
        "schedule": None,
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_promo_monthly"
                    }
                }
            ]
        },
        "metadata": {
            "topspot_user_id": "topspot-user-123",
            "topspot_plan_kind": "promo_2027_monthly",
        },
    }

    schedule = {
        "id": "sub_sched_monthly_123",
        "current_phase": {
            "start_date": 1799985600,
            "end_date": 1802664000,
        },
    }

    with patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ), patch(
        "backend.isaiah.isaiah_router.STRIPE_STANDARD_MONTHLY_PRICE_ID",
        "price_standard_monthly",
    ), patch(
        "backend.isaiah.isaiah_router.stripe.SubscriptionSchedule.create",
        return_value=schedule,
    ) as create_schedule, patch(
        "backend.isaiah.isaiah_router.stripe.SubscriptionSchedule.modify",
    ) as modify_schedule:
        isaiah_router.create_2027_promo_subscription_schedule_if_applicable(
            subscription,
            "topspot-user-123",
        )

    create_schedule.assert_called_once_with(
        from_subscription="sub_promo_monthly_123",
        metadata={
            "topspot_user_id": "topspot-user-123",
            "topspot_plan_kind": "promo_2027_monthly",
        },
    )

    modify_schedule.assert_called_once()
    schedule_id, = modify_schedule.call_args.args
    kwargs = modify_schedule.call_args.kwargs

    assert schedule_id == "sub_sched_monthly_123"
    assert kwargs["end_behavior"] == "release"
    assert kwargs["proration_behavior"] == "none"

    phases = kwargs["phases"]
    assert len(phases) == 2

    current_phase = phases[0]
    future_phase = phases[1]

    assert current_phase["start_date"] == 1799985600
    assert current_phase["end_date"] == 1830319200
    assert current_phase["items"] == [{
        "price": "price_promo_monthly",
        "quantity": 1,
    }]
    assert current_phase["proration_behavior"] == "none"

    assert future_phase["start_date"] == 1830319200
    assert future_phase["duration"] == {
        "interval": "year",
        "interval_count": 1,
    }
    assert future_phase["items"] == [{
        "price": "price_standard_monthly",
        "quantity": 1,
    }]
    assert future_phase["proration_behavior"] == "none"
    assert "billing_cycle_anchor" not in future_phase


def test_create_2027_promo_annual_schedule_resets_billing_anchor():
    from backend.isaiah import isaiah_router

    fake_supabase = FakeSupabase()

    subscription = {
        "id": "sub_promo_annual_123",
        "schedule": None,
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_promo_annual"
                    }
                }
            ]
        },
        "metadata": {
            "topspot_user_id": "topspot-user-123",
            "topspot_plan_kind": "promo_2027_annual",
        },
    }

    schedule = {
        "id": "sub_sched_annual_123",
        "current_phase": {
            "start_date": 1799985600,
            "end_date": 1831521600,
        },
    }

    with patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ), patch(
        "backend.isaiah.isaiah_router.STRIPE_STANDARD_ANNUAL_PRICE_ID",
        "price_standard_annual",
    ), patch(
        "backend.isaiah.isaiah_router.stripe.SubscriptionSchedule.create",
        return_value=schedule,
    ) as create_schedule, patch(
        "backend.isaiah.isaiah_router.stripe.SubscriptionSchedule.modify",
    ) as modify_schedule:
        isaiah_router.create_2027_promo_subscription_schedule_if_applicable(
            subscription,
            "topspot-user-123",
        )

    create_schedule.assert_called_once_with(
        from_subscription="sub_promo_annual_123",
        metadata={
            "topspot_user_id": "topspot-user-123",
            "topspot_plan_kind": "promo_2027_annual",
        },
    )

    modify_schedule.assert_called_once()
    schedule_id, = modify_schedule.call_args.args
    kwargs = modify_schedule.call_args.kwargs

    assert schedule_id == "sub_sched_annual_123"
    assert kwargs["end_behavior"] == "release"
    assert kwargs["proration_behavior"] == "none"

    phases = kwargs["phases"]
    assert len(phases) == 2

    current_phase = phases[0]
    future_phase = phases[1]

    assert current_phase["start_date"] == 1799985600
    assert current_phase["end_date"] == 1830319200
    assert current_phase["items"] == [{
        "price": "price_promo_annual",
        "quantity": 1,
    }]
    assert current_phase["proration_behavior"] == "none"

    assert future_phase["start_date"] == 1830319200
    assert future_phase["duration"] == {
        "interval": "year",
        "interval_count": 1,
    }
    assert future_phase["items"] == [{
        "price": "price_standard_annual",
        "quantity": 1,
    }]
    assert future_phase["proration_behavior"] == "none"
    assert future_phase["billing_cycle_anchor"] == "phase_start"


def test_create_2027_promo_schedule_reuses_existing_schedule():
    from backend.isaiah import isaiah_router

    fake_supabase = FakeSupabase()

    subscription = {
        "id": "sub_promo_retry_123",
        "schedule": "sub_sched_existing_123",
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_promo_monthly"
                    }
                }
            ]
        },
        "metadata": {
            "topspot_user_id": "topspot-user-123",
            "topspot_plan_kind": "promo_2027_monthly",
        },
    }

    schedule = {
        "id": "sub_sched_existing_123",
        "current_phase": {
            "start_date": 1799985600,
            "end_date": 1802664000,
        },
    }

    with patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ), patch(
        "backend.isaiah.isaiah_router.STRIPE_STANDARD_MONTHLY_PRICE_ID",
        "price_standard_monthly",
    ), patch(
        "backend.isaiah.isaiah_router.stripe.SubscriptionSchedule.retrieve",
        return_value=schedule,
    ) as retrieve_schedule, patch(
        "backend.isaiah.isaiah_router.stripe.SubscriptionSchedule.create",
    ) as create_schedule, patch(
        "backend.isaiah.isaiah_router.stripe.SubscriptionSchedule.modify",
    ) as modify_schedule:
        isaiah_router.create_2027_promo_subscription_schedule_if_applicable(
            subscription,
            "topspot-user-123",
        )

    retrieve_schedule.assert_called_once_with("sub_sched_existing_123")
    create_schedule.assert_not_called()
    modify_schedule.assert_called_once()


def test_webhook_processing_failure_removes_event_marker_for_retry():
    from backend.isaiah import isaiah_router

    class DeleteTrackingQuery:
        def __init__(self, table_name, calls):
            self.table_name = table_name
            self.calls = calls
            self.deleted = False
            self.filters = []

        def insert(self, payload):
            self.calls.append(("insert", self.table_name, payload))
            return self

        def delete(self):
            self.deleted = True
            self.calls.append(("delete", self.table_name))
            return self

        def eq(self, column, value):
            self.filters.append((column, value))
            self.calls.append(("eq", self.table_name, column, value))
            return self

        def execute(self):
            self.calls.append(("execute", self.table_name, self.deleted, tuple(self.filters)))

            if self.table_name == "topspot_users":
                raise RuntimeError("forced processing failure")

            return FakeResult([])

    class DeleteTrackingSupabase:
        def __init__(self):
            self.calls = []

        def table(self, table_name):
            return DeleteTrackingQuery(table_name, self.calls)

    fake_supabase = DeleteTrackingSupabase()

    event = {
        "id": "evt_retry_cleanup_123",
        "type": "invoice.paid",
        "data": {
            "object": {
                "subscription": "sub_retry_cleanup_123",
            }
        },
    }

    subscription = {
        "id": "sub_retry_cleanup_123",
        "customer": "cus_retry_cleanup_123",
        "metadata": {},
    }

    request = MagicMock()
    request.body = AsyncMock(return_value=b"{}")
    request.headers = {"stripe-signature": "sig_test"}

    with patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ), patch(
        "backend.isaiah.isaiah_router.stripe.Webhook.construct_event",
        return_value=event,
    ), patch(
        "backend.isaiah.isaiah_router.stripe.Subscription.retrieve",
        return_value=subscription,
    ):
        response = asyncio.run(isaiah_router.stripe_webhook(request))

    assert response.status_code == 500

    assert (
        "delete",
        "stripe_webhook_events",
    ) in fake_supabase.calls

    assert (
        "eq",
        "stripe_webhook_events",
        "id",
        "evt_retry_cleanup_123",
    ) in fake_supabase.calls
