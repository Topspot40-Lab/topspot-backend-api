import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import create_client

from backend.isaiah.isaiah_helper import get_env_config
from backend.isaiah.jwt_session import (
    JWT_EXP_DELTA_SECONDS,
    create_jwt_token,
    decode_jwt_token,
)
from backend.services.resend_marketing import (
    create_marketing_contact,
    set_contact_unsubscribed,
)


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

cookie_config = get_env_config()


class SupabaseSessionRequest(BaseModel):
    access_token: str


class SupabaseSignupRequest(BaseModel):
    access_token: str
    display_name: str
    preferred_language: str
    marketing_opt_in: bool = False


class MarketingPreferenceRequest(BaseModel):
    marketing_opt_in: bool


class ProfileCompletionRequest(BaseModel):
    display_name: str


SUPPORTED_PREFERRED_LANGUAGES = {"en", "es", "pt-BR"}


def normalized_display_name(value: str) -> str:
    name = value.strip() if isinstance(value, str) else ""
    if not 2 <= len(name) <= 50:
        raise HTTPException(
            status_code=422,
            detail="Display name must be between 2 and 50 characters",
        )
    return name


def require_preferred_language(value: str) -> str:
    if value not in SUPPORTED_PREFERRED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Unsupported preferred language")
    return value


def _session_response(
    topspot_user_id: str,
    *,
    status_code: int,
    created: bool = False,
    legacy_linked: bool = False,
    display_name: str | None = None,
):
    response = JSONResponse(
        status_code=status_code,
        content={
            "authenticated": True,
            "created": created,
            "legacy_linked": legacy_linked,
            "user_id": topspot_user_id,
            "profile_completion_required": not bool((display_name or "").strip()),
        },
    )
    response.set_cookie(
        key="access_token",
        value=create_jwt_token(topspot_user_id),
        httponly=True,
        secure=cookie_config["SECURE_COOKIE"],
        samesite="none",
        max_age=JWT_EXP_DELTA_SECONDS,
        path="/",
        domain=cookie_config["COOKIE_DOMAIN"],
    )
    return response


@router.post("/logout")
def logout():
    response = JSONResponse(
        status_code=200,
        content={"logged_out": True},
    )

    response.delete_cookie(
        key="access_token",
        path="/",
        domain=cookie_config["COOKIE_DOMAIN"],
        secure=cookie_config["SECURE_COOKIE"],
        httponly=True,
        samesite="none",
    )

    return response


@router.post("/supabase/signup")
def create_supabase_signup(payload: SupabaseSignupRequest):
    token = payload.access_token.strip()
    display_name = normalized_display_name(payload.display_name)
    preferred_language = require_preferred_language(payload.preferred_language)

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing Supabase access token",
        )

    try:
        auth_response = supabase.auth.get_user(token)
    except Exception:
        logger.warning("Supabase signup access-token verification failed")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token",
        )

    auth_user = getattr(auth_response, "user", None)

    if auth_user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token",
        )

    auth_user_id = str(auth_user.id)
    verified_email = (auth_user.email or "").strip().lower()

    if not verified_email:
        raise HTTPException(
            status_code=403,
            detail="A verified email address is required",
        )

    if auth_user.email_confirmed_at is None:
        raise HTTPException(
            status_code=403,
            detail="Email address has not been verified",
        )

    try:
        email_result = (
            supabase.table("topspot_users")
            .select("id,auth_user_id,display_name")
            .eq("email", verified_email)
            .limit(1)
            .execute()
        )

        auth_result = (
            supabase.table("topspot_users")
            .select("id")
            .eq("auth_user_id", auth_user_id)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("TopSpot signup conflict lookup failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to complete signup",
        )

    if auth_result.data:
        raise HTTPException(
            status_code=409,
            detail="This identity is already linked to a TopSpot40 account. Please sign in instead.",
        )

    existing_user = email_result.data[0] if email_result.data else None
    if existing_user:
        # Legacy activation is allowed only after this verified sign-up and only
        # while the legacy row has never been linked to Supabase authentication.
        if existing_user.get("auth_user_id") is not None:
            raise HTTPException(
                status_code=409,
                detail="A TopSpot40 account already exists with this email. Please sign in instead.",
            )
        try:
            linked_result = (
                supabase.table("topspot_users")
                .update({"auth_user_id": auth_user_id})
                .eq("id", existing_user["id"])
                .is_("auth_user_id", "null")
                .execute()
            )
        except Exception:
            logger.exception("Legacy TopSpot identity linking failed")
            raise HTTPException(status_code=409, detail="Unable to complete signup")

        if not linked_result.data:
            raise HTTPException(status_code=409, detail="Unable to complete signup")

        return _session_response(
            str(existing_user["id"]),
            status_code=200,
            legacy_linked=True,
            display_name=existing_user.get("display_name"),
        )

    try:
        insert_result = (
            supabase.table("topspot_users")
            .insert(
                {
                    "email": verified_email,
                    "auth_user_id": auth_user_id,
                    "display_name": display_name,
                    "preferred_language": preferred_language,
                }
            )
            .execute()
        )
    except Exception:
        logger.exception("TopSpot user creation failed")
        raise HTTPException(
            status_code=409,
            detail="Unable to create TopSpot40 account",
        )

    if not insert_result.data:
        raise HTTPException(
            status_code=500,
            detail="Unable to create TopSpot40 account",
        )

    topspot_user_id = str(insert_result.data[0]["id"])

    preference_payload = {
        "user_id": topspot_user_id,
        "marketing_opt_in": payload.marketing_opt_in,
        "marketing_opt_in_at": (
            datetime.now(timezone.utc).isoformat()
            if payload.marketing_opt_in
            else None
        ),
        "marketing_unsubscribed_at": None,
        "consent_source": "signup",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    preference_saved = False

    try:
        supabase.table("marketing_email_preferences").insert(
            preference_payload
        ).execute()
        preference_saved = True
    except Exception:
        logger.exception(
            "Marketing preference creation failed for user_id=%s; "
            "treating user as not subscribed",
            topspot_user_id,
        )

    if payload.marketing_opt_in and preference_saved:
        try:
            create_marketing_contact(verified_email)
        except Exception:
            logger.exception(
                "Resend marketing contact sync failed for user_id=%s",
                topspot_user_id,
            )

    return _session_response(
        topspot_user_id,
        status_code=201,
        created=True,
        display_name=display_name,
    )


@router.post("/profile-completion")
def complete_profile(
    payload: ProfileCompletionRequest,
    access_token: str = Cookie(None),
):
    jwt_payload = decode_jwt_token(access_token)
    if not jwt_payload:
        raise HTTPException(status_code=401, detail="Invalid or expired JWT Session")

    display_name = normalized_display_name(payload.display_name)
    topspot_user_id = str(jwt_payload["user_id"])

    try:
        result = (
            supabase.rpc(
                "complete_topspot_user_display_name",
                {
                    "p_user_id": topspot_user_id,
                    "p_display_name": display_name,
                },
            )
            .execute()
        )
    except Exception:
        logger.exception("Profile completion save failed for user_id=%s", topspot_user_id)
        raise HTTPException(status_code=500, detail="Unable to complete profile")

    if not result.data:
        raise HTTPException(status_code=409, detail="Profile is already complete")

    return {"display_name": result.data[0]["display_name"]}


@router.get("/marketing-preference")
def get_marketing_preference(access_token: str = Cookie(None)):
    jwt_payload = decode_jwt_token(access_token)

    if not jwt_payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired JWT Session",
        )

    topspot_user_id = str(jwt_payload["user_id"])

    try:
        pref_result = (
            supabase.table("marketing_email_preferences")
            .select("marketing_opt_in,marketing_opt_in_at,marketing_unsubscribed_at")
            .eq("user_id", topspot_user_id)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception(
            "Marketing preference lookup failed for user_id=%s",
            topspot_user_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to load marketing preference",
        )

    row = pref_result.data[0] if pref_result.data else None

    if not row:
        return {
            "marketing_opt_in": False,
            "marketing_opt_in_at": None,
            "marketing_unsubscribed_at": None,
        }

    return {
        "marketing_opt_in": row["marketing_opt_in"],
        "marketing_opt_in_at": row["marketing_opt_in_at"],
        "marketing_unsubscribed_at": row["marketing_unsubscribed_at"],
    }


@router.post("/marketing-preference")
def set_marketing_preference(
    payload: MarketingPreferenceRequest,
    access_token: str = Cookie(None),
):
    jwt_payload = decode_jwt_token(access_token)

    if not jwt_payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired JWT Session",
        )

    topspot_user_id = str(jwt_payload["user_id"])

    try:
        user_result = (
            supabase.table("topspot_users")
            .select("id,email")
            .eq("id", topspot_user_id)
            .single()
            .execute()
        )
    except Exception:
        logger.exception(
            "TopSpot user lookup failed for user_id=%s",
            topspot_user_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to update marketing preference",
        )

    if not user_result.data or not user_result.data.get("email"):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired JWT Session",
        )

    email = user_result.data["email"]

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
        raise HTTPException(
            status_code=500,
            detail="Unable to update marketing preference",
        )

    existing_row = existing_result.data[0] if existing_result.data else None
    now_iso = datetime.now(timezone.utc).isoformat()

    if payload.marketing_opt_in:
        marketing_opt_in_at = (
            existing_row["marketing_opt_in_at"]
            if existing_row and existing_row["marketing_opt_in_at"]
            else now_iso
        )
        marketing_unsubscribed_at = None
    else:
        marketing_opt_in_at = (
            existing_row["marketing_opt_in_at"] if existing_row else None
        )
        marketing_unsubscribed_at = now_iso

    preference_payload = {
        "marketing_opt_in": payload.marketing_opt_in,
        "marketing_opt_in_at": marketing_opt_in_at,
        "marketing_unsubscribed_at": marketing_unsubscribed_at,
        "consent_source": "account_settings",
        "updated_at": now_iso,
    }

    try:
        if existing_row:
            save_result = (
                supabase.table("marketing_email_preferences")
                .update(preference_payload)
                .eq("user_id", topspot_user_id)
                .execute()
            )
        else:
            preference_payload["user_id"] = topspot_user_id
            save_result = (
                supabase.table("marketing_email_preferences")
                .insert(preference_payload)
                .execute()
            )
    except Exception:
        logger.exception(
            "Marketing preference save failed for user_id=%s",
            topspot_user_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to update marketing preference",
        )

    if not save_result.data:
        raise HTTPException(
            status_code=500,
            detail="Unable to update marketing preference",
        )

    try:
        set_contact_unsubscribed(email, not payload.marketing_opt_in)
    except Exception:
        logger.exception(
            "Resend marketing contact sync failed for user_id=%s",
            topspot_user_id,
        )

    saved_row = save_result.data[0]

    return {
        "marketing_opt_in": saved_row["marketing_opt_in"],
        "marketing_opt_in_at": saved_row["marketing_opt_in_at"],
        "marketing_unsubscribed_at": saved_row["marketing_unsubscribed_at"],
    }


@router.post("/supabase/session")
def create_supabase_session(payload: SupabaseSessionRequest):
    token = payload.access_token.strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing Supabase access token",
        )

    try:
        auth_response = supabase.auth.get_user(token)
    except Exception:
        logger.warning("Supabase access-token verification failed")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token",
        )

    auth_user = getattr(auth_response, "user", None)

    if auth_user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token",
        )

    auth_user_id = str(auth_user.id)
    verified_email = (auth_user.email or "").strip().lower()

    if not verified_email:
        raise HTTPException(
            status_code=403,
            detail="A verified email address is required",
        )

    if auth_user.email_confirmed_at is None:
        raise HTTPException(
            status_code=403,
            detail="Email address has not been verified",
        )

    try:
        user_result = (
            supabase.table("topspot_users")
            .select("id,email,auth_user_id,display_name")
            .eq("email", verified_email)
            .limit(2)
            .execute()
        )
    except Exception:
        logger.exception("TopSpot user lookup failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to complete sign-in",
        )

    matching_users = user_result.data or []

    if len(matching_users) == 0:
        raise HTTPException(
            status_code=403,
            detail="Unable to complete sign-in",
        )

    if len(matching_users) != 1:
        logger.error(
            "Ambiguous TopSpot account lookup for verified email"
        )
        raise HTTPException(
            status_code=409,
            detail="Unable to uniquely identify the TopSpot40 account",
        )

    topspot_user = matching_users[0]
    topspot_user_id = str(topspot_user["id"])
    if str(topspot_user.get("auth_user_id") or "") != auth_user_id:
        logger.warning("Refusing sign-in with a non-matching Supabase identity")
        raise HTTPException(status_code=403, detail="Unable to complete sign-in")

    try:
        update_result = (
            supabase.table("topspot_users")
            .update(
                {"last_login_at": datetime.now(timezone.utc).isoformat()}
            )
            .eq("id", topspot_user_id)
            .execute()
        )
    except Exception:
        logger.exception("TopSpot Supabase identity linking failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to complete sign-in",
        )

    if not update_result.data:
        raise HTTPException(
            status_code=500,
            detail="Unable to complete sign-in",
        )

    return _session_response(
        topspot_user_id,
        status_code=200,
        display_name=topspot_user.get("display_name"),
    )
