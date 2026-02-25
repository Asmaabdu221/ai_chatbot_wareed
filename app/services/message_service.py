"""
Message business logic and AI integration.
Ownership enforced via conversation belonging to user.
AI logic isolated here (OpenAI or other providers).
"""

import logging
import os
import re
import tempfile
import json
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
from app.services.context_cache import get_context_cache
from app.data.branches_service import (
    get_available_cities,
    find_branches_by_city,
)

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


_LIGHT_INTENT_CITIES = {
    "الرياض", "جدة", "مكة", "المدينه", "المدينة", "الدمام", "الخبر", "القصيم", "تبوك", "ابها", "أبها",
    "حائل", "جازان", "الطايف", "الطائف", "الجبيل", "خميس مشيط", "نجران", "الاحساء", "الأحساء",
}


def _normalize_light(text: str) -> str:
    value = (text or "").strip().lower()
    if not value:
        return ""
    value = re.sub(r"[\u064B-\u065F\u0670]", "", value)
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = value.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    value = re.sub(r"[^\w\s\u0600-\u06FF]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _contains_any(text: str, keywords: set[str]) -> bool:
    return any(k in text for k in keywords)


def _detect_city_or_area(text: str) -> tuple[bool, str]:
    n = _normalize_light(text)
    for city in _LIGHT_INTENT_CITIES:
        if _normalize_light(city) in n:
            return True, city
    if any(w in n for w in {"حي", "الحي", "المنطقة", "منطقه", "المنطقه", "district", "area"}):
        return True, "area"
    return False, ""


def _classify_light_intent(text: str) -> tuple[str, dict]:
    raw = (text or "").strip().lower()
    n = _normalize_light(text)
    merged = f"{raw} {n}".strip()
    has_city, city = _detect_city_or_area(text)
    meta = {"has_city_or_area": has_city, "city_or_area": city}

    if _contains_any(merged, {"متى تطلع", "متى تجهز", "مدة النتيجة", "مده النتيجه", "وقت النتيجة", "وقت النتيجه", "كم يوم", "النتائج", "النتايج", "turnaround", "results time"}):
        return "result_time", meta
    if _contains_any(merged, {"اقرب فرع", "أقرب فرع", "وين الفرع", "مكان الفرع", "موقع الفرع", "branch", "location", "وين اقرب", "وين اقرب فرع"}):
        return "branch_location", meta
    if _contains_any(merged, {"كم سعر", "السعر", "اسعار", "أسعار", "تكلفة", "تكلفه", "price", "cost"}):
        return "pricing", meta
    if _contains_any(merged, {"استلام النتيجه", "استلام النتيجة", "كيف استلم", "كيف توصل النتيجه", "واتساب", "ايميل", "email", "تطبيق", "delivery"}):
        return "result_delivery", meta
    if _contains_any(merged, {"شكوى", "شكوي", "مشكلة", "مشكله", "غير راضي", "مو راضي", "سيئة", "سيئه", "complaint"}):
        return "complaint", meta
    return "other", meta


def _example_matches_intent(example: str, intent_label: str) -> bool:
    if intent_label == "other":
        return True
    n = _normalize_light(example)
    keywords_map = {
        "result_time": {"نتيجه", "نتيجة", "تطلع", "جاهزه", "جاهزة", "وقت"},
        "branch_location": {"فرع", "عنوان", "موقع", "اقرب"},
        "pricing": {"سعر", "تكلفه", "تكلفة", "price", "cost"},
        "result_delivery": {"واتساب", "ايميل", "email", "تطبيق", "استلام"},
        "complaint": {"شكوى", "شكوي", "اعتذار", "تعويض", "اسفين", "مشكلة", "مشكله"},
    }
    return _contains_any(n, keywords_map.get(intent_label, set()))


def _build_style_guidance_block_for_intent(query: str, intent_label: str) -> str:
    if not getattr(settings, "ENABLE_STYLE_RAG", True):
        return ""
    try:
        raw_examples = search_style_examples(
            query=query,
            top_k=max(getattr(settings, "STYLE_TOP_K", 3) * 4, 3),
        )
    except Exception as exc:
        logger.debug("Style retrieval skipped: %s", exc)
        return ""
    if not raw_examples:
        return ""

    filtered = [ex for ex in raw_examples if _example_matches_intent(ex, intent_label)]
    chosen = filtered[: getattr(settings, "STYLE_TOP_K", 3)] if filtered else raw_examples[: getattr(settings, "STYLE_TOP_K", 3)]
    if not chosen:
        return ""

    lines = ["🎯 **Style Guidance Examples (tone only):**"]
    for i, ex in enumerate(chosen, 1):
        lines.append(f"{i}. {ex}")
    lines.append("Use these examples for tone and phrasing only, not for medical facts.")
    return "\n".join(lines)


def _filter_rag_results_by_intent(rag_results: list[dict], intent_label: str) -> list[dict]:
    if intent_label in {"branch_location", "result_delivery", "complaint"}:
        return []
    if intent_label != "pricing":
        return rag_results
    filtered: list[dict] = []
    for row in rag_results:
        test = row.get("test") or {}
        if test.get("price") is not None:
            filtered.append(row)
    return filtered


def _format_rag_results_context(rag_results: list[dict], include_prices: bool = True) -> str:
    if not rag_results:
        return ""
    parts = ["📊 **معلومات التحاليل ذات الصلة:**\n"]
    for i, row in enumerate(rag_results[:3], 1):
        test = row.get("test") or {}
        lines = [f"🔬 **{test.get('analysis_name_ar', 'غير متوفر')}**"]
        if test.get("analysis_name_en"):
            lines.append(f"   ({test.get('analysis_name_en')})")
        if test.get("description"):
            lines.append(f"\n📝 **الوصف:** {test.get('description')}")
        if include_prices and test.get("price") is not None:
            lines.append(f"\n💵 **السعر:** {test.get('price')}")
        if test.get("category"):
            lines.append(f"\n📂 **التصنيف:** {test.get('category')}")
        parts.append(f"\n{i}. " + "\n".join(lines) + "\n" + "-" * 50 + "\n")
    return "".join(parts)


def _branch_location_prompt(city_or_area: str = "") -> str:
    if city_or_area and city_or_area != "area":
        return (
            f"لتحديد أقرب فرع في {city_or_area} بدقة، شاركنا اسم الحي/المنطقة. "
            f"وللدعم المباشر تقدر تتواصل على {settings.CUSTOMER_SERVICE_PHONE}."
        )
    return (
        "عشان نحدد أقرب فرع لك بدقة، اكتب المدينة أو الحي. "
        f"وللدعم المباشر تقدر تتواصل على {settings.CUSTOMER_SERVICE_PHONE}."
    )


def _user_explicitly_asked_home_visit(text: str) -> bool:
    n = _normalize_light(text)
    return any(k in n for k in {"زيارة منزلية", "سحب منزلي", "home visit", "منزلي"})


def _sanitize_branch_location_response(text: str, has_city_or_area: bool, allow_home_visit: bool = False) -> str:
    n = _normalize_light(text)
    if not allow_home_visit and any(k in n for k in {"زيارة منزلية", "سحب منزلي", "home visit", "منزلي"}):
        if not has_city_or_area:
            return _branch_location_prompt()
        return (
            "لتحديد أقرب فرع بدقة داخل مدينتك، اكتب اسم الحي/المنطقة "
            f"أو تواصل مع خدمة العملاء على {settings.CUSTOMER_SERVICE_PHONE}."
        )
    return text


def _has_verified_branch_info(kb_context: str) -> bool:
    raw_text = (kb_context or "").lower()
    text = _normalize_light(kb_context or "")
    if not raw_text and not text:
        return False
    raw_signals = ("العنوان", "ساعات العمل", "اوقات العمل", "مواعيد العمل", "أوقات العمل")
    if any(sig in raw_text for sig in raw_signals):
        return True
    strong_signals = (
        "العنوان",
        "ساعات العمل",
        "اوقات العمل",
        "مواعيد العمل",
    )
    if "العنوان" in text and any(sig in text for sig in ("ساعات العمل", "اوقات العمل", "مواعيد العمل", "دوام")):
        return True
    if any(sig in text for sig in strong_signals):
        return True
    return bool(re.search(r"(فرع|branch).{0,40}(العنوان|ساعات|دوام|مواعيد)", text))


def _ensure_result_time_clause(text: str, light_intent: str) -> str:
    if light_intent != "result_time":
        return text
    required_clause = "بعض الفحوصات قد تحتاج وقت أطول حسب نوعها"
    if required_clause in (text or ""):
        return text
    clean = (text or "").strip()
    if not clean:
        return required_clause
    return f"{clean}\n\n{required_clause}"


def _branch_state_key(conversation_id: UUID) -> str:
    return f"branch_selection:{conversation_id}"


def _to_western_digits(text: str) -> str:
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    return (text or "").translate(trans)


def _extract_number_choice(text: str) -> int | None:
    raw = _to_western_digits((text or "").strip())
    m = re.fullmatch(r"\s*(\d{1,2})\s*", raw)
    if not m:
        return None
    return int(m.group(1))


def _store_branch_selection(conversation_id: UUID, city: str, branches: list[dict]) -> None:
    payload = {"city": city, "branches": branches}
    get_context_cache().set(_branch_state_key(conversation_id), json.dumps(payload, ensure_ascii=False))


def _load_branch_selection(conversation_id: UUID) -> dict | None:
    raw = get_context_cache().get(_branch_state_key(conversation_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def _branch_phone() -> str:
    configured = (getattr(settings, "CUSTOMER_SERVICE_PHONE", "") or "").strip()
    if configured:
        return configured
    return "920003694"


def _format_branch_item(idx: int, branch: dict) -> str:
    lines = [f"{idx}) {branch.get('branch_name', '').strip()}"]
    if branch.get("hours"):
        lines.append(branch["hours"].strip())
    lines.append(f"رابط الموقع: {branch.get('maps_url', '').strip()}")
    return "\n".join(lines)


def _format_city_branches_reply(city: str, branches: list[dict]) -> str:
    lines = [f"هذه فروعنا المتوفرة في {city}:"]
    for i, b in enumerate(branches, 1):
        lines.append("")
        lines.append(_format_branch_item(i, b))
    lines.append("")
    lines.append("اكتب اسم الحي أو رقم الفرع إذا تحب أحدد لك الأنسب.")
    return "\n".join(lines)


def _extract_city_from_query(query: str) -> str:
    n = _normalize_light(query)
    cities = sorted(get_available_cities(), key=lambda x: len(_normalize_light(x)), reverse=True)
    for city in cities:
        city_n = _normalize_light(city)
        if city_n and city_n in n:
            return city
    return ""


def _extract_city_and_district(query: str) -> tuple[str, str]:
    city = _extract_city_from_query(query)
    n = _normalize_light(query)
    if city:
        city_n = _normalize_light(city)
        n = n.replace(city_n, " ")
    n = re.sub(r"\b(وين|اقرب|أقرب|فرع|الفروع|مدينة|مدينه|في|ابي|ابغى|لو سمحت|حدد|لي|لوسمحت)\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return city, n


def _match_city_in_catalog(city_query: str) -> str:
    if not city_query:
        return ""
    cands = get_available_cities()
    qn = _normalize_light(city_query)
    for c in cands:
        cn = _normalize_light(c)
        if qn == cn or qn in cn or cn in qn:
            return c
    return ""


def _branch_lookup_bypass_reply(question: str, conversation_id: UUID, light_intent: str) -> str | None:
    # Step 4: numeric selection from previously shown list
    choice = _extract_number_choice(question)
    if choice is not None:
        cached = _load_branch_selection(conversation_id)
        if cached and isinstance(cached.get("branches"), list):
            branches = cached["branches"]
            if 1 <= choice <= len(branches):
                b = branches[choice - 1]
                lines = [f"الفرع رقم {choice}:", b.get("branch_name", "").strip()]
                if b.get("hours"):
                    lines.append(b["hours"].strip())
                lines.append(f"رابط الموقع: {b.get('maps_url', '').strip()}")
                lines.append(f"ولأي مساعدة إضافية تقدر تتواصل مع خدمة العملاء على {_branch_phone()}")
                return "\n".join(lines)

    if light_intent != "branch_location":
        return None

    # Case A: no city
    city_raw, district = _extract_city_and_district(question)
    if not city_raw:
        return "عشان أحدد أقرب فرع، اكتب اسم المدينة (مثال: الرياض / جدة) أو المدينة + الحي."

    city = _match_city_in_catalog(city_raw)
    if not city:
        cities = get_available_cities()
        lines = [f"حالياً لا يوجد لدينا فروع في {city_raw}.", "", "الفروع المتوفرة لدينا حالياً في:"]
        for c in cities:
            lines.append(f"- {c}")
        lines.append("")
        lines.append(f"ولأي مساعدة إضافية تقدر تتواصل مع خدمة العملاء على {_branch_phone()}")
        return "\n".join(lines)

    city_branches = find_branches_by_city(city)
    if not city_branches:
        lines = [f"حالياً لا يوجد لدينا فروع في {city}.", "", "الفروع المتوفرة لدينا حالياً في:"]
        for c in get_available_cities():
            lines.append(f"- {c}")
        lines.append("")
        lines.append(f"ولأي مساعدة إضافية تقدر تتواصل مع خدمة العملاء على {_branch_phone()}")
        return "\n".join(lines)

    # Case C: city + district
    if district:
        district_hits = []
        qn = _normalize_light(district)
        for b in city_branches:
            if qn and (qn in _normalize_light(b.get("branch_name", "")) or qn in _normalize_light(b.get("group", ""))):
                district_hits.append(b)
        if district_hits:
            _store_branch_selection(conversation_id, city, district_hits)
            return _format_city_branches_reply(city, district_hits)
        _store_branch_selection(conversation_id, city, city_branches)
        return (
            f"ما لقينا الحي المذكور بالاسم داخل قائمتنا، لكن هذه فروع {city} المتوفرة:\n\n"
            + _format_city_branches_reply(city, city_branches).replace(f"هذه فروعنا المتوفرة في {city}:\n", "", 1)
        )

    # Case B: city only
    _store_branch_selection(conversation_id, city, city_branches)
    return _format_city_branches_reply(city, city_branches)


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
    user_asked_home_visit = _user_explicitly_asked_home_visit(question_for_ai)

    light_intent, light_intent_meta = _classify_light_intent(question_for_ai)
    logger.info(
        "light intent classification | intent=%s | meta=%s",
        light_intent,
        light_intent_meta,
    )

    branch_bypass_reply = _branch_lookup_bypass_reply(question_for_ai, conversation_id, light_intent)
    if branch_bypass_reply:
        assistant_msg = add_message(
            db,
            conversation_id,
            MessageRole.ASSISTANT,
            branch_bypass_reply,
            token_count=0,
        )
        db.commit()
        db.refresh(assistant_msg)
        return user_msg, assistant_msg

    if light_intent == "branch_location" and not light_intent_meta.get("has_city_or_area"):
        assistant_msg = add_message(
            db,
            conversation_id,
            MessageRole.ASSISTANT,
            _branch_location_prompt(),
            token_count=0,
        )
        db.commit()
        db.refresh(assistant_msg)
        return user_msg, assistant_msg

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

    if light_intent == "branch_location":
        verified_branch_answer = _direct_kb_faq_answer(question_for_ai, "branches_locations")
        if verified_branch_answer and _has_verified_branch_info(verified_branch_answer):
            verified_branch_answer = _sanitize_branch_location_response(
                verified_branch_answer,
                bool(light_intent_meta.get("has_city_or_area")),
                allow_home_visit=user_asked_home_visit,
            )
            assistant_msg = add_message(
                db,
                conversation_id,
                MessageRole.ASSISTANT,
                verified_branch_answer,
                token_count=0,
            )
            db.commit()
            db.refresh(assistant_msg)
            return user_msg, assistant_msg
        assistant_msg = add_message(
            db,
            conversation_id,
            MessageRole.ASSISTANT,
            _branch_location_prompt(light_intent_meta.get("city_or_area") or ""),
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
        if light_intent == "branch_location" or intent == "working_hours":
            if not faq_answer or not _has_verified_branch_info(faq_answer):
                assistant_msg = add_message(
                    db,
                    conversation_id,
                    MessageRole.ASSISTANT,
                    _branch_location_prompt(light_intent_meta.get("city_or_area") or ""),
                    token_count=0,
                )
                db.commit()
                db.refresh(assistant_msg)
                return user_msg, assistant_msg
            faq_answer = _sanitize_branch_location_response(
                faq_answer,
                bool(light_intent_meta.get("has_city_or_area")),
                allow_home_visit=user_asked_home_visit,
            )
            assistant_msg = add_message(db, conversation_id, MessageRole.ASSISTANT, faq_answer, token_count=0)
            db.commit()
            db.refresh(assistant_msg)
            return user_msg, assistant_msg
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
            rag_results = _filter_rag_results_by_intent(rag_results, light_intent)
            rag_has_hit = bool(rag_results)
            rag_chunk_count = len(rag_results)
            rag_top_score = float(rag_results[0]["score"]) if rag_results else 0.0
            logger.info(
                "retrieval rag | called=yes | chunks=%s | top_score=%.3f | has_hit=%s",
                rag_chunk_count,
                rag_top_score,
                bool(rag_has_hit),
            )
            if rag_has_hit:
                rag_context = _format_rag_results_context(rag_results, include_prices=True)
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

    style_guidance_block = _build_style_guidance_block_for_intent(question_for_ai, light_intent)
    intent_guidance_block = f"Intent: {light_intent}"
    combined_context = knowledge_context
    combined_context = "\n\n".join(
        [part for part in [knowledge_context, intent_guidance_block, style_guidance_block] if part]
    ) or None

    logger.info(
        "prompt context injection | context_injected=%s | context_len=%s | style_examples=%s | light_intent=%s",
        bool(combined_context),
        len(combined_context or ""),
        bool(style_guidance_block),
        light_intent,
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

    if light_intent == "branch_location":
        assistant_content = _sanitize_branch_location_response(
            assistant_content,
            bool(light_intent_meta.get("has_city_or_area")),
            allow_home_visit=user_asked_home_visit,
        )
    assistant_content = _ensure_result_time_clause(assistant_content, light_intent)
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
