# backend/routers/router_feedback.py
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
from uuid import uuid4

from backend.services.supabase_client import supabase
from backend.models.feedback import FeedbackCreate

feedback_router = APIRouter(prefix="/feedback", tags=["feedback"])


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
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "message": "Feedback submitted successfully",
        "id": payload["id"],
    }
