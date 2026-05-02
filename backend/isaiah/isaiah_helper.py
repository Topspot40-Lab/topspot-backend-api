# backend/isaiah/isaiah_helper.py

def get_env_config():
    """
    Returns backend configuration for cookies.
    """
    return {
        "COOKIE_DOMAIN": ".topspot40.com",  # set "topspot40.com" for production if needed, None if local
        "SECURE_COOKIE": True  # set True if using HTTPS in production, False if local
    }

def get_spotify_redirect_uri(local: bool = True):
    """
    Returns the Spotify redirect URI for OAuth callback.
    """
    if local:
        return "http://127.0.0.1:8000/spotify/callback"
    return "https://api.topspot40.com/api/auth/spotify/callback"  # adjust to Netlify deploy

def get_frontend_url(local: bool = True):
    """
    Returns the frontend base URL.
    """
    if local:
        return "http://localhost:5173"
    #return "https://resplendent-gaufre-032b1a.netlify.app"  # Netlify site
    return "https://topspot40.com" # domain site
