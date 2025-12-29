from fastapi import FastAPI
from backend.routers.health import router as health_router

app = FastAPI(
    title="TopSpot Backend API",
    version="0.1.0"
)

app.include_router(health_router)
