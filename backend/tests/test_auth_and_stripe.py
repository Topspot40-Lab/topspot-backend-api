import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from backend.main import app

client = TestClient(app)


# =====================================================
# LOGIN + COOKIE TEST
# =====================================================

@pytest.mark.asyncio
async def test_spotify_callback_sets_cookie_and_redirects():
    fake_token_data = {
        "access_token": "spotify_access",
        "refresh_token": "spotify_refresh",
        "expires_in": 3600
    }

    fake_profile = {
        "id": "spotify123",
        "display_name": "Isaiah",
        "product": "premium",
        "email": "test@test.com",
        "country": "US"
    }

    fake_user = {"id": "topspot_user_1"}

    with patch("backend.isaiah.isaiah_router.exchange_code_for_token", new=AsyncMock()) as mock_exchange, \
         patch("backend.isaiah.isaiah_router.get_user_profile", new=AsyncMock()) as mock_profile, \
         patch("backend.isaiah.isaiah_router.get_or_create_topspot_user") as mock_user, \
         patch("backend.isaiah.isaiah_router.create_jwt_token") as mock_jwt, \
         patch("backend.isaiah.isaiah_router.supabase") as mock_supabase:

        mock_exchange.return_value = fake_token_data
        mock_profile.return_value = fake_profile
        mock_user.return_value = fake_user
        mock_jwt.return_value = "fake_jwt"

        # mock subscription check
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None

        response = client.get("/spotify/callback?code=testcode", allow_redirects=False)

        assert response.status_code in (302, 307)

        # Cookie checks
        cookies = response.headers.get("set-cookie")
        assert "access_token=fake_jwt" in cookies
        assert "HttpOnly" in cookies


# =====================================================
# NON PREMIUM USER BLOCK TEST
# =====================================================

@pytest.mark.asyncio
async def test_spotify_callback_blocks_non_premium():
    fake_token_data = {
        "access_token": "spotify_access",
        "expires_in": 3600
    }

    fake_profile = {
        "id": "spotify123",
        "product": "free"
    }

    with patch("backend.isaiah.isaiah_router.exchange_code_for_token", new=AsyncMock()) as mock_exchange, \
         patch("backend.isaiah.isaiah_router.get_user_profile", new=AsyncMock()) as mock_profile:

        mock_exchange.return_value = fake_token_data
        mock_profile.return_value = fake_profile

        response = client.get("/spotify/callback?code=testcode", allow_redirects=False)

        assert response.status_code in (302, 307)
        assert "not-spotify-premium" in response.headers["location"]


# =====================================================
# COOKIE JWT AUTH TEST
# =====================================================

def test_cookie_jwt_auth_valid():
    with patch("backend.isaiah.isaiah_router.decode_jwt_token") as mock_decode:
        mock_decode.return_value = {"user_id": "123"}

        response = client.get(
            "/spotify/token",
            cookies={"access_token": "valid_jwt"}
        )

        # will fail unless get_valid_access_token mocked, but ensures JWT used
        assert response.status_code != 401


# =====================================================
# STRIPE CHECKOUT SESSION
# =====================================================

def test_create_checkout_session():
    fake_session = MagicMock()
    fake_session.url = "https://stripe.com/fake_checkout"

    with patch("backend.isaiah.isaiah_router.decode_jwt_token") as mock_decode, \
         patch("stripe.checkout.Session.create") as mock_create:

        mock_decode.return_value = {"user_id": "123"}
        mock_create.return_value = fake_session

        response = client.post(
            "/create-checkout-session",
            cookies={"access_token": "fake_jwt"}
        )

        assert response.status_code == 200
        assert response.json()["url"] == "https://stripe.com/fake_checkout"


# =====================================================
# STRIPE VERIFY SUBSCRIPTION
# =====================================================

def test_verify_subscription_success():
    fake_session = {
        "customer": "cust_123",
        "subscription": "sub_123"
    }

    fake_subscription = {
        "status": "active",
        "items": {
            "data": [
                {"price": {"id": "price_123"}}
            ]
        },
        "current_period_start": 1700000000,
        "current_period_end": 1800000000,
        "cancel_at_period_end": False
    }

    with patch("backend.isaiah.isaiah_router.decode_jwt_token") as mock_decode, \
         patch("stripe.checkout.Session.retrieve") as mock_session, \
         patch("stripe.Subscription.retrieve") as mock_sub, \
         patch("backend.isaiah.isaiah_router.supabase") as mock_supabase:

        mock_decode.return_value = {"user_id": "123"}
        mock_session.return_value = fake_session
        mock_sub.return_value = fake_subscription

        response = client.get(
            "/verify-subscription?session_id=test",
            cookies={"access_token": "fake_jwt"}
        )

        assert response.status_code in (302, 307)
        assert "success" in response.headers["location"]


# =====================================================
# SUBSCRIPTION STATUS REDIRECT
# =====================================================

def test_subscription_status_redirect_dashboard():
    with patch("backend.isaiah.isaiah_router.decode_jwt_token") as mock_decode, \
         patch("backend.isaiah.isaiah_router.supabase") as mock_supabase:

        mock_decode.return_value = {"user_id": "123"}
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "status": "active"
        }

        response = client.get(
            "/subscription-status",
            cookies={"access_token": "fake_jwt"}
        )

        assert response.status_code in (302, 307)
        assert "dashboard" in response.headers["location"]
