from fastapi import APIRouter, Header, HTTPException
from backend.isaiah.isaiah_router import supabase  # reuse existing client
import os

router = APIRouter()

#ADMIN_SECRET = "supersecretkey"  # move to env later


@router.post("/admin/set-tester")
def set_tester(email: str, x_admin_key: str = Header(None)):
    ADMIN_SECRET = os.getenv("ADMIN_SECRET")

    # Check if env key of admin secret key is in env
    if not ADMIN_SECRET:
        raise HTTPException(status_code=500, detail="ADMIN_SECRET is not set in environment")
    #  auth
    if x_admin_key != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")

    #  check if user exists
    res = supabase.table("topspot_users") \
        .select("id, email, is_tester") \
        .eq("email", email) \
        .execute()

    user = res.data[0] if res.data else None

    # CASE 1: user does NOT exist → create
    if not user:
        supabase.table("topspot_users").insert({
            "email": email,
            "is_tester": True
        }).execute()

        return {
            "success": True,
            "email": email
        }

    # CASE 2: already tester
    if user and user.get("is_tester"):
        return {
            "success": True,
            "email": email
        }

    # CASE 3: update existing user
    supabase.table("topspot_users") \
        .update({"is_tester": True}) \
        .eq("email", email) \
        .execute()

    return {
        "success": True,
        "email": email
    }
