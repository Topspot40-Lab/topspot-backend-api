import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from backend.main import app

client = TestClient(app)


def test_spotify_login_redirect():
    response = client.get("/spotify/login", allow_redirects=False)
    assert response.status_code in (302, 307)
    assert "accounts.spotify.com" in response.headers["location"]


@pytest.mark.asyncio
async def test_spotify_token_endpoint():
    with patch("backend.isaiah.isaiah_router.decode_jwt_token") as mock_decode, \
         patch("backend.isaiah.isaiah_router.get_valid_access_token", new=AsyncMock()) as mock_valid:

        mock_decode.return_value = {"user_id": "123"}
        mock_valid.return_value = "spotify_token_abc"

        response = client.get(
            "/spotify/token",
            cookies={"access_token": "fake_jwt"}
        )

        assert response.status_code == 200
        assert response.json()["access_token"] == "spotify_token_abc"


@pytest.mark.asyncio
async def test_spotify_sdk_token():
    with patch("backend.isaiah.isaiah_router.decode_jwt_token") as mock_decode, \
         patch("backend.isaiah.isaiah_router.get_valid_access_token", new=AsyncMock()) as mock_valid:

        mock_decode.return_value = {"user_id": "123"}
        mock_valid.return_value = "sdk_token_abc"

        response = client.get(
            "/spotify/sdk-token",
            cookies={"access_token": "fake_jwt"}
        )

        assert response.status_code == 200
        assert response.json()["access_token"] == "sdk_token_abc"
