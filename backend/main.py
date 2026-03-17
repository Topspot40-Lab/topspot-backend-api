from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Core routers
from backend.routers.health import router as health_router
from backend.routers.catalog import router as catalog_router

# 🎵 Playback & Car-Mode routers
from backend.routers.playback_status import router as playback_status_router
from backend.routers.playback_control import router as playback_control_router
from backend.routers.decade_genre_player import router as decade_genre_player_router
from backend.routers.collections_player import router as collections_player_router
from backend.routers.decade_genre_pause import router as decade_genre_pause_router

# 🔐 Spotify Auth (THIS WAS MISSING)
from backend.routers.spotify_auth import router as spotify_auth_router
from backend.routers.feedback import feedback_router


# Isaiah's endpoints 
from backend.isaiah.isaiah_router import stripe_router
from backend.isaiah.isaiah_router import spotify_user_auth_router

from backend.routers import supabase_collections

import logging

class IgnorePlaybackStatus(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn.access puts the whole access line in record.getMessage()
        return "/playback/status" not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(IgnorePlaybackStatus())


app = FastAPI(
    title="TopSpot Backend API",
    version="0.1.0"
)

from fastapi.responses import HTMLResponse

@app.get("/", response_class=HTMLResponse)
async def root():
    print("🔥🔥🔥 ROOT ENDPOINT HIT 🔥🔥🔥")
    return """
    <html>
      <head>
        <title>TopSpot40 Backend</title>
      </head>
      <body style="font-family: system-ui; padding: 40px;">
        <h1>🎶 TopSpot40 Backend</h1>
        <p>Status: Alive and humming.</p>
        <p>Environment: Render</p>
      </body>
    </html>
    """




# 🔓 CORS — REQUIRED for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
        "https://topspot40.com",
        "https://www.topspot40.com",
        "https://topspot40.netlify.app",
        "https://sparkling-croissant-23bbac.netlify.app",
        "https://resplendent-gaufre-032b1a.netlify.app",
    ],
    #allow_credentials=False,
    allow_credentials=True, # must be True for Cookies
    allow_methods=["*"],
    allow_headers=["*"],
)


# 🧪 Basic health + catalog
app.include_router(health_router)
app.include_router(catalog_router)

# 🔐 Spotify Auth (NOW LIVE)
app.include_router(spotify_auth_router)

# 🚗 Car-Mode + Playback
app.include_router(playback_status_router)
app.include_router(decade_genre_player_router)
app.include_router(collections_player_router)
app.include_router(decade_genre_pause_router)
app.include_router(playback_control_router)
app.include_router(feedback_router, prefix="/api")



# Spotify Auth endpoints 
app.include_router(spotify_user_auth_router, prefix="/api/auth")
# Stripe endpoints
app.include_router(stripe_router, prefix="/api")
# Feedback/bug report logic endpoint
app.include_router(feedback_router, prefix="/api")
app.include_router(supabase_collections.router)
