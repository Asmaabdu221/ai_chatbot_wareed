"""
Database Models
Defines all database tables and relationships for the WAREED Medical AI Chatbot

Models:
- User: Represents a user of the system
- Conversation: Represents a chat conversation belonging to a user
- Message: Represents individual messages within a conversation
"""

import uuid
import enum
from datetime import datetime
from typing import List
from sqlalchemy import (
    String, Boolean, Integer, Text, ForeignKey, Enum as SQLEnum, Index, DateTime, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UpdateTimestampMixin


class MessageRole(str, enum.Enum):
    """
    Message role enumeration
    Defines who sent the message in a conversation
    """
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class User(Base, TimestampMixin):
    """
    User model - represents a user of the chatbot system
    
    Each user can have multiple conversations.
    Uses UUID for security and scalability (prevents enumeration attacks).
    Authenticated users have email + password_hash; anonymous users (created by chat) have NULL.
    """
    __tablename__ = "users"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique user identifier"
    )
    
    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
        comment="Email for login (NULL for anonymous users)"
    )
    
    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Hashed password (NULL for anonymous users)"
    )
    
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Last time user interacted with the system"
    )
    
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Display name shown in UI"
    )
    
    username: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
        comment="Unique username (e.g. for @mentions)"
    )
    
    avatar_url: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="URL or path to profile avatar image"
    )
    
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether the user account is active"
    )
    
    # Relationships
    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",  # Delete conversations when user is deleted
        lazy="selectin",  # Optimize loading
        order_by="Conversation.created_at.desc()"
    )
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, active={self.is_active})>"


class Conversation(Base, UpdateTimestampMixin):
    """
    Conversation model - represents a chat conversation
    
    Each conversation belongs to one user and contains multiple messages
    Supports soft delete via is_archived flag (data retention for analytics)
    """
    __tablename__ = "conversations"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique conversation identifier"
    )
    
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # Performance: faster user conversation lookups
        comment="Foreign key to users table"
    )
    
    title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Conversation title (auto-generated from first message)"
    )
    
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,  # Performance: filter archived conversations efficiently
        comment="Soft delete flag - archived conversations not shown to user"
    )
    
    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="conversations"
    )
    
    messages: Mapped[List["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",  # Delete messages when conversation is deleted
        lazy="selectin",
        order_by="Message.created_at.asc()"
    )
    
    # Composite index for efficient queries
    __table_args__ = (
        Index(
            "ix_conversations_user_archived",
            "user_id",
            "is_archived"
        ),
    )
    
    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, user_id={self.user_id}, title='{self.title}')>"


class Message(Base, TimestampMixin):
    """
    Message model - represents a single message in a conversation
    
    Messages can be from user, assistant (AI), or system
    Tracks token usage for cost monitoring and optimization
    """
    __tablename__ = "messages"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique message identifier"
    )
    
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # Performance: faster conversation message lookups
        comment="Foreign key to conversations table"
    )
    
    role: Mapped[MessageRole] = mapped_column(
        SQLEnum(
            MessageRole,
            name="message_role",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        index=True,  # Performance: filter messages by role if needed
        comment="Message sender role (user, assistant, or system)"
    )
    
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Message content (supports long medical responses)"
    )
    
    token_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of tokens used (for cost tracking and analytics)"
    )
    
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
        comment="Soft delete timestamp (NULL = not deleted)"
    )
    
    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages"
    )
    
    # Composite index for efficient message retrieval
    __table_args__ = (
        Index(
            "ix_messages_conversation_created",
            "conversation_id",
            "created_at"
        ),
    )
    
    def __repr__(self) -> str:
        content_preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"<Message(id={self.id}, role={self.role.value}, content='{content_preview}')>"
