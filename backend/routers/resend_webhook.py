import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from supabase import create_client
from svix.webhooks import Webhook, WebhookVerificationError


logger = logging.getLogger(__name__)

router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
)

REQUIRED_SVIX_HEADERS = ("svix-id", "svix-timestamp", "svix-signature")


@router.post("/webhooks/resend")
async def resend_contact_webhook(request: Request):
    webhook_secret = os.getenv("RESEND_WEBHOOK_SECRET")

    if not webhook_secret:
        logger.error("RESEND_WEBHOOK_SECRET is not configured")
        raise HTTPException(status_code=400, detail="Webhook is not configured")

    headers = {key.lower(): value for key, value in request.headers.items()}

    if not all(headers.get(name) for name in REQUIRED_SVIX_HEADERS):
        raise HTTPException(
            status_code=400,
            detail="Missing Svix signature headers",
        )

    payload = await request.body()

    try:
        event = Webhook(webhook_secret).verify(payload, headers)
    except WebhookVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Svix signature")

    if not isinstance(event, dict) or event.get("type") != "contact.updated":
        return JSONResponse({"status": "ignored", "reason": "unhandled_event_type"})

    data = event.get("data") or {}
    email = str(data.get("email") or "").strip().lower()
    unsubscribed = data.get("unsubscribed")

    if not email:
        return JSONResponse({"status": "ignored", "reason": "missing_email"})

    if unsubscribed is not True:
        # Resend re-opting a contact in must never create TopSpot40 marketing
        # consent on its own; consent can only be granted through TopSpot40.
        return JSONResponse({"status": "ignored", "reason": "not_unsubscribed"})

    try:
        user_result = (
            supabase.table("topspot_users")
            .select("id")
            .ilike("email", email)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception(
            "TopSpot user lookup failed for Resend contact.updated webhook"
        )
        raise HTTPException(status_code=500, detail="Unable to process webhook")

    matching_users = user_result.data or []

    if not matching_users:
        return JSONResponse({"status": "ignored", "reason": "no_matching_user"})

    topspot_user_id = str(matching_users[0]["id"])

    try:
        existing_result = (
            supabase.table("marketing_email_preferences")
            .select("marketing_opt_in_at")
            .eq("user_id", topspot_user_id)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception(
            "Marketing preference lookup failed for user_id=%s",
            topspot_user_id,
        )
        raise HTTPException(status_code=500, detail="Unable to process webhook")

    existing_row = existing_result.data[0] if existing_result.data else None
    now_iso = datetime.now(timezone.utc).isoformat()

    preference_payload = {
        "marketing_opt_in": False,
        "marketing_opt_in_at": (
            existing_row["marketing_opt_in_at"] if existing_row else None
        ),
        "marketing_unsubscribed_at": now_iso,
        "consent_source": "resend_unsubscribe",
        "updated_at": now_iso,
    }

    try:
        if existing_row:
            supabase.table("marketing_email_preferences").update(
                preference_payload
            ).eq("user_id", topspot_user_id).execute()
        else:
            preference_payload["user_id"] = topspot_user_id
            supabase.table("marketing_email_preferences").insert(
                preference_payload
            ).execute()
    except Exception:
        logger.exception(
            "Marketing preference save failed for user_id=%s",
            topspot_user_id,
        )
        raise HTTPException(status_code=500, detail="Unable to process webhook")

    return JSONResponse({"status": "processed"})
