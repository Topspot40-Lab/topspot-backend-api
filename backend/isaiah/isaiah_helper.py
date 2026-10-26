# backend/isaiah/isaiah_helper.py
import os
from pathlib import Path

from dotenv import load_dotenv


# Auth routers import this helper before some of the older router modules call
# load_dotenv(), so load the repository's existing local configuration here.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

def get_env_config():
    """
    Returns backend configuration for cookies. Production remains the default;
    local development is explicitly selected with TOPSPOT_ENV=local.
    """
    environment = os.getenv("TOPSPOT_ENV", "production").strip().lower()

    if environment in {"local", "development", "dev"}:
        return {
            # Omit Domain so the browser creates a host-only localhost cookie.
            "COOKIE_DOMAIN": None,
            "SECURE_COOKIE": False,
            "SAMESITE": "lax",
        }

    return {
        "COOKIE_DOMAIN": ".topspot40.com",
        "SECURE_COOKIE": True,
        "SAMESITE": "none",
    }

def get_spotify_redirect_uri(local: bool = True):
    """
    Returns the Spotify redirect URI for OAuth callback.
    """
    if local:
        return "http://127.0.0.1:8000/api/auth/spotify/callback"
    return "https://api.topspot40.com/api/auth/spotify/callback"  # adjust to Netlify deploy

def get_frontend_url(local: bool = True):
    """
    Returns the frontend base URL.
    """
    if local:
        return "http://localhost:5173"
    #return "https://resplendent-gaufre-032b1a.netlify.app"  # Netlify site
    return "https://topspot40.com" # domain site



def get_stripe_config(local: bool):
    if local:
        return {
            "secret_key": os.getenv("STRIPE_TEST_SECRET_KEY"),
            "price_id": os.getenv("STRIPE_TEST_PRICE_ID"),
            "standard_monthly_price_id": os.getenv("STRIPE_TEST_STANDARD_MONTHLY_PRICE_ID"),
            "standard_annual_price_id": os.getenv("STRIPE_TEST_STANDARD_ANNUAL_PRICE_ID"),
            "promo_2027_monthly_price_id": os.getenv("STRIPE_TEST_2027_PROMO_MONTHLY_PRICE_ID"),
            "promo_2027_annual_price_id": os.getenv("STRIPE_TEST_2027_PROMO_ANNUAL_PRICE_ID"),
            "webhook_secret": os.getenv("STRIPE_WEBHOOK_TEST_SECRET"),
        }
    else:
        return {
            "secret_key": os.getenv("STRIPE_SECRET_KEY"),
            "price_id": os.getenv("STRIPE_PRICE_ID"),
            "standard_monthly_price_id": os.getenv("STRIPE_STANDARD_MONTHLY_PRICE_ID"),
            "standard_annual_price_id": os.getenv("STRIPE_STANDARD_ANNUAL_PRICE_ID"),
            "promo_2027_monthly_price_id": os.getenv("STRIPE_2027_PROMO_MONTHLY_PRICE_ID"),
            "promo_2027_annual_price_id": os.getenv("STRIPE_2027_PROMO_ANNUAL_PRICE_ID"),
            "webhook_secret": os.getenv("STRIPE_WEBHOOK_SECRET"),
        }
    
