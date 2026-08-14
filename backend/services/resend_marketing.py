import os

import httpx


RESEND_CONTACTS_API_URL = "https://api.resend.com/contacts"


def _get_marketing_api_key() -> str:
    api_key = os.getenv("RESEND_MARKETING_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError("RESEND_MARKETING_API_KEY is not configured")

    return api_key


def create_marketing_contact(email: str) -> None:
    normalized_email = email.strip().lower()

    if not normalized_email:
        raise ValueError("Email is required")

    headers = {
        "Authorization": f"Bearer {_get_marketing_api_key()}",
        "Content-Type": "application/json",
    }

    payload = {
        "email": normalized_email,
        "unsubscribed": False,
    }

    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            RESEND_CONTACTS_API_URL,
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
