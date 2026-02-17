"""
Conversation business logic. Ownership enforced: user can only access their own conversations.
"""

import logging
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message, User

logger = logging.getLogger(__name__)


def create_conversation(
    db: Session,
    user_id: UUID,
    title: str | None = None,
) -> Conversation:
    """Create a conversation for the given user. Returns the new conversation."""
    conv = Conversation(user_id=user_id, title=title or None)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    logger.info("Conversation created: %s for user %s", conv.id, user_id)
    return conv


def list_conversations(
    db: Session,
    user_id: UUID,
    *,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Conversation], int]:
    """
    List conversations for the user. Returns (items, total_count).
    Ownership enforced by user_id (from JWT).
    """
    base = select(Conversation).where(Conversation.user_id == user_id)
    if not include_archived:
        base = base.where(Conversation.is_archived == False)
    count_stmt = select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
    if not include_archived:
        count_stmt = count_stmt.where(Conversation.is_archived == False)
    total = db.execute(count_stmt).scalar() or 0
    stmt = base.order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)
    conversations = list(db.execute(stmt).scalars().all())
    return conversations, total


def get_conversation_for_user(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
) -> Conversation | None:
    """
    Get a conversation by id only if it belongs to the user. Otherwise None.
    Caller should return 403 if None.
    """
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        return None
    return conv


def ensure_conversation_owned_by_user(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
) -> Conversation | None:
    """Alias for get_conversation_for_user (ownership check)."""
    return get_conversation_for_user(db, conversation_id, user_id)


def update_conversation_title(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
    title: str,
) -> Conversation | None:
    """Update conversation title; returns conversation or None if not owner."""
    conv = get_conversation_for_user(db, conversation_id, user_id)
    if conv is None:
        return None
    conv.title = title[:255] if len(title) > 255 else title
    db.commit()
    db.refresh(conv)
    return conv


def set_conversation_title_from_first_message(
    db: Session,
    conversation: Conversation,
    first_message_content: str,
) -> None:
    """Set conversation title from first message if title is empty."""
    if conversation.title:
        return
    conversation.title = (first_message_content[:50] + "...") if len(first_message_content) > 50 else first_message_content
    db.commit()


def delete_conversation_soft(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
) -> bool:
    """
    Soft-delete (archive) a conversation. Returns True if found and owned, False otherwise.
    """
    conv = get_conversation_for_user(db, conversation_id, user_id)
    if conv is None:
        return False
    conv.is_archived = True
    db.commit()
    logger.info("Conversation archived: %s", conversation_id)
    return True
