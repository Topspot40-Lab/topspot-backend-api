import pytest
from unittest.mock import AsyncMock, patch
from backend.isaiah.isaiah_spotify import (
    exchange_code_for_token,
    get_user_profile,
    get_valid_access_token,
    refresh_spotify_token
)


@pytest.mark.asyncio
async def test_exchange_code_for_token_success():
    fake_response = {
        "access_token": "abc123",
        "refresh_token": "refresh123",
        "expires_in": 3600
    }

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = fake_response

        result = await exchange_code_for_token("fake_code", "http://localhost")

        assert result["access_token"] == "abc123"
        assert result["refresh_token"] == "refresh123"


@pytest.mark.asyncio
async def test_get_user_profile():
    fake_profile = {
        "id": "spotify_user",
        "display_name": "Isaiah",
        "product": "premium"
    }

    with patch("httpx.AsyncClient.get", new=AsyncMock()) as mock_get:
        mock_get.return_value.json.return_value = fake_profile
        mock_get.return_value.status_code = 200

        result = await get_user_profile("fake_access_token")

        assert result["id"] == "spotify_user"
        assert result["product"] == "premium"


@pytest.mark.asyncio
async def test_refresh_spotify_token():
    fake_refresh = {
        "access_token": "new_token",
        "expires_in": 3600
    }

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        mock_post.return_value.json.return_value = fake_refresh
        mock_post.return_value.status_code = 200

        result = await refresh_spotify_token("fake_refresh")

        assert result["access_token"] == "new_token"
