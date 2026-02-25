"""
Message business logic and AI integration.
Ownership enforced via conversation belonging to user.
AI logic isolated here (OpenAI or other providers).
"""

import logging
import os
import tempfile
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message, MessageRole
from app.services.conversation_service import get_conversation_for_user, set_conversation_title_from_first_message
from app.services.openai_service import openai_service
from app.services.question_router import route as route_question, classify_intent
from app.data.knowledge_loader_v2 import get_knowledge_context
from app.data.knowledge_loader_v2 import get_knowledge_base
from app.data.rag_pipeline import (
    get_grounded_context,
    is_rag_ready,
    NO_INFO_MESSAGE,
    retrieve,
    RAG_KNOWLEDGE_PATH,
    RAG_EMBEDDINGS_PATH,
)
from app.core.config import settings
from app.utils.arabic_normalizer import normalize_for_matching
from app.services.report_parser_service import parse_lab_report_text, compose_report_summary, is_report_explanation_request
from app.services.response_fallback_service import sanitize_for_ui, compose_context_fallback
from app.data.style_pipeline import search_style_examples

logger = logging.getLogger(__name__)

_ESCALATION_BLOCKED_PHRASES = (
    "we will contact you",
    "we'll contact you",
    "someone will reach out",
    "we will forward your request",
    "سوف نتواصل",
    "سنقوم بالتواصل",
    "سيتم التواصل",
    "راح نتواصل",
    "سنحول طلبك",
    "راح نحول طلبك",
)


def _build_direct_support_message() -> str:
    return (
        "للحصول على دعم مباشر، تقدر تتواصل مع خدمة العملاء على الرقم التالي: "
        f"{settings.CUSTOMER_SERVICE_PHONE}"
    )


def _enforce_escalation_policy(text: str) -> str:
    content = (text or "").strip()
    lowered = content.lower()
    if any(phrase in lowered for phrase in _ESCALATION_BLOCKED_PHRASES):
        return _build_direct_support_message()
    return content


def _build_style_guidance_block(query: str) -> str:
    if not getattr(settings, "ENABLE_STYLE_RAG", True):
        return ""
    try:
        examples = search_style_examples(
            query=query,
            top_k=getattr(settings, "STYLE_TOP_K", 3),
        )
    except Exception as exc:
        logger.debug("Style retrieval skipped: %s", exc)
        return ""

    if not examples:
        return ""

    lines = ["🎯 **Style Guidance Examples (tone only):**"]
    for i, ex in enumerate(examples, 1):
        lines.append(f"{i}. {ex}")
    lines.append("Use these examples for tone and phrasing only, not for medical facts.")
    return "\n".join(lines)


def _direct_kb_faq_answer(question: str, intent: str) -> str | None:
    try:
        kb = get_knowledge_base()
        query_seed = question
        if intent == "working_hours":
            query_seed = "ساعات الدوام وقت الدوام متى تفتحون متى تقفلون " + question
        elif intent == "contact_support":
            query_seed = "رقم التواصل خدمة العملاء واتساب ايميل " + question
        elif intent == "branches_locations":
            query_seed = "فروع الموقع العنوان المدينة " + question
        elif intent == "home_visit":
            query_seed = "زيارة منزلية سحب منزلي " + question
        elif intent == "payment_insurance_privacy":
            query_seed = "الدفع التأمين الخصوصية البيانات " + question
        results = kb.search_faqs(query_seed, min_score=45, max_results=1)
        if results:
            return sanitize_for_ui(results[0]["faq"].get("answer") or "")
    except Exception as exc:
        logger.warning("KB FAQ direct route failed: %s", exc)
    return None


def _symptom_guidance(question: str) -> str:
    n = normalize_for_matching(question or "")
    picks = ["CBC", "Ferritin", "TSH", "Vitamin D (25 OH-Vit D -Total)"]
    if "سكر" in n or "دوخه" in n:
        picks.append("HbA1c")
    unique = []
    for p in picks:
        if p not in unique:
            unique.append(p)
    return (
        "حسب الأعراض المذكورة غالباً يبدأ الطبيب بفحوصات:\n"
        + "\n".join([f"- {p}" for p in unique[:5]])
        + "\n\nهذا توجيه تثقيفي فقط، والتشخيص النهائي يكون عند الطبيب."
    )


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


from typing import Optional
from app.services.document_extract_service import extract_text_from_document
from app.services.prescription_vision_service import process_prescription_image


def _transcribe_audio_bytes(audio_bytes: bytes, filename: str = "voice-message.webm") -> str:
    if not audio_bytes:
        raise ValueError("Empty audio data.")
    suffix = os.path.splitext(filename)[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_audio:
        temp_audio.write(audio_bytes)
        temp_audio_path = temp_audio.name
    try:
        try:
            from openai import OpenAI
        except Exception:
            raise ValueError("Voice transcription service is currently unavailable.")
        client = OpenAI()
        with open(temp_audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
        return (getattr(transcript, "text", "") or "").strip()
    except Exception as exc:
        logger.warning("Audio transcription failed: %s", exc)
        raise ValueError("Failed to transcribe the voice message. Please try again.")
    finally:
        try:
            os.remove(temp_audio_path)
        except Exception:
            pass

def send_message_with_ai(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
    content: str,
) -> tuple[Message, Message] | None:
    """Legacy wrapper for text-only messages."""
    return send_message_with_attachment(db, conversation_id, user_id, content)

def send_message_with_attachment(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
    content: str,
    attachment_content: Optional[bytes] = None,
    attachment_filename: Optional[str] = None,
    attachment_type: Optional[str] = None,
) -> tuple[Message, Message] | None:
    """
    Handle message with/without attachment.
    Flow:
    1) Extract attachment text when provided.
    2) Save user message.
    3) Retrieve context from RAG + KB/FAQ.
    4) Generate grounded AI response (or deterministic price response).
    """
    conv = get_conversation_for_user(db, conversation_id, user_id)
    if conv is None:
        return None

    extracted_context = ""
    normalized_attachment_type = (attachment_type or "").lower()
    is_audio = normalized_attachment_type == "audio" or (
        attachment_filename and attachment_filename.lower().endswith((".webm", ".wav", ".mp3", ".m4a", ".ogg"))
    )
    effective_content = (content or "").strip()

    if attachment_content:
        if is_audio:
            transcript = _transcribe_audio_bytes(attachment_content, attachment_filename or "voice-message.webm")
            if not transcript:
                raise ValueError("No speech could be recognized in the voice message.")
            extracted_context = transcript
            if not effective_content:
                effective_content = transcript
        elif normalized_attachment_type == "image" or (
            attachment_filename and attachment_filename.lower().endswith((".jpg", ".jpeg", ".png"))
        ):
            try:
                ocr_result = process_prescription_image(attachment_content, "image/jpeg")
            except Exception:
                raise ValueError("Failed to analyze the attached image. Please upload a clearer image.")
            extracted_context = (ocr_result.get("response_message") or "").strip()
            if not extracted_context:
                raise ValueError("No readable content could be extracted from the attached image.")
        else:
            extracted_context = extract_text_from_document(attachment_content, attachment_filename or "")

    question_for_ai = effective_content or "Voice message"
    ai_prompt = question_for_ai
    if attachment_content:
        ai_prompt = (
            f"سياق من المرفق ({attachment_filename or 'ملف'}):\n"
            f"{extracted_context}\n\n"
            f"سؤال المستخدم: {question_for_ai}"
        )

    first_msg_count = db.execute(
        select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id,
            Message.deleted_at.is_(None),
        )
    ).scalar() or 0
    if first_msg_count == 0:
        set_conversation_title_from_first_message(db, conv, question_for_ai)

    # Persist plain user question (no attachment metadata in message bubble).
    user_msg = add_message(db, conversation_id, MessageRole.USER, question_for_ai)
    db.commit()
    db.refresh(user_msg)

    history = get_conversation_history_for_ai(db, conv, max_messages=20)

    intent_payload = classify_intent(question_for_ai)
    intent = intent_payload.get("intent", "services_overview")
    slots = intent_payload.get("slots", {}) or {}
    detected_tokens = slots.get("detected_tokens") or []
    logger.info(
        "intent classification | intent=%s | confidence=%s | slots=%s | detected_tokens=%s | needs_clarification=%s",
        intent,
        intent_payload.get("confidence"),
        slots,
        detected_tokens,
        intent_payload.get("needs_clarification"),
    )

    # Deterministic router shortcuts.
    route_type, fixed_reply = route_question(question_for_ai)
    if fixed_reply:
        logger.info("Question routed to fixed response (route=%s)", route_type)
        assistant_msg = add_message(
            db,
            conversation_id,
            MessageRole.ASSISTANT,
            sanitize_for_ui(fixed_reply),
            token_count=0,
        )
        db.commit()
        db.refresh(assistant_msg)
        return user_msg, assistant_msg

    if intent_payload.get("needs_clarification") and intent_payload.get("clarifying_question"):
        assistant_msg = add_message(
            db,
            conversation_id,
            MessageRole.ASSISTANT,
            sanitize_for_ui(intent_payload["clarifying_question"]),
            token_count=0,
        )
        db.commit()
        db.refresh(assistant_msg)
        return user_msg, assistant_msg

    if intent in {
        "branches_locations",
        "working_hours",
        "contact_support",
        "home_visit",
        "payment_insurance_privacy",
    }:
        faq_answer = _direct_kb_faq_answer(question_for_ai, intent)
        if faq_answer:
            assistant_msg = add_message(db, conversation_id, MessageRole.ASSISTANT, faq_answer, token_count=0)
            db.commit()
            db.refresh(assistant_msg)
            return user_msg, assistant_msg

    if intent == "symptom_based_suggestion":
        suggestion = _symptom_guidance(question_for_ai)
        assistant_msg = add_message(db, conversation_id, MessageRole.ASSISTANT, suggestion, token_count=0)
        db.commit()
        db.refresh(assistant_msg)
        return user_msg, assistant_msg

    # PDF report summarizer (works even if LLM is unavailable).
    is_pdf_attachment = bool(attachment_content and (attachment_filename or "").lower().endswith(".pdf"))
    wants_report_explain = intent in {"report_explanation", "test_definition"} or is_report_explanation_request(question_for_ai)
    if is_pdf_attachment and wants_report_explain and extracted_context:
        parsed_rows = parse_lab_report_text(extracted_context)
        report_reply = compose_report_summary(parsed_rows)
        assistant_msg = add_message(
            db,
            conversation_id,
            MessageRole.ASSISTANT,
            sanitize_for_ui(report_reply),
            token_count=0,
        )
        db.commit()
        db.refresh(assistant_msg)
        return user_msg, assistant_msg

    threshold = getattr(settings, "RAG_SIMILARITY_THRESHOLD", 0.58)
    merged_context_parts: list[str] = []
    rag_chunk_count = 0
    rag_top_score = 0.0
    has_kb_hit = False
    fallback_used = False

    logger.info(
        "retrieval called | query='%s' | rag_ready=%s | knowledge_index='%s' | embeddings_index='%s' | kb_namespace='%s'",
        question_for_ai[:120],
        is_rag_ready(),
        RAG_KNOWLEDGE_PATH,
        RAG_EMBEDDINGS_PATH,
        "knowledge_base_with_faq.json",
    )

    if is_rag_ready():
        try:
            rag_results, rag_has_hit = retrieve(
                question_for_ai,
                max_results=3,
                similarity_threshold=threshold,
            )
            rag_chunk_count = len(rag_results)
            rag_top_score = float(rag_results[0]["score"]) if rag_results else 0.0
            logger.info(
                "retrieval rag | called=yes | chunks=%s | top_score=%.3f | has_hit=%s",
                rag_chunk_count,
                rag_top_score,
                bool(rag_has_hit),
            )
            if rag_has_hit:
                rag_context, _ = get_grounded_context(
                    user_message=question_for_ai,
                    max_tests=3,
                    similarity_threshold=threshold,
                    include_prices=True,
                )
                if rag_context:
                    merged_context_parts.append(rag_context)
        except Exception as e:
            logger.warning("retrieval rag failed: %s", e)
    else:
        logger.info("retrieval rag | called=no | reason=rag_not_ready")

    # Broader KB retrieval (tests + FAQs/services/packages).
    try:
        kb_context = get_knowledge_context(
            user_message=question_for_ai,
            max_tests=3,
            max_faqs=2,
            include_prices=True,
        )
        has_kb_hit = bool(kb_context and "لم يتم العثور على معلومات محددة" not in kb_context)
        logger.info(
            "retrieval kb | called=yes | has_hit=%s | context_len=%s",
            has_kb_hit,
            len(kb_context or ""),
        )
        if has_kb_hit:
            merged_context_parts.append(kb_context)
    except Exception as e:
        logger.warning("retrieval kb failed: %s", e)

    knowledge_context = None
    if merged_context_parts:
        seen = set()
        unique_parts = []
        for part in merged_context_parts:
            key = part.strip()
            if key and key not in seen:
                seen.add(key)
                unique_parts.append(part)
        if unique_parts:
            knowledge_context = "\n\n".join(unique_parts)

    style_guidance_block = _build_style_guidance_block(question_for_ai)
    combined_context = knowledge_context
    if style_guidance_block:
        combined_context = "\n\n".join([part for part in [knowledge_context, style_guidance_block] if part])

    logger.info(
        "prompt context injection | context_injected=%s | context_len=%s | style_examples=%s",
        bool(combined_context),
        len(combined_context or ""),
        bool(style_guidance_block),
    )

    ai_result = openai_service.generate_response(
        user_message=ai_prompt,
        knowledge_context=combined_context,
        conversation_history=history,
    )
    llm_success = bool(ai_result.get("success"))
    assistant_content = ai_result.get("response") or "عذرًا، حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى."
    tokens = ai_result.get("tokens_used") or 0
    logger.info(
        "response generation | intent=%s | route=%s | llm_success=%s | fallback_used=%s | kb_hit=%s | rag_chunks=%s | rag_top_score=%.3f | context_len=%s",
        intent,
        route_type,
        llm_success,
        fallback_used,
        has_kb_hit,
        rag_chunk_count,
        rag_top_score,
        len(knowledge_context or ""),
    )

    if not llm_success:
        assistant_content = compose_context_fallback(question_for_ai, intent, slots, knowledge_context)
        tokens = 0
        fallback_used = True
        logger.warning(
            "llm unavailable -> fallback answer used | intent=%s | route=%s | rag_ready=%s",
            intent,
            route_type,
            is_rag_ready(),
        )
        logger.info(
            "fallback diagnostics | detected_tokens=%s | intent=%s | route=%s | kb_hit=%s | rag_chunks=%s | rag_top_score=%.3f | llm_status=failed | fallback_used=%s",
            detected_tokens,
            intent,
            route_type,
            has_kb_hit,
            rag_chunk_count,
            rag_top_score,
            fallback_used,
        )

    # If KB hit exists but model produced generic miss, retry once with explicit grounding instruction.
    if knowledge_context and ("لا تتوفر لدي معلومات" in assistant_content or NO_INFO_MESSAGE in assistant_content):
        logger.info("model returned generic miss despite retrieval hit; retrying grounded answer")
        retry_result = openai_service.generate_response(
            user_message=f"استخدم المعلومات المسترجعة للإجابة بدقة على: {question_for_ai}",
            knowledge_context=combined_context,
            conversation_history=history,
        )
        retry_response = retry_result.get("response")
        if retry_response:
            assistant_content = retry_response
            tokens = retry_result.get("tokens_used") or tokens

    assistant_content = _enforce_escalation_policy(assistant_content)

    assistant_msg = add_message(
        db,
        conversation_id,
        MessageRole.ASSISTANT,
        sanitize_for_ui(assistant_content),
        token_count=tokens,
    )
    db.commit()
    db.refresh(assistant_msg)
    return user_msg, assistant_msg
