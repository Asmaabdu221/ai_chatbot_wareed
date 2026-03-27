"""
Conversation & Messages API. JWT Bearer only; user from token. No user_id from client.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db import get_db
from app.db.models import User
from app.schemas.conversation import ConversationCreate, ConversationRead, ConversationListResponse, ConversationUpdate
from app.schemas.message import (
    MessageCreate,
    MessageRead,
    MessageListResponse,
    SendMessageResponse,
    PrescriptionMessageCreate,
)
from app.services import conversation_service as conv_svc
from app.services import message_service as msg_svc

logger = logging.getLogger(__name__)

router = APIRouter()


def _conv_read(conv) -> ConversationRead:
    return ConversationRead(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        is_archived=conv.is_archived,
    )


def _msg_read(msg) -> MessageRead:
    return MessageRead(
        id=msg.id,
        role=msg.role.value,
        content=msg.content,
        token_count=msg.token_count,
        created_at=msg.created_at,
    )


# ---------- Conversations ----------


@router.post(
    "/conversations",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create conversation",
)
def create_conversation(
    body: ConversationCreate | None = Body(None),
    current_user: User = Depends(get_current_user),
    db: Session | None = Depends(get_db),
):
    """Create a conversation for the authenticated user. Title optional (auto from first message)."""
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="قاعدة البيانات غير مفعّلة.",
        )
    title = (body.title if body else None) or None
    conv = conv_svc.create_conversation(db, current_user.id, title=title)
    return _conv_read(conv)


@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    summary="List my conversations",
)
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session | None = Depends(get_db),
    include_archived: bool = Query(False, description="Include archived"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List conversations for the authenticated user. User from JWT only."""
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="قاعدة البيانات غير مفعّلة.",
        )
    items, total = conv_svc.list_conversations(
        db, current_user.id, include_archived=include_archived, limit=limit, offset=offset
    )
    return ConversationListResponse(
        conversations=[_conv_read(c) for c in items],
        total=total,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationRead,
    summary="Get one conversation",
)
def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session | None = Depends(get_db),
):
    """Get a conversation by id. 403 if not owner."""
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="قاعدة البيانات غير مفعّلة.")
    conv = conv_svc.get_conversation_for_user(db, conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="لا صلاحية للوصول لهذه المحادثة.")
    return _conv_read(conv)


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationRead,
    summary="Update conversation (e.g. title)",
)
def update_conversation(
    conversation_id: UUID,
    body: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session | None = Depends(get_db),
):
    """Update conversation title. 403 if not owner."""
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="قاعدة البيانات غير مفعّلة.")
    if body.title is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="يجب تقديم العنوان.")
    conv = conv_svc.update_conversation_title(db, conversation_id, current_user.id, body.title)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="لا صلاحية لتعديل هذه المحادثة.")
    return _conv_read(conv)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete (archive) conversation",
)
def delete_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session | None = Depends(get_db),
):
    """Soft-delete a conversation. 403 if not owner."""
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="قاعدة البيانات غير مفعّلة.")
    ok = conv_svc.delete_conversation_soft(db, conversation_id, current_user.id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="لا صلاحية لحذف هذه المحادثة.")


# ---------- Messages ----------


from fastapi import UploadFile, File, Form

@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SendMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send message and get AI reply",
)
async def send_message(
    request: Request,
    conversation_id: UUID,
    content: str = Form(None),
    message: Optional[str] = Form(None),
    attachment: Optional[UploadFile] = File(None),
    attachment_type: Optional[str] = Form(None),
    conversation_id_form: Optional[str] = Form(None, alias="conversation_id"),
    # Support legacy JSON if no Form data is sent
    body: Optional[MessageCreate] = Body(None),
    current_user: User = Depends(get_current_user),
    db: Session | None = Depends(get_db),
):
    """
    Send a user message. Supports:
    1. JSON (content field)
    2. Form-data (content/message + optional attachment)
    """
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="قاعدة البيانات غير مفعّلة.")
    final_content = (content or message or (body.content if body else "")).strip()
    if not final_content:
        try:
            payload = await request.json()
            if isinstance(payload, dict):
                final_content = str(payload.get("content") or payload.get("message") or "").strip()
        except Exception:
            # Multipart/form-data requests are valid and may not parse as JSON
            pass

    is_audio_attachment = bool(attachment and (attachment_type or "").lower() == "audio")
    logger.info(
        "attachment checkpoint | received=%s | filename=%s | form_attachment_type=%s | upload_content_type=%s",
        bool(attachment),
        getattr(attachment, "filename", None),
        attachment_type,
        getattr(attachment, "content_type", None),
    )
    if not final_content:
        if attachment and not is_audio_attachment:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="يرجى كتابة سؤالك حول المرفق قبل الإرسال.")
        if not attachment:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="محتوى الرسالة مطلوب.")
    try:
        if attachment:
            file_bytes = await attachment.read()
            result = msg_svc.send_message_with_attachment(
                db, conversation_id, current_user.id, final_content or "",
                attachment_content=file_bytes,
                attachment_filename=attachment.filename,
                attachment_type=attachment_type
            )
        else:
            result = msg_svc.send_message_with_ai(db, conversation_id, current_user.id, final_content)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("send_message failed: %s", e)
        from app.core.config import settings
        detail = str(e) if getattr(settings, "DEBUG", False) else "حدث خطأ أثناء معالجة الرسالة."
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail)

    if result is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="لا صلاحية لهذه المحادثة.")
    
    user_msg, assistant_msg = result
    return SendMessageResponse(
        user_message=_msg_read(user_msg),
        assistant_message=_msg_read(assistant_msg),
    )


@router.post(
    "/conversations/{conversation_id}/messages/prescription",
    response_model=SendMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save prescription result (no AI)",
)
def save_prescription_messages(
    conversation_id: UUID,
    body: PrescriptionMessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session | None = Depends(get_db),
):
    """Save prescription user + assistant messages without calling AI."""
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="قاعدة البيانات غير مفعّلة.",
        )
    result = msg_svc.add_prescription_messages(
        db, conversation_id, current_user.id,
        body.user_content, body.assistant_content,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="لا صلاحية لهذه المحادثة.")
    user_msg, assistant_msg = result
    return SendMessageResponse(
        user_message=_msg_read(user_msg),
        assistant_message=_msg_read(assistant_msg),
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="List messages in conversation",
)
def list_messages(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session | None = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List messages in a conversation. 403 if not owner."""
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="قاعدة البيانات غير مفعّلة.")
    out = msg_svc.list_messages_for_user(db, conversation_id, current_user.id, limit=limit, offset=offset)
    if out is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="لا صلاحية لهذه المحادثة.")
    messages, total = out
    return MessageListResponse(
        messages=[_msg_read(m) for m in messages],
        total=total,
    )
