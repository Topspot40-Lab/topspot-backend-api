# Spotify file is meant for Auth and Track logic
import os 
import httpx 
from dotenv import load_dotenv
from supabase import create_client
import base64 
from datetime import datetime, timezone, timedelta
import logging


# Configure logging once, at the top of your app
logging.basicConfig(
    level=logging.INFO,  # DEBUG gives you everything (INFO, WARNING, ERROR, etc.)
    format="%(asctime)s [%(levelname)s] %(message)s"
)
# logger = logging.getLogger(__name__)
logger = logging.getLogger("playlist")  # custom logger for your app
logging.getLogger("httpx").setLevel(logging.DEBUG)
logging.getLogger("httpcore").setLevel(logging.DEBUG)

# from typing import Any

load_dotenv()


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

client_id = os.getenv("SPOTIPY_CLIENT_ID")
client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_ME_URL = "https://api.spotify.com/v1/me"



AUTH_URL = "https://accounts.spotify.com/api/token"



async def get_access_token():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            AUTH_URL,
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
        )
        response.raise_for_status()
        return response.json()["access_token"]
    

async def fetch_track_preview(track_id: str):
    token = await get_access_token()
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"https://api.spotify.com/v1/tracks/{track_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        res.raise_for_status()
        data = res.json()
        return {
            "track_name": data["name"],
            "artist": data["artists"][0]["name"],
            "preview_url": data["preview_url"],
            "album_image": data["album"]["images"][0]["url"],
            "album_name": data["album"]["name"]
        }

async def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    """
    Exchange authorization code for access and refresh tokens.
    """
    async with httpx.AsyncClient() as client:
        #debug statements 
        print(f"CLIENT_ID: {client_id}")
        print(f"CLIENT_SECRET is set: {bool(client_secret)}")

        auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        #DEBUG STATEMENT 
        print("POSTing to token URL:", SPOTIFY_TOKEN_URL)
        print("Headers:", headers)
        print("Data:", data)

        response = await client.post(SPOTIFY_TOKEN_URL, headers=headers, data=data)
        if response.status_code != 200:
            print("Spotify error response:", response.text)
        response.raise_for_status()
        return response.json()

async def get_user_profile(access_token: str) -> dict:
    """
    Get Spotify user profile with the access token.
    """
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = await client.get(SPOTIFY_ME_URL, headers=headers)
        response.raise_for_status()
        return response.json()





# checks if the spotify tokens that's stored in supabase of the user is still active from the supabase
"""
Fetches the token record from Supabase.

Parses expires_at as a timezone-aware datetime.

Checks whether the token is expired.

If expired, calls refresh_spotify_token() to get a new one.

Updates the Supabase record with the new access_token and expires_at.

Returns a valid token either way.

And make it async function so that it works everywhere else
"""
async def get_valid_access_token(user_id: str):
    record = supabase.table("spotify_tokens").select("*").eq("user_id", user_id).single().execute().data
    if not record:
        raise Exception("No tokens found for user")

    expires_at = datetime.fromisoformat(record["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        # Token expired — refresh it
        refresh_token = record["refresh_token"]
        refreshed = await refresh_spotify_token(refresh_token)
        new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=refreshed["expires_in"])

        # Update in Supabase
        supabase.table("spotify_tokens").update({
            "access_token": refreshed["access_token"],
            "expires_at": new_expires_at.isoformat()
        }).eq("user_id", user_id).execute()

        return refreshed["access_token"]
    else:
        # Still valid
        return record["access_token"]
    


async def refresh_spotify_token(refresh_token: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://accounts.spotify.com/api/token",
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": os.getenv("SPOTIPY_CLIENT_ID"),
                "client_secret": os.getenv("SPOTIPY_CLIENT_SECRET"),
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        resp.raise_for_status()
        return resp.json()
    
