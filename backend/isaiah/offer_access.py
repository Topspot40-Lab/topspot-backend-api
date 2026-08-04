from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


OFFER_CODE = "topspot_2026_free_2027_discount"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_supabase_timestamptz(
    value: str | datetime | None,
) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else ""))
        except ValueError as exc:
            raise ValueError("Malformed timestamp") from exc
    else:
        raise ValueError("Timestamp must be a string, datetime, or None")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware")

    return parsed.astimezone(timezone.utc)


def compute_offer_access(
    entitlement: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = parse_supabase_timestamptz(now) if now is not None else utc_now()

    if entitlement is None:
        return {
            "access_state": "none",
            "access_source": "none",
            "is_subscribed": False,
            "status": "inactive",
            "requires_checkout": True,
            "eligible_for_2027_discount": False,
            "discount_used": False,
            "discount_available": False,
        }

    offer_code = entitlement.get("offer_code")
    if not isinstance(offer_code, str) or not offer_code.strip():
        raise ValueError("Entitlement must contain a nonblank offer_code")

    if entitlement.get("free_access_expires_at") is None:
        raise ValueError("Entitlement must contain free_access_expires_at")
    if entitlement.get("grace_access_expires_at") is None:
        raise ValueError("Entitlement must contain grace_access_expires_at")
    if entitlement.get("standard_transition_at") is None:
        raise ValueError("Entitlement must contain standard_transition_at")

    free_access_expires_at = parse_supabase_timestamptz(entitlement.get("free_access_expires_at"))
    grace_access_expires_at = parse_supabase_timestamptz(entitlement.get("grace_access_expires_at"))
    standard_transition_at = parse_supabase_timestamptz(entitlement.get("standard_transition_at"))

    if free_access_expires_at > grace_access_expires_at:
        raise ValueError("free_access_expires_at must not be later than grace_access_expires_at")
    if grace_access_expires_at > standard_transition_at:
        raise ValueError("grace_access_expires_at must not be later than standard_transition_at")

    discount_consumed_at = parse_supabase_timestamptz(entitlement.get("discount_consumed_at"))
    discount_used = discount_consumed_at is not None
    discount_available = not discount_used and current_time < standard_transition_at

    base_response = {
        "offer_code": offer_code,
        "eligible_for_2027_discount": True,
        "discount_used": discount_used,
        "discount_available": discount_available,
    }

    if current_time < free_access_expires_at:
        return {
            "access_state": "free_2026",
            "access_source": "offer",
            "is_subscribed": True,
            "status": "free_2026",
            "requires_checkout": False,
            **base_response,
            "access_expires_at": free_access_expires_at.isoformat(),
        }

    if current_time < grace_access_expires_at:
        return {
            "access_state": "grace_2027",
            "access_source": "offer_grace",
            "is_subscribed": True,
            "status": "grace_2027",
            "requires_checkout": True,
            **base_response,
            "access_expires_at": grace_access_expires_at.isoformat(),
        }

    return {
        "access_state": "expired",
        "access_source": "none",
        "is_subscribed": False,
        "status": "expired",
        "requires_checkout": True,
        **base_response,
    }
