from fastapi import FastAPI

from backend.routers.health import router as health_router
from backend.routers.catalog import router as catalog_router

app = FastAPI(
    title="TopSpot Backend API",
    version="0.1.0"
)

app.include_router(health_router)
app.include_router(catalog_router)
