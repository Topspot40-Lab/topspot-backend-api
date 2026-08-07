import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import create_client
from supabase_auth.errors import AuthApiError

from backend.isaiah.isaiah_helper import get_env_config
from backend.isaiah.jwt_session import (
    JWT_EXP_DELTA_SECONDS,
    create_jwt_token,
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
def create_supabase_signup(payload: SupabaseSessionRequest):
    token = payload.access_token.strip()

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
            .select("id")
            .ilike("email", verified_email)
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

    if email_result.data:
        raise HTTPException(
            status_code=409,
            detail="A TopSpot40 account already exists with this email. Please sign in instead.",
        )

    if auth_result.data:
        raise HTTPException(
            status_code=409,
            detail="This sign-in identity is already linked to a TopSpot40 account.",
        )

    try:
        insert_result = (
            supabase.table("topspot_users")
            .insert(
                {
                    "email": verified_email,
                    "auth_user_id": auth_user_id,
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
    topspot_jwt = create_jwt_token(topspot_user_id)

    response = JSONResponse(
        status_code=201,
        content={
            "authenticated": True,
            "created": True,
            "user_id": topspot_user_id,
        },
    )

    response.set_cookie(
        key="access_token",
        value=topspot_jwt,
        httponly=True,
        secure=cookie_config["SECURE_COOKIE"],
        samesite="none",
        max_age=JWT_EXP_DELTA_SECONDS,
        path="/",
        domain=cookie_config["COOKIE_DOMAIN"],
    )

    return response


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
            .select("id,email,auth_user_id")
            .ilike("email", verified_email)
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
            detail="No existing TopSpot40 account matches this email",
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
    existing_auth_user_id = topspot_user.get("auth_user_id")

    if (
        existing_auth_user_id is not None
        and str(existing_auth_user_id) != auth_user_id
    ):
        try:
            existing_auth_response = (
                supabase.auth.admin.get_user_by_id(
                    str(existing_auth_user_id)
                )
            )
        except AuthApiError as exc:
            if exc.status != 404:
                logger.exception(
                    "Unable to verify existing Supabase identity link"
                )
                raise HTTPException(
                    status_code=503,
                    detail="Unable to complete sign-in",
                )

            logger.warning(
                "Replacing stale legacy Supabase identity link "
                "for TopSpot user %s",
                topspot_user_id,
            )
        except Exception:
            logger.exception(
                "Unable to verify existing Supabase identity link"
            )
            raise HTTPException(
                status_code=503,
                detail="Unable to complete sign-in",
            )
        else:
            if getattr(existing_auth_response, "user", None) is not None:
                logger.warning(
                    "Refusing to replace a valid Supabase identity link "
                    "for TopSpot user %s",
                    topspot_user_id,
                )
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This TopSpot40 account is already linked "
                        "to another identity"
                    ),
                )

    try:
        update_result = (
            supabase.table("topspot_users")
            .update(
                {
                    "auth_user_id": auth_user_id,
                    "last_login_at": datetime.now(timezone.utc).isoformat(),
                }
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

    topspot_jwt = create_jwt_token(topspot_user_id)

    response = JSONResponse(
        status_code=200,
        content={
            "authenticated": True,
            "user_id": topspot_user_id,
        },
    )

    response.set_cookie(
        key="access_token",
        value=topspot_jwt,
        httponly=True,
        secure=cookie_config["SECURE_COOKIE"],
        samesite="none",
        max_age=JWT_EXP_DELTA_SECONDS,
        path="/",
        domain=cookie_config["COOKIE_DOMAIN"],
    )

    return response