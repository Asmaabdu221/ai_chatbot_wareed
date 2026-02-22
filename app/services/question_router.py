"""
Intent Classification + Routing.
Deterministic Arabic-first heuristics with optional LLM fallback.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CONTACT_RESPONSE = "للاستفسار عن الأسعار تقدر تتواصل معنا على الرقم: 800-122-1220"
ATTACHMENT_GUIDE_RESPONSE = (
    "تفضل/ي أرفق الصورة أو ملف التحليل (PDF/صورة)، ثم اكتب/ي سؤالك مثل: "
    "(هل هذه التحاليل متوفرة؟) أو (اشرح نتيجة التحليل) واضغط/ي إرسال."
)
HOURS_FALLBACK_RESPONSE = "تقدر تتواصل معنا على 800-122-1220 ونعطيك ساعات الدوام حسب فرعك."

INTENT_CATEGORIES = [
    "greeting",
    "services_overview",
    "test_availability",
    "test_definition",
    "test_preparation",
    "sample_type",
    "pricing_inquiry",
    "packages_inquiry",
    "offers_discounts",
    "branches_locations",
    "working_hours",
    "contact_support",
    "home_visit",
    "booking_appointment",
    "report_explanation",
    "upload_report_guidance",
    "symptom_based_suggestion",
    "payment_insurance_privacy",
]

HOURS_KEYWORDS = ["ساعات الدوام", "الدوام", "متى تفتحون", "متى تقفلون", "وقت الدوام"]
_CITIES = [
    "الرياض", "جدة", "مكة", "المدينة", "الدمام", "الخبر", "القصيم", "تبوك", "أبها", "حائل", "جازان",
]

_KEYWORDS_BY_INTENT = {
    "greeting": ["السلام", "اهلا", "مرحباً", "مرحبا", "هلا", "hi", "hello"],
    "services_overview": ["خدماتكم", "ايش تقدمون", "وش تقدمون", "services", "service"],
    "test_availability": ["متوفر", "متاحة", "متاح", "عندكم", "هل يوجد", "availability", "available"],
    "test_definition": ["ما هو", "وش هو", "وش معنى", "ما معنى", "يعني ايش", "شرح تحليل", "definition", "meaning"],
    "test_preparation": ["تحضير", "صيام", "قبل التحليل", "preparation", "fasting"],
    "sample_type": ["نوع العينة", "دم او بول", "sample", "specimen"],
    "pricing_inquiry": ["سعر", "تكلفة", "كم يكلف", "price", "cost"],
    "packages_inquiry": ["باقة", "باقات", "package", "packages"],
    "offers_discounts": ["عرض", "عروض", "خصم", "discount", "offer"],
    "branches_locations": ["فرع", "فروع", "الموقع", "وين", "location", "branch"],
    "working_hours": HOURS_KEYWORDS + ["مواعيد العمل", "ساعات العمل", "hours", "open", "close"],
    "contact_support": ["رقم", "تواصل", "خدمة العملاء", "واتساب", "email", "contact"],
    "home_visit": ["منزل", "زيارة منزلية", "سحب منزلي", "home visit"],
    "booking_appointment": ["حجز", "موعد", "book", "appointment"],
    "report_explanation": ["حلل النتيجة", "فسر النتائج", "اشرح التحاليل", "وش معنى النتيجة", "result explanation"],
    "upload_report_guidance": ["ارفق", "رفع صورة", "رفع ملف", "وصفة", "pdf", "upload"],
    "symptom_based_suggestion": ["عندي", "اعاني", "أعاني", "تساقط", "دوخة", "خمول", "اعراض", "symptom"],
    "payment_insurance_privacy": ["تأمين", "تامين", "دفع", "فاتورة", "خصوصية", "بياناتي", "privacy", "insurance", "payment"],
}

LAB_CODE_PATTERN = re.compile(r"\b([A-Za-z]{2,10}\d{0,3}[A-Za-z]{0,3}\d{0,2})\b")
LAB_CODE_STOPWORDS = {
    "and", "the", "for", "with", "from", "this", "that", "what", "mean", "meaning",
    "test", "analysis", "pdf", "doc", "docx", "txt", "jpg", "jpeg", "png", "upload",
}
DEFINITION_PHRASES = [
    "ÙˆØ´ Ù…Ø¹Ù†Ù‰", "Ù…Ø§ Ù…Ø¹Ù†Ù‰", "ÙŠØ¹Ù†ÙŠ Ø§ÙŠØ´", "Ù…Ø§ Ù‡Ùˆ", "Ø´Ø±Ø­ ØªØ­Ù„ÙŠÙ„", "Ø´Ø±Ø­ ÙØ­Øµ", "Ø§Ø´Ø±Ø­ ØªØ­Ù„ÙŠÙ„", "Ø§Ø´Ø±Ø­ ÙØ­Øµ",
]
AVAILABILITY_PHRASES = [
    "Ø¹Ù†Ø¯ÙƒÙ…", "Ù…ØªÙˆÙØ±", "Ù…ØªØ§Ø­Ø©", "Ù…ØªØ§Ø­", "Ù‡Ù„ ÙŠÙˆØ¬Ø¯", "Ù‡Ù„ Ù…ØªÙˆÙØ±", "Ù‡Ù„ Ù…ØªØ§Ø­Ø©", "ØªÙˆÙØ±ÙˆÙ†",
]
PREPARATION_PHRASES = ["ØªØ­Ø¶ÙŠØ±", "ØµÙŠØ§Ù…", "Ù‚Ø¨Ù„ Ø§Ù„ØªØ­Ù„ÙŠÙ„", "Ù‚Ø¨Ù„ Ø§Ù„ÙØ­Øµ", "fasting", "preparation"]
SAMPLE_PHRASES = ["Ù†ÙˆØ¹ Ø§Ù„Ø¹ÙŠÙ†Ø©", "Ø¯Ù… Ø§Ùˆ Ø¨ÙˆÙ„", "Ø¯Ù… Ø£Ùˆ Ø¨ÙˆÙ„", "sample", "specimen"]


def _normalize(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""
    t = text.strip().lower()
    t = re.sub("[^\\u0600-\\u06FFa-zA-Z0-9\\s]", " ", t)
    t = re.sub("[؟،؛]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _contains_keyword(normalized_text: str, keyword: str) -> bool:
    kw = _normalize(keyword)
    if not kw:
        return False
    padded = f" {normalized_text} "
    return f" {kw} " in padded


def _has_any_phrase(normalized_text: str, phrases: List[str]) -> bool:
    return any(_contains_keyword(normalized_text, p) for p in phrases)


def _detect_lab_tokens(text: str) -> List[str]:
    if not text:
        return []
    detected: List[str] = []
    seen_upper: set[str] = set()
    for match in LAB_CODE_PATTERN.finditer(text):
        token = (match.group(1) or "").strip()
        if not token:
            continue
        token_lower = token.lower()
        if token_lower in LAB_CODE_STOPWORDS:
            continue
        if len(token) <= 1:
            continue
        token_upper = token.upper()
        if token_upper in seen_upper:
            continue
        seen_upper.add(token_upper)
        detected.append(token)
    return detected


def _clean_analysis_name(candidate: str, detected_tokens: List[str]) -> str:
    value = (candidate or "").strip()
    if not value:
        return ""
    for token in detected_tokens:
        if re.search(rf"\b{re.escape(token)}\b", value, re.IGNORECASE):
            return token
    value = re.sub(r"^(Ù‡Ø°Ø§|Ù‡Ø§Ø°Ø§|Ù‡Ø°ÙŠ|Ù‡Ø°Ø§ Ø§Ù„ØªØ­Ù„ÙŠÙ„|Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ù‡Ø°Ø§|ØªØ­Ù„ÙŠÙ„|ÙØ­Øµ)\s+", "", value, flags=re.IGNORECASE)
    return value.strip()


def _tokens(normalized_text: str) -> set[str]:
    out: set[str] = set()
    for tok in (normalized_text or "").split():
        if not tok:
            continue
        out.add(tok)
        if tok.startswith("ال") and len(tok) > 3:
            out.add(tok[2:])
    return out


def _extract_slots(message: str) -> Dict[str, Any]:
    text = (message or "").strip()
    normalized = _normalize(text)
    slots: Dict[str, Any] = {}
    detected_tokens = _detect_lab_tokens(text)
    if detected_tokens:
        slots["detected_tokens"] = detected_tokens
    for city in _CITIES:
        if city in text:
            slots["city"] = city
            break
    m = re.search(r"(?:تحليل|فحص)\s+([^\n،,.!?]{2,80})", text, re.IGNORECASE)
    if m:
        cleaned = _clean_analysis_name(m.group(1), detected_tokens)
        if cleaned:
            slots["analysis_name"] = cleaned
    elif detected_tokens:
        slots["analysis_name"] = detected_tokens[0]
    pkg = re.search(r"(?:باقة|باقات)\s+([^\n،,.!?]{2,80})", text, re.IGNORECASE)
    if pkg:
        slots["package_name"] = pkg.group(1).strip()
    sym = re.search(r"(?:عندي|اعاني من|أعاني من)\s+([^\n،,.!?]{2,80})", text, re.IGNORECASE)
    if sym:
        slots["symptom"] = sym.group(1).strip()
    if "pdf" in normalized or "ملف" in normalized:
        slots["attachment_hint"] = "document"
    if "صورة" in normalized:
        slots["attachment_hint"] = "image"
    return slots

def _heuristic_intent(message: str) -> Tuple[str, float]:
    normalized = _normalize(message)
    toks = _tokens(normalized)
    detected_tokens = _detect_lab_tokens(message)
    if not normalized:
        return "greeting", 0.2

    if detected_tokens:
        if _has_any_phrase(normalized, DEFINITION_PHRASES):
            return "test_definition", 0.97
        if _has_any_phrase(normalized, AVAILABILITY_PHRASES):
            return "test_availability", 0.97
        if _has_any_phrase(normalized, PREPARATION_PHRASES):
            return "test_preparation", 0.93
        if _has_any_phrase(normalized, SAMPLE_PHRASES):
            return "sample_type", 0.93

    if ("متوفر" in toks or "available" in toks) and ({"تحليل", "فحص"} & toks):
        return "test_availability", 0.9
    if {"تحضير", "صيام", "fasting", "preparation"} & toks:
        return "test_preparation", 0.9
    if {"باقة", "باقات", "package", "packages"} & toks:
        return "packages_inquiry", 0.92
    if {"رقم", "اتواصل", "تواصل", "contact", "whatsapp", "ايميل"} & toks:
        return "contact_support", 0.9
    if {"احجز", "حجز", "موعد", "appointment", "book"} & toks:
        return "booking_appointment", 0.9
    if {"symptom", "symptoms", "عندي", "اعاني", "دوخة", "خمول", "تساقط"} & toks:
        return "symptom_based_suggestion", 0.88
    if {"تأمين", "تامين", "دفع", "الدفع", "خصوصية", "privacy", "insurance", "payment"} & toks:
        return "payment_insurance_privacy", 0.9
    if any(_contains_keyword(normalized, k) for k in ["وش معنى", "ما معنى", "يعني ايش", "ما هو"]):
        if _contains_keyword(normalized, "النتيجة") or _contains_keyword(normalized, "النتايج"):
            return "report_explanation", 0.92
        return "test_definition", 0.9
    if any(_contains_keyword(normalized, k) for k in ["موقعكم", "وين فرع", "العنوان", "branch location"]):
        return "branches_locations", 0.9
    if any(_contains_keyword(normalized, k) for k in ["home visit", "زيارة منزلية", "سحب منزلي"]):
        return "home_visit", 0.95
    if any(_contains_keyword(normalized, k) for k in ["طرق الدفع", "الدفع", "تأمين", "خصوصية"]):
        return "payment_insurance_privacy", 0.92

    best_intent = "services_overview"
    best_score = 0
    for intent, kws in _KEYWORDS_BY_INTENT.items():
        score = 0
        for kw in kws:
            if _contains_keyword(normalized, kw):
                score += 1
        if score > best_score:
            best_score = score
            best_intent = intent
    confidence = min(0.99, 0.4 + 0.15 * best_score) if best_score else 0.35
    return best_intent, confidence

def _llm_fallback_classify(message: str) -> Optional[Dict[str, Any]]:
    # Optional path only when API is available; safe to skip.
    try:
        from openai import OpenAI
        from app.core.config import settings

        client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=8.0, max_retries=0)
        prompt = (
            "صنف الرسالة إلى intent واحد فقط من: "
            + ", ".join(INTENT_CATEGORIES)
            + ". أعد JSON فقط بالمفاتيح: intent, confidence."
        )
        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You output strict JSON only."},
                {"role": "user", "content": f"{prompt}\n\nالرسالة: {message}"},
            ],
            temperature=0,
            max_tokens=120,
        )
        raw = (resp.choices[0].message.content or "").strip()
        parsed = json.loads(raw)
        if parsed.get("intent") in INTENT_CATEGORIES:
            return parsed
    except Exception:
        return None
    return None


def classify_intent(message: str) -> Dict[str, Any]:
    intent, confidence = _heuristic_intent(message)
    slots = _extract_slots(message)
    detected_tokens = slots.get("detected_tokens") or []

    if confidence < 0.5 and str(__import__("os").environ.get("INTENT_LLM_FALLBACK", "")).lower() in {"1", "true", "yes"}:
        llm_pick = _llm_fallback_classify(message)
        if llm_pick and llm_pick.get("intent") in INTENT_CATEGORIES:
            intent = llm_pick["intent"]
            confidence = float(llm_pick.get("confidence") or 0.6)

    needs_clarification = False
    clarifying_question = ""
    if "analysis_name" not in slots and detected_tokens:
        slots["analysis_name"] = detected_tokens[0]

    if intent in {"pricing_inquiry", "test_availability", "test_definition", "test_preparation", "sample_type"}:
        if "analysis_name" not in slots:
            needs_clarification = True
            clarifying_question = "أكيد، تقصد/ين أي تحليل بالضبط؟"
    elif intent == "branches_locations" and "city" not in slots:
        needs_clarification = True
        clarifying_question = "أي مدينة حاب/ة تعرف/ين عنها؟"
    elif intent == "packages_inquiry" and "package_name" not in slots:
        clarifying_question = "تبغى/ين باقات فحص عام ولا باقة معينة؟"
        needs_clarification = True

    return {
        "intent": intent,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "slots": slots,
        "needs_clarification": needs_clarification,
        "clarifying_question": clarifying_question,
    }

def _resolve_hours_answer(message: str) -> Optional[str]:
    try:
        from app.data.knowledge_loader_v2 import get_knowledge_base

        kb = get_knowledge_base()
        query = " ".join(HOURS_KEYWORDS) + " " + (message or "")
        faq_results = kb.search_faqs(query, min_score=45, max_results=3)
        if faq_results:
            return (faq_results[0]["faq"].get("answer") or "").strip() or HOURS_FALLBACK_RESPONSE
    except Exception as exc:
        logger.warning("Hours FAQ resolution failed: %s", exc)
    return None


def route(message: str) -> Tuple[str, Optional[str]]:
    normalized = _normalize(message)
    if not normalized:
        return "general", None

    cls = classify_intent(message)
    intent = cls["intent"]

    if intent == "upload_report_guidance":
        return "upload_guide", ATTACHMENT_GUIDE_RESPONSE

    if intent in {"pricing_inquiry", "offers_discounts", "packages_inquiry"}:
        return "price", CONTACT_RESPONSE

    if intent == "working_hours":
        hours = _resolve_hours_answer(message)
        return "working_hours", (hours or HOURS_FALLBACK_RESPONSE)

    return "general", None


def get_price_response() -> str:
    return CONTACT_RESPONSE



