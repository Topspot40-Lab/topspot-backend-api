import os
from urllib.parse import quote

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


def set_contact_unsubscribed(email: str, unsubscribed: bool) -> None:
    normalized_email = email.strip().lower()

    if not normalized_email:
        raise ValueError("Email is required")

    headers = {
        "Authorization": f"Bearer {_get_marketing_api_key()}",
        "Content-Type": "application/json",
    }

    encoded_email = quote(normalized_email, safe="")
    contact_url = f"{RESEND_CONTACTS_API_URL}/{encoded_email}"

    with httpx.Client(timeout=15.0) as client:
        get_response = client.get(contact_url, headers=headers)

        if get_response.status_code == 404:
            create_response = client.post(
                RESEND_CONTACTS_API_URL,
                headers=headers,
                json={
                    "email": normalized_email,
                    "unsubscribed": unsubscribed,
                },
            )
            create_response.raise_for_status()
            return

        get_response.raise_for_status()

        update_response = client.patch(
            contact_url,
            headers=headers,
            json={"unsubscribed": unsubscribed},
        )
        update_response.raise_for_status()
