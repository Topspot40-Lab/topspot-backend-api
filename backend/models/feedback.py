# models/feedback.py
from pydantic import BaseModel, EmailStr
from typing import Optional, Literal

FeedbackType = Literal["bug", "feature", "feedback"]
FeedbackSeverity = Literal["low", "medium", "high", "critical"]
FeedbackStatus = Literal["new", "triaged", "in_progress", "fixed", "ignored"]


class FeedbackCreate(BaseModel):
    type: FeedbackType
    message: str
    title: Optional[str] = None
    email: Optional[EmailStr] = None
    route: Optional[str] = None
