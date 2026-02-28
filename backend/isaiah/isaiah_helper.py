import os 



def get_env_config():
    ENV = os.getenv("ENV", "development")
    if ENV == "production":
        return {
            "ENV": ENV,
            "COOKIE_DOMAIN": "topspot40.com",
            "SECURE_COOKIE": True
        }
    else:
        return {
            "ENV": ENV,
            "COOKIE_DOMAIN": None,
            "SECURE_COOKIE": False
        }



def get_spotify_redirect_uri():
    if os.getenv("ENV") == "production":
        return os.getenv("SPOTIPY_REDIRECT_URI_PROD")
    return os.getenv("SPOTIPY_REDIRECT_URI")  # Gary’s dev URI
