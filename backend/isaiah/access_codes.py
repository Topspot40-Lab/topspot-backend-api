"""Authenticated access-code redemption; the database performs the atomic grant."""
from __future__ import annotations

import logging
import re
from uuid import UUID

from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.isaiah.jwt_session import decode_jwt_token

logger = logging.getLogger(__name__)


class AccessCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=128)


def create_access_code_router(get_client) -> APIRouter:
    router = APIRouter()

    @router.post("/access-codes/redeem")
    def redeem_access_code(
        body: AccessCodeRequest,
        request: Request,
        access_token: str | None = Cookie(None),
    ):
        # JSON plus the custom header prevents a cross-origin HTML form from
        # redeeming a code with another person's session. CORS controls preflight.
        if request.headers.get("x-topspot-access-code") != "1":
            raise HTTPException(403, detail={"code": "request_rejected"})
        payload = decode_jwt_token(access_token) if access_token else None
        try:
            user_id = str(UUID(payload["user_id"])) if payload else None
        except (KeyError, TypeError, ValueError, AttributeError):
            user_id = None
        if not user_id:
            raise HTTPException(401, detail={"code": "sign_in_required"})

        code = body.code.strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{3,64}", code):
            raise HTTPException(400, detail={"code": "invalid_code"})
        try:
            result = get_client().rpc("redeem_access_code", {
                "p_user_id": user_id,
                "p_code": code,
            }).execute().data
            if not isinstance(result, dict) or result.get("result") not in {
                "activated", "already_redeemed", "unchanged", "invalid_code",
                "unavailable_code", "rate_limited", "sign_in_required", "paid_subscription",
            }:
                raise ValueError("Invalid redemption response")
        except Exception:
            # Never include the submitted code, JWT, or database error in logs.
            logger.error("Access-code redemption failed")
            raise HTTPException(503, detail={"code": "temporarily_unavailable"}) from None

        outcome = result["result"]
        status = {
            "invalid_code": 400, "unavailable_code": 400,
            "rate_limited": 429, "sign_in_required": 401,
            "paid_subscription": 409,
        }.get(outcome, 200)
        headers = {"Cache-Control": "no-store"}
        if status == 429:
            headers["Retry-After"] = "900"
        return JSONResponse(result, status_code=status, headers=headers)

    return router
