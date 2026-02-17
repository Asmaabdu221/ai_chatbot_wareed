"""Conversation API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    """Request body for creating a conversation. Title optional (auto-generated from first message)."""
    title: str | None = Field(None, max_length=255, description="Optional title; else derived from first message")


class ConversationUpdate(BaseModel):
    """Request body for updating a conversation (e.g. title)."""
    title: str | None = Field(None, max_length=255, description="New title")


class ConversationRead(BaseModel):
    """Single conversation response."""
    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    is_archived: bool = False

    class Config:
        from_attributes = True


class ConversationListResponse(BaseModel):
    """List of conversations (e.g. GET /api/conversations)."""
    conversations: list[ConversationRead]
    total: int
