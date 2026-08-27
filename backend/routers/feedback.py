import logging
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
from uuid import uuid4

from backend.services.supabase_client import supabase
from backend.models.feedback import FeedbackCreate
from backend.services.feedback_notifications import send_feedback_notification

feedback_router = APIRouter(prefix="/feedback", tags=["feedback"])
logger = logging.getLogger(__name__)

FEEDBACK_SUBMISSION_FAILED_DETAIL = "Unable to submit feedback."


@feedback_router.post("/")
async def create_feedback(feedback: FeedbackCreate):
    payload = {
        "id": str(uuid4()),
        "user_id": None,
        "email": feedback.email,
        "type": feedback.type,
        "title": feedback.title,
        "message": feedback.message,
        "route": feedback.route,
        "app_version": "1.0.0",
        "user_agent": "web",
        "severity": "low",
        "status": "new",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        supabase.table("feedback").insert(payload).execute()
    except Exception:
        logger.error("endpoint=feedback.create_feedback error_category=feedback_persistence_failure")
        raise HTTPException(status_code=500, detail=FEEDBACK_SUBMISSION_FAILED_DETAIL)

    try:
        await send_feedback_notification(payload)
    except Exception:
        logger.error(
            "endpoint=feedback.create_feedback error_category=feedback_notification_failure"
        )

    return {
        "message": "Feedback submitted successfully",
        "id": payload["id"],
    }
