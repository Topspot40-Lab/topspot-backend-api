from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers.health import router as health_router
from backend.routers.catalog import router as catalog_router

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

app.include_router(health_router)
app.include_router(catalog_router)
