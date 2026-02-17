"""Message API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    """Request body for sending a message (user content)."""
    content: str = Field(..., min_length=1, max_length=10000, description="Message text")


class PrescriptionMessageCreate(BaseModel):
    """Request body for prescription result (user + assistant pair, no AI call)."""
    user_content: str = Field(default="صورة وصفة طبية", max_length=500)
    assistant_content: str = Field(..., min_length=1, max_length=20000)


class MessageRead(BaseModel):
    """Single message response."""
    id: UUID
    role: str
    content: str
    token_count: int | None
    created_at: datetime

    class Config:
        from_attributes = True


class MessageListResponse(BaseModel):
    """List of messages (e.g. GET /api/conversations/{id}/messages)."""
    messages: list[MessageRead]
    total: int


class SendMessageResponse(BaseModel):
    """Response after sending a message (user + AI assistant pair)."""
    user_message: MessageRead
    assistant_message: MessageRead
