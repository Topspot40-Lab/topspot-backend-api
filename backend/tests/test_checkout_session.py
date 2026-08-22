from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_create_checkout_session_copies_user_id_to_subscription_metadata():
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/test"

    with patch(
        "backend.isaiah.isaiah_router.decode_jwt_token",
        return_value={"user_id": "topspot-user-123"},
    ), patch(
        "backend.isaiah.isaiah_router.STRIPE_PRICE_ID",
        "price_test_123",
    ), patch(
        "backend.isaiah.isaiah_router.stripe_config",
        {"secret_key": "sk_test_fake"},
    ), patch(
        "backend.isaiah.isaiah_router.stripe.checkout.Session.create",
        return_value=fake_session,
    ) as mock_create:
        response = client.post(
            "/api/create-checkout-session",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "url": "https://checkout.stripe.com/test"
    }

    kwargs = mock_create.call_args.kwargs

    assert kwargs["client_reference_id"] == "topspot-user-123"
    assert kwargs["metadata"] == {
        "topspot_user_id": "topspot-user-123"
    }
    assert kwargs["subscription_data"] == {
        "metadata": {
            "topspot_user_id": "topspot-user-123"
        }
    }


def test_create_checkout_session_reuses_existing_stripe_customer():
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/test"

    fake_user_result = MagicMock()
    fake_user_result.data = {
        "stripe_customer_id": "cus_topspot_123"
    }

    fake_supabase = MagicMock()
    fake_supabase.table.return_value \
        .select.return_value \
        .eq.return_value \
        .single.return_value \
        .execute.return_value = fake_user_result

    with patch(
        "backend.isaiah.isaiah_router.decode_jwt_token",
        return_value={"user_id": "topspot-user-123"},
    ), patch(
        "backend.isaiah.isaiah_router.STRIPE_PRICE_ID",
        "price_test_123",
    ), patch(
        "backend.isaiah.isaiah_router.stripe_config",
        {"secret_key": "sk_test_fake"},
    ), patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ), patch(
        "backend.isaiah.isaiah_router.stripe.checkout.Session.create",
        return_value=fake_session,
    ) as mock_create:
        response = client.post(
            "/api/create-checkout-session",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 200

    kwargs = mock_create.call_args.kwargs

    assert kwargs["customer"] == "cus_topspot_123"
