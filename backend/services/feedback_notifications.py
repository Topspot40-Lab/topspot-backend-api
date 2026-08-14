import logging
import os

import httpx

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


async def send_feedback_notification(payload: dict) -> None:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_address = os.getenv("FEEDBACK_NOTIFICATION_FROM", "").strip()
    recipients_raw = os.getenv("FEEDBACK_NOTIFICATION_RECIPIENTS", "").strip()

    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not configured")

    if not from_address:
        raise RuntimeError("FEEDBACK_NOTIFICATION_FROM is not configured")

    recipients = [
        email.strip()
        for email in recipients_raw.split(",")
        if email.strip()
    ]

    if not recipients:
        raise RuntimeError("FEEDBACK_NOTIFICATION_RECIPIENTS is not configured")

    feedback_type = payload.get("type") or "feedback"
    title = payload.get("title") or "(No title)"
    message = payload.get("message") or ""
    sender_email = payload.get("email") or "(Not supplied)"
    route = payload.get("route") or "(Not supplied)"
    created_at = payload.get("created_at") or "(Unknown)"
    feedback_id = payload.get("id") or "(Unknown)"

    subject = f"TopSpot40 {feedback_type}: {title}"

    text_body = (
        "New TopSpot40 feedback submission\n\n"
        f"Type: {feedback_type}\n"
        f"Title: {title}\n"
        f"Email: {sender_email}\n"
        f"Route: {route}\n"
        f"Created: {created_at}\n"
        f"Feedback ID: {feedback_id}\n\n"
        "Message:\n"
        f"{message}"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    email_payload = {
        "from": f"TopSpot40 Notifications <{from_address}>",
        "to": recipients,
        "subject": subject,
        "text": text_body,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            RESEND_API_URL,
            headers=headers,
            json=email_payload,
        )
        response.raise_for_status()

    logger.info(
        "Feedback notification email sent for feedback_id=%s",
        feedback_id,
    )
