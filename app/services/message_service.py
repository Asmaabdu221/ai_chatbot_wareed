"""
Message business logic and AI integration.
Ownership enforced via conversation belonging to user.
AI logic isolated here (OpenAI or other providers).
"""

import logging
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message, MessageRole
from app.services.conversation_service import get_conversation_for_user, set_conversation_title_from_first_message
from app.services.openai_service import openai_service
from app.services.question_router import route as route_question
from app.data.knowledge_loader_v2 import get_knowledge_context
from app.data.rag_pipeline import (
    get_grounded_context,
    is_rag_ready,
    NO_INFO_MESSAGE,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


def list_messages_for_user(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
    *,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Message], int] | None:
    """
    List messages in a conversation. Returns (messages, total) or None if conversation not found/not owned.
    Excludes soft-deleted messages.
    """
    conv = get_conversation_for_user(db, conversation_id, user_id)
    if conv is None:
        return None
    count_stmt = select(func.count(Message.id)).where(
        Message.conversation_id == conversation_id,
        Message.deleted_at.is_(None),
    )
    total = db.execute(count_stmt).scalar() or 0
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.deleted_at.is_(None))
        .order_by(Message.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    messages = list(db.execute(stmt).scalars().all())
    return messages, total


def add_message(
    db: Session,
    conversation_id: UUID,
    role: MessageRole,
    content: str,
    token_count: int | None = None,
) -> Message:
    """Append a message to a conversation. Caller must ensure ownership."""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        token_count=token_count,
    )
    db.add(msg)
    db.flush()
    return msg


def get_conversation_history_for_ai(
    db: Session,
    conversation: Conversation,
    max_messages: int = 20,
) -> list[dict[str, str]]:
    """Load recent messages as [{role, content}] for AI context. Excludes soft-deleted."""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation.id, Message.deleted_at.is_(None))
        .order_by(Message.created_at.desc())
        .limit(max_messages)
    )
    messages = list(db.execute(stmt).scalars().all())
    messages.reverse()
    return [{"role": m.role.value, "content": m.content} for m in messages]


def add_prescription_messages(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
    user_content: str,
    assistant_content: str,
) -> tuple[Message, Message] | None:
    """Add user + assistant messages for prescription result (no AI call)."""
    conv = get_conversation_for_user(db, conversation_id, user_id)
    if conv is None:
        return None
    first_msg_count = db.execute(
        select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id,
            Message.deleted_at.is_(None),
        )
    ).scalar() or 0
    if first_msg_count == 0:
        set_conversation_title_from_first_message(db, conv, user_content)
    user_msg = add_message(db, conversation_id, MessageRole.USER, user_content)
    assistant_msg = add_message(db, conversation_id, MessageRole.ASSISTANT, assistant_content, token_count=0)
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant_msg)
    return user_msg, assistant_msg


def send_message_with_ai(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
    content: str,
) -> tuple[Message, Message] | None:
    """
    Add user message, optionally set conversation title from first message,
    generate AI response (with routing and knowledge), add assistant message.
    Returns (user_message, assistant_message) or None if conversation not owned.
    """
    conv = get_conversation_for_user(db, conversation_id, user_id)
    if conv is None:
        return None

    # First message: set conversation title if empty
    first_msg_count = db.execute(
        select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id,
            Message.deleted_at.is_(None),
        )
    ).scalar() or 0
    if first_msg_count == 0:
        set_conversation_title_from_first_message(db, conv, content)

    # Persist user message
    user_msg = add_message(db, conversation_id, MessageRole.USER, content)
    db.commit()
    db.refresh(user_msg)

    # Conversation history for AI (excluding the message we just added, so same as before)
    history = get_conversation_history_for_ai(db, conv, max_messages=20)

    # Route: price question → fixed response, no API
    route_type, fixed_reply = route_question(content)
    if route_type == "price" and fixed_reply:
        assistant_msg = add_message(db, conversation_id, MessageRole.ASSISTANT, fixed_reply, token_count=0)
        db.commit()
        db.refresh(assistant_msg)
        return user_msg, assistant_msg

    # Knowledge context: RAG (primary) or legacy
    knowledge_context = None
    try:
        if is_rag_ready():
            # RAG pipeline: hybrid retrieval, strict threshold, no hallucination
            threshold = getattr(settings, "RAG_SIMILARITY_THRESHOLD", 0.58)
            knowledge_context, has_relevant = get_grounded_context(
                user_message=content,
                max_tests=3,
                similarity_threshold=threshold,
                include_prices=True,
            )
            if not has_relevant:
                # Below threshold: return fixed message without OpenAI call
                assistant_msg = add_message(
                    db, conversation_id, MessageRole.ASSISTANT, NO_INFO_MESSAGE, token_count=0
                )
                db.commit()
                db.refresh(assistant_msg)
                return user_msg, assistant_msg
        else:
            # RAG not built: legacy knowledge loader
            knowledge_context = get_knowledge_context(
                user_message=content,
                max_tests=3,
                max_faqs=2,
                include_prices=True,
            )
            # Legacy returns context even when empty; if no tests/faqs, use no-info
            if knowledge_context and "لم يتم العثور على معلومات محددة" in knowledge_context:
                assistant_msg = add_message(
                    db, conversation_id, MessageRole.ASSISTANT, NO_INFO_MESSAGE, token_count=0
                )
                db.commit()
                db.refresh(assistant_msg)
                return user_msg, assistant_msg
    except Exception as e:
        logger.warning("Knowledge context failed: %s", e)

    # AI response
    ai_result = openai_service.generate_response(
        user_message=content,
        knowledge_context=knowledge_context,
        conversation_history=history,
    )
    assistant_content = ai_result.get("response") or "عذراً، لم أتمكن من توليد رد."
    tokens = ai_result.get("tokens_used") or 0
    assistant_msg = add_message(db, conversation_id, MessageRole.ASSISTANT, assistant_content, token_count=tokens)
    db.commit()
    db.refresh(assistant_msg)
    return user_msg, assistant_msg
