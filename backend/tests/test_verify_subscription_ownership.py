from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def _checkout_session(*, client_reference_id, metadata):
    return {
        "client_reference_id": client_reference_id,
        "metadata": metadata,
        "customer": "cus_topspot_123",
        "subscription": "sub_topspot_123",
    }


def _verify(session):
    with patch(
        "backend.isaiah.isaiah_router.decode_jwt_token",
        return_value={"user_id": "topspot-user-123"},
    ), patch(
        "backend.isaiah.isaiah_router.stripe.checkout.Session.retrieve",
        return_value=session,
    ) as retrieve_session, patch(
        "backend.isaiah.isaiah_router.stripe.Subscription.retrieve",
        return_value={"id": "sub_topspot_123", "status": "active"},
    ) as retrieve_subscription:
        response = client.get(
            "/api/verify-subscription?session_id=cs_test_123",
            cookies={"access_token": "fake_jwt"},
        )

    return response, retrieve_session, retrieve_subscription


def test_verify_subscription_accepts_session_owned_by_caller():
    response, _, retrieve_subscription = _verify(
        _checkout_session(
            client_reference_id="topspot-user-123",
            metadata={"topspot_user_id": "topspot-user-123"},
        )
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "active",
        "subscription_id": "sub_topspot_123",
        "is_active": True,
    }
    retrieve_subscription.assert_called_once_with("sub_topspot_123")


@pytest.mark.parametrize(
    "session",
    [
        _checkout_session(
            client_reference_id="another-user",
            metadata={"topspot_user_id": "another-user"},
        ),
        _checkout_session(client_reference_id="topspot-user-123", metadata={}),
        _checkout_session(
            client_reference_id="topspot-user-123",
            metadata={"topspot_user_id": "another-user"},
        ),
        _checkout_session(client_reference_id="topspot-user-123", metadata="not-a-mapping"),
    ],
    ids=["another-user", "missing-ownership", "conflicting-ownership", "malformed-ownership"],
)
def test_verify_subscription_rejects_untrusted_checkout_session_owner(session):
    response, retrieve_session, retrieve_subscription = _verify(session)

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Checkout session is not authorized for this account"
    }
    retrieve_session.assert_called_once_with("cs_test_123")
    retrieve_subscription.assert_not_called()
