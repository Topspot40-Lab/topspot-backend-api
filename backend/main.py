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
from backend.routers.single_track_player import router as single_track_player_router
from backend.routers.decade_genre_pause import router as decade_genre_pause_router

# 🔐 Spotify Auth (THIS WAS MISSING)
from backend.routers.spotify_auth import router as spotify_auth_router


app = FastAPI(
    title="TopSpot Backend API",
    version="0.1.0"
)

# 🔓 CORS — REQUIRED for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://topspot40.com",
    ],
    allow_credentials=False,
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
