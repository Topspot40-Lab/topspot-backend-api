# backend/database.py
from __future__ import annotations

import os
import logging
from pathlib import Path

from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import NullPool  # avoids stale pooled conns in dev

log = logging.getLogger(__name__)

# 1) Load .env from project root (…/topspot_json_creator/.env)
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path)
    except Exception:
        pass
else:
    log.warning("No .env found at %s", env_path)

# 2) Read DB URL (support a few common var names)
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("POSTGRES_URL")
    or os.getenv("SUPABASE_DB_URL")
    or ""
)
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL/POSTGRES_URL not set in .env")

# 3) Connection args (good defaults for Supabase/remote PG)
#    - sslmode=require for TLS
#    - keepalives so idle conns don't get dropped by proxies
connect_args = {
    "sslmode": "require",   # remove if using local non-TLS Postgres
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
    # Optional: server-side statement timeout (ms)
    # "options": "-c statement_timeout=60000",
}

# 4) Create engine
#    NullPool: safest in dev + uvicorn --reload (no stale pool survivors)
#    pool_pre_ping: validates connection before each checkout
engine = create_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,
    pool_pre_ping=True,
    connect_args=connect_args,
)

def init_db() -> None:
    """Create tables if they don't exist (call once at startup if you use SQLModel metadata)."""
    SQLModel.metadata.create_all(engine)

def get_db():
    """FastAPI dependency: yield a Session per request and close it afterward."""
    with Session(engine) as session:
        yield session

# --- Context manager for scripts (CLI jobs, one-off tools) ---
from contextlib import contextmanager

@contextmanager
def get_db_session():
    """
    Wrap the existing get_db() generator dependency into a context manager
    so scripts can do: `with get_db_session() as db:`
    """
    gen = get_db()           # use the local generator defined above
    db = next(gen)           # retrieve the Session
    try:
        yield db
    finally:
        # advance the generator so its teardown/close logic executes
        try:
            next(gen)
        except StopIteration:
            pass
