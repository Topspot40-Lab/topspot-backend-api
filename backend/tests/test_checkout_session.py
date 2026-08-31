from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_create_checkout_session_copies_user_id_to_subscription_metadata():
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/test"

    user_result = MagicMock()
    user_result.data = {
        "stripe_customer_id": None
    }

    entitlement_result = MagicMock()
    entitlement_result.data = []

    fake_supabase = _checkout_supabase(
        user_result,
        entitlement_result,
    )

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

    entitlement_result = MagicMock()
    entitlement_result.data = []

    fake_supabase = _checkout_supabase(
        fake_user_result,
        entitlement_result,
    )

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



def _checkout_supabase(user_result, entitlement_result):
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.single.return_value = query
    query.limit.return_value = query
    query.execute.side_effect = [user_result, entitlement_result]

    fake_supabase = MagicMock()
    fake_supabase.table.return_value = query
    return fake_supabase


def test_create_checkout_session_blocks_free_2026_standard_checkout():
    user_result = MagicMock()
    user_result.data = {
        "stripe_customer_id": None
    }

    entitlement_result = MagicMock()
    entitlement_result.data = [
        {
            "offer_code": "topspot_2026_free_2027_discount"
        }
    ]

    fake_supabase = _checkout_supabase(
        user_result,
        entitlement_result,
    )

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
        "backend.isaiah.isaiah_router.compute_offer_access",
        return_value={
            "access_state": "free_2026",
            "requires_checkout": False,
        },
    ), patch(
        "backend.isaiah.isaiah_router.stripe.checkout.Session.create",
    ) as mock_create:
        response = client.post(
            "/api/create-checkout-session",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 403
    mock_create.assert_not_called()


def test_create_checkout_session_blocks_grace_2027_standard_checkout():
    user_result = MagicMock()
    user_result.data = {
        "stripe_customer_id": "cus_topspot_123"
    }

    entitlement_result = MagicMock()
    entitlement_result.data = [
        {
            "offer_code": "topspot_2026_free_2027_discount"
        }
    ]

    fake_supabase = _checkout_supabase(
        user_result,
        entitlement_result,
    )

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
        "backend.isaiah.isaiah_router.compute_offer_access",
        return_value={
            "access_state": "grace_2027",
            "requires_checkout": True,
        },
    ), patch(
        "backend.isaiah.isaiah_router.stripe.checkout.Session.create",
    ) as mock_create:
        response = client.post(
            "/api/create-checkout-session",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 403
    mock_create.assert_not_called()


def test_active_complimentary_user_cannot_open_standard_checkout():
    user_result = MagicMock()
    user_result.data = {
        "stripe_customer_id": None,
        "complimentary_access": True,
        "complimentary_access_expires_at": None,
        "complimentary_access_reason": "Lifetime award",
    }
    entitlement_result = MagicMock()
    entitlement_result.data = []
    fake_supabase = _checkout_supabase(user_result, entitlement_result)

    with patch("backend.isaiah.isaiah_router.decode_jwt_token", return_value={"user_id": "topspot-user-123"}), patch(
        "backend.isaiah.isaiah_router.STRIPE_PRICE_ID", "price_test_123"
    ), patch("backend.isaiah.isaiah_router.stripe_config", {"secret_key": "sk_test_fake"}), patch(
        "backend.isaiah.isaiah_router.supabase", fake_supabase
    ), patch("backend.isaiah.isaiah_router.stripe.checkout.Session.create") as mock_create:
        response = client.post("/api/create-checkout-session", cookies={"access_token": "fake_jwt"})

    assert response.status_code == 403
    mock_create.assert_not_called()


def test_active_complimentary_user_cannot_open_early_checkout():
    user_result = MagicMock()
    user_result.data = {
        "stripe_customer_id": None,
        "complimentary_access": True,
        "complimentary_access_expires_at": None,
        "complimentary_access_reason": "Lifetime award",
    }
    entitlement_result = MagicMock()
    entitlement_result.data = [
        {"offer_code": "topspot_2026_free_2027_discount"}
    ]
    fake_supabase = _checkout_supabase(user_result, entitlement_result)

    with patch("backend.isaiah.isaiah_router.decode_jwt_token", return_value={"user_id": "topspot-user-123"}), patch(
        "backend.isaiah.isaiah_router.stripe_config", {"secret_key": "sk_test_fake"}
    ), patch("backend.isaiah.isaiah_router.supabase", fake_supabase), patch(
        "backend.isaiah.isaiah_router.stripe.checkout.Session.create"
    ) as mock_create:
        response = client.post(
            "/api/create-2027-promo-checkout-session?plan=monthly",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 403
    mock_create.assert_not_called()



def test_create_2027_promo_checkout_uses_monthly_promo_price():
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/promo-monthly"

    user_result = MagicMock()
    user_result.data = {
        "stripe_customer_id": "cus_topspot_123"
    }

    entitlement_result = MagicMock()
    entitlement_result.data = [
        {
            "offer_code": "topspot_2026_free_2027_discount"
        }
    ]

    fake_supabase = _checkout_supabase(
        user_result,
        entitlement_result,
    )

    with patch(
        "backend.isaiah.isaiah_router.decode_jwt_token",
        return_value={"user_id": "topspot-user-123"},
    ), patch(
        "backend.isaiah.isaiah_router.stripe_config",
        {"secret_key": "sk_test_fake"},
    ), patch(
        "backend.isaiah.isaiah_router.STRIPE_2027_PROMO_MONTHLY_PRICE_ID",
        "price_promo_monthly",
    ), patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ), patch(
        "backend.isaiah.isaiah_router.compute_offer_access",
        return_value={
            "access_state": "grace_2027",
            "discount_available": True,
        },
    ), patch(
        "backend.isaiah.isaiah_router.stripe.checkout.Session.create",
        return_value=fake_session,
    ) as mock_create:
        response = client.post(
            "/api/create-2027-promo-checkout-session?plan=monthly",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 200

    kwargs = mock_create.call_args.kwargs
    assert kwargs["line_items"][0]["price"] == "price_promo_monthly"
    assert kwargs["metadata"]["topspot_plan_kind"] == "promo_2027_monthly"
    assert kwargs["subscription_data"]["metadata"]["topspot_plan_kind"] == "promo_2027_monthly"


def test_create_2027_promo_checkout_uses_annual_promo_price():
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/promo-annual"

    user_result = MagicMock()
    user_result.data = {
        "stripe_customer_id": "cus_topspot_123"
    }

    entitlement_result = MagicMock()
    entitlement_result.data = [
        {
            "offer_code": "topspot_2026_free_2027_discount"
        }
    ]

    fake_supabase = _checkout_supabase(
        user_result,
        entitlement_result,
    )

    with patch(
        "backend.isaiah.isaiah_router.decode_jwt_token",
        return_value={"user_id": "topspot-user-123"},
    ), patch(
        "backend.isaiah.isaiah_router.stripe_config",
        {"secret_key": "sk_test_fake"},
    ), patch(
        "backend.isaiah.isaiah_router.STRIPE_2027_PROMO_ANNUAL_PRICE_ID",
        "price_promo_annual",
    ), patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ), patch(
        "backend.isaiah.isaiah_router.compute_offer_access",
        return_value={
            "access_state": "grace_2027",
            "discount_available": True,
        },
    ), patch(
        "backend.isaiah.isaiah_router.stripe.checkout.Session.create",
        return_value=fake_session,
    ) as mock_create:
        response = client.post(
            "/api/create-2027-promo-checkout-session?plan=annual",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 200

    kwargs = mock_create.call_args.kwargs
    assert kwargs["line_items"][0]["price"] == "price_promo_annual"
    assert kwargs["metadata"]["topspot_plan_kind"] == "promo_2027_annual"
    assert kwargs["subscription_data"]["metadata"]["topspot_plan_kind"] == "promo_2027_annual"


def test_create_2027_promo_checkout_rejects_non_grace_user():
    user_result = MagicMock()
    user_result.data = {
        "stripe_customer_id": None
    }

    entitlement_result = MagicMock()
    entitlement_result.data = [
        {
            "offer_code": "topspot_2026_free_2027_discount"
        }
    ]

    fake_supabase = _checkout_supabase(
        user_result,
        entitlement_result,
    )

    with patch(
        "backend.isaiah.isaiah_router.decode_jwt_token",
        return_value={"user_id": "topspot-user-123"},
    ), patch(
        "backend.isaiah.isaiah_router.stripe_config",
        {"secret_key": "sk_test_fake"},
    ), patch(
        "backend.isaiah.isaiah_router.supabase",
        fake_supabase,
    ), patch(
        "backend.isaiah.isaiah_router.compute_offer_access",
        return_value={
            "access_state": "free_2026",
            "discount_available": True,
        },
    ), patch(
        "backend.isaiah.isaiah_router.stripe.checkout.Session.create",
    ) as mock_create:
        response = client.post(
            "/api/create-2027-promo-checkout-session?plan=monthly",
            cookies={"access_token": "fake_jwt"},
        )

    assert response.status_code == 403
    mock_create.assert_not_called()
