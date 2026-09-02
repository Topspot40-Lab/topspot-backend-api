# models/feedback.py
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

FeedbackType = Literal["bug", "feature", "feedback"]
FeedbackCategory = Literal["contact", "general_feedback", "content_issue"]
FeedbackSeverity = Literal["low", "medium", "high", "critical"]
FeedbackStatus = Literal["new", "triaged", "in_progress", "fixed", "ignored"]


class FeedbackCreate(BaseModel):
    type: FeedbackType
    message: str
    title: str | None = None
    email: EmailStr | None = None
    route: str | None = None
    category: FeedbackCategory = "general_feedback"
    metadata: dict[str, Any] = Field(default_factory=dict)
