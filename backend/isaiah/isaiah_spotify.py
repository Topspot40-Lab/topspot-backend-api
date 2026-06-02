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
        logger.critical("=== TOKEN EXCHANGE START ===")
        print(f"CLIENT_ID: {client_id}")
        logger.critical("CLIENT_ID EXISTS: %s", bool(client_id))
        print(f"CLIENT_SECRET is set: {bool(client_secret)}")
        logger.critical("CLIENT_SECRET EXISTS: %s", bool(client_secret))
        

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
        logger.critical("REDIRECT_URI: %s", redirect_uri)
        logger.critical("CODE PREFIX: %s", code[:20])
        print("POSTing to token URL:", SPOTIFY_TOKEN_URL)
        print("Headers:", headers)
        print("Data:", data)

        logger.critical("POSTING TO SPOTIFY TOKEN ENDPOINT")
        response = await client.post(SPOTIFY_TOKEN_URL, headers=headers, data=data)
        logger.critical("TOKEN RESPONSE STATUS=%s", response.status_code)
        if response.status_code != 200:
            print("Spotify error response:", response.text)
        response.raise_for_status()
        return response.json()

async def get_user_profile(access_token: str) -> dict:
    """
    Get Spotify user profile with the access token.
    """
    logger.critical("=== GET USER PROFILE START ===")
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = await client.get(SPOTIFY_ME_URL, headers=headers)
        logger.critical("/me STATUS=%s", response.status_code)
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
    logger.critical("🔍 get_valid_access_token CALLED")
    logger.critical("USER_ID: %s", user_id)
    record = supabase.table("spotify_tokens").select("*").eq("user_id", user_id).single().execute().data
    logger.critical("DB RECORD: %s", record)
    if not record:
        logger.critical("❌ NO TOKEN RECORD FOUND")
        raise Exception("No tokens found for user")
    
    logger.critical("RECORD USER_ID: %s", record.get("user_id"))
    logger.critical("RECORD HAS ACCESS_TOKEN: %s", bool(record.get("access_token")))
    logger.critical("RECORD HAS REFRESH_TOKEN: %s", bool(record.get("refresh_token")))
    logger.critical("RECORD EXPIRES_AT RAW: %s", record.get("expires_at"))

    expires_at = datetime.fromisoformat(record["expires_at"])
    logger.critical("PARSED EXPIRES_AT: %s", expires_at)
    logger.critical("NOW UTC: %s", datetime.now(timezone.utc))
    logger.critical("IS EXPIRED: %s", expires_at < datetime.now(timezone.utc))
    if expires_at < datetime.now(timezone.utc):
        # Token expired — refresh it
        logger.critical("⚠️ TOKEN EXPIRED → ENTERING REFRESH PATH")
        refresh_token = record["refresh_token"]
        logger.critical("USING REFRESH TOKEN (PREFIX): %s", refresh_token[:20] if refresh_token else None)
        refreshed = await refresh_spotify_token(refresh_token)
        logger.critical("REFRESH RESPONSE KEYS: %s", list(refreshed.keys()))
        logger.critical("NEW ACCESS TOKEN (PREFIX): %s", refreshed["access_token"][:20])
        logger.critical("EXPIRES_IN: %s", refreshed.get("expires_in"))
        new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=refreshed["expires_in"])

        logger.critical("NEW EXPIRES_AT: %s", new_expires_at)
        # Update in Supabase
        supabase.table("spotify_tokens").update({
            "access_token": refreshed["access_token"],
            "expires_at": new_expires_at.isoformat()
        }).eq("user_id", user_id).execute()
        logger.critical("✅ SUPABASE TOKEN UPDATED FOR USER_ID: %s", user_id)

        return refreshed["access_token"]
    else:
        # Still valid
        logger.critical("✅ TOKEN STILL VALID → USING STORED ACCESS TOKEN")
        logger.critical("ACCESS TOKEN (PREFIX): %s", record["access_token"][:20])
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
    
