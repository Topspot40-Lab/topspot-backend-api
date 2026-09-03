# backend/db/supabase_client.py
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from yarl import URL
from backend.services.supabase_url import normalize_supabase_url, storage_endpoint_url

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # server-side only

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(normalize_supabase_url(SUPABASE_URL), SUPABASE_SERVICE_ROLE_KEY)
# supabase-py derives ``storage/v1`` without a terminal slash, while the
# installed storage3 client requires one. Keep the configured project URL intact.
supabase.storage_url = URL(storage_endpoint_url(SUPABASE_URL))
