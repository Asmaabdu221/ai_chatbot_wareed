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

INTENT_SLOT_CONTRACT: Dict[str, Dict[str, Any]] = {
    "greeting": {"required_slots": [], "required_any": [], "optional_slots": [], "clarification_question": ""},
    "services_overview": {"required_slots": [], "required_any": [], "optional_slots": [], "clarification_question": ""},
    "test_availability": {
        "required_slots": [],
        "required_any": ["analysis_name", "analysis_code"],
        "optional_slots": [],
        "clarification_question": "أكيد، اسم التحليل أو رمزه لو تكرمت/ي؟",
    },
    "test_definition": {
        "required_slots": [],
        "required_any": ["analysis_name", "analysis_code"],
        "optional_slots": [],
        "clarification_question": "وش اسم التحليل أو رمزه عشان أشرحه لك؟",
    },
    "test_preparation": {
        "required_slots": [],
        "required_any": ["analysis_name", "analysis_code"],
        "optional_slots": [],
        "clarification_question": "أكيد، وش اسم التحليل أو رمزه عشان نعطيك التحضير الصحيح؟",
    },
    "sample_type": {
        "required_slots": [],
        "required_any": ["analysis_name", "analysis_code"],
        "optional_slots": [],
        "clarification_question": "وش اسم التحليل أو رمزه عشان نحدد نوع العينة؟",
    },
    "pricing_inquiry": {
        "required_slots": [],
        "required_any": ["analysis_name", "analysis_code", "package_name"],
        "optional_slots": ["city"],
        "clarification_question": "أكيد، لأي تحليل أو باقة تبين السعر؟",
    },
    "packages_inquiry": {
        "required_slots": [],
        "required_any": [],
        "optional_slots": ["package_name", "campaign_period"],
        "clarification_question": "تبين عروض على باقة معيّنة ولا بشكل عام؟",
    },
    "offers_discounts": {
        "required_slots": [],
        "required_any": [],
        "optional_slots": ["package_name", "campaign_period"],
        "clarification_question": "تبين عروض على باقة معيّنة ولا بشكل عام؟",
    },
    "branches_locations": {
        "required_slots": [],
        "required_any": [],
        "optional_slots": ["city"],
        "clarification_question": "تمام، بأي مدينة تبين أقرب فرع؟",
    },
    "working_hours": {
        "required_slots": [],
        "required_any": [],
        "optional_slots": ["city"],
        "clarification_question": "تمام، لأي مدينة تبين ساعات الدوام؟",
    },
    "contact_support": {"required_slots": [], "required_any": [], "optional_slots": ["channel"], "clarification_question": ""},
    "home_visit": {
        "required_slots": [],
        "required_any": [],
        "optional_slots": ["city", "location_type"],
        "clarification_question": "تمام، بأي مدينة تبين السحب المنزلي؟",
    },
    "booking_appointment": {
        "required_slots": [],
        "required_any": [],
        "optional_slots": ["city", "service_name"],
        "clarification_question": "",
    },
    "report_explanation": {
        "required_slots": [],
        "required_any": [],
        "optional_slots": ["analysis_name", "attachment_hint"],
        "clarification_question": "",
    },
    "upload_report_guidance": {
        "required_slots": [],
        "required_any": [],
        "optional_slots": ["attachment_hint"],
        "clarification_question": "",
    },
    "symptom_based_suggestion": {
        "required_slots": [],
        "required_any": [],
        "optional_slots": ["symptom"],
        "clarification_question": "",
    },
    "payment_insurance_privacy": {
        "required_slots": [],
        "required_any": [],
        "optional_slots": ["payment_method"],
        "clarification_question": "",
    },
}

_KEYWORDS_BY_INTENT = {
    "greeting": ["السلام", "اهلا", "مرحباً", "مرحبا", "هلا", "hi", "hello"],
    "services_overview": ["خدماتكم", "ايش تقدمون", "وش تقدمون", "services", "service"],
    "test_availability": ["متوفر", "متاحة", "متاح", "عندكم", "هل يوجد", "availability", "available"],
    "test_definition": ["ما هو", "وش هو", "وش معنى", "ما معنى", "يعني ايش", "شرح تحليل", "definition", "meaning"],
    "test_preparation": ["تحضير", "صيام", "قبل التحليل", "preparation", "fasting"],
    "sample_type": ["نوع العينة", "دم او بول", "sample", "specimen"],
    "pricing_inquiry": ["سعر", "تكلفة", "كم يكلف", "الأسعار", "price", "cost"],
    "packages_inquiry": ["باقة", "باقات", "package", "packages"],
    "offers_discounts": ["عرض", "عروض", "خصم", "خصومات", "برومو", "رمضان", "ساري", "discount", "offer"],
    "branches_locations": ["فرع", "فروع", "الموقع", "وين", "location", "branch"],
    "working_hours": HOURS_KEYWORDS + ["مواعيد العمل", "ساعات العمل", "hours", "open", "close"],
    "contact_support": ["رقم", "تواصل", "خدمة العملاء", "واتساب", "email", "contact", "ايميل"],
    "home_visit": ["منزل", "زيارة منزلية", "سحب منزلي", "سحب عينات منزلي", "سحب من المنزل", "وريد كير", "home visit"],
    "booking_appointment": ["حجز", "موعد", "book", "appointment"],
    "report_explanation": ["حلل النتيجة", "فسر النتائج", "اشرح التحاليل", "وش معنى النتيجة", "result explanation"],
    "upload_report_guidance": ["ارفق", "رفع صورة", "رفع ملف", "وصفة", "pdf", "upload"],
    "symptom_based_suggestion": ["عندي", "اعاني", "أعاني", "تساقط", "دوخة", "خمول", "اعراض", "symptom"],
    "payment_insurance_privacy": ["تأمين", "تامين", "دفع", "فاتورة", "خصوصية", "بياناتي", "فيزا", "مدى", "تمارا", "تحويل", "privacy", "insurance", "payment"],
}

LAB_CODE_PATTERN = re.compile(r"\b([A-Za-z]{2,10}\d{0,3}[A-Za-z]{0,3}\d{0,2})\b")
LAB_CODE_STOPWORDS = {
    "and", "the", "for", "with", "from", "this", "that", "what", "mean", "meaning",
    "test", "analysis", "pdf", "doc", "docx", "txt", "jpg", "jpeg", "png", "upload",
}
DEFINITION_PHRASES = ["وش معنى", "ما معنى", "يعني ايش", "ما هو", "شرح تحليل", "شرح فحص", "اشرح تحليل", "اشرح فحص"]
AVAILABILITY_PHRASES = ["عندكم", "متوفر", "متاحة", "متاح", "هل يوجد", "هل متوفر", "هل متاحة", "توفرون"]
PREPARATION_PHRASES = ["تحضير", "صيام", "قبل التحليل", "قبل الفحص", "fasting", "preparation"]
SAMPLE_PHRASES = ["نوع العينة", "دم او بول", "دم أو بول", "sample", "specimen"]
OFFERS_KEYWORDS = ["عروض", "خصومات", "عرض", "برومو", "رمضان", "ساري"]
HOME_VISIT_KEYWORDS = ["سحب منزلي", "زيارة منزلية", "عينات من البيت", "وريد كير", "سحب من المنزل", "سحب عينات منزلي"]
PAYMENT_KEYWORDS = ["الدفع", "فيزا", "مدى", "تمارا", "تحويل", "تأمين", "تامين", "خصوصية"]
RESULTS_DELIVERY_KEYWORDS = ["واتساب", "ايميل", "email", "تطبيق"]
BRANCH_KEYWORDS = ["فرع", "فروع", "أقرب فرع", "وين الفرع", "الموقع"]


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
    value = re.sub(r"^(هذا|هاذا|هذي|هذا التحليل|التحليل هذا|تحليل|فحص)\s+", "", value, flags=re.IGNORECASE)
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
        slots["analysis_code"] = detected_tokens[0]
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

def _priority_non_analysis_intent(normalized: str, toks: set[str]) -> Optional[Tuple[str, float]]:
    if _has_any_phrase(normalized, HOURS_KEYWORDS):
        return "working_hours", 0.98
    if _has_any_phrase(normalized, HOME_VISIT_KEYWORDS) or ({"سحب", "منزلي"} <= toks):
        return "home_visit", 0.97
    if _has_any_phrase(normalized, OFFERS_KEYWORDS):
        return "offers_discounts", 0.97
    if _has_any_phrase(normalized, PAYMENT_KEYWORDS):
        return "payment_insurance_privacy", 0.96
    if _has_any_phrase(normalized, BRANCH_KEYWORDS):
        return "branches_locations", 0.95
    if _has_any_phrase(normalized, RESULTS_DELIVERY_KEYWORDS) and "نتيجة" not in normalized:
        return "contact_support", 0.92
    return None


def _heuristic_intent(message: str) -> Tuple[str, float]:
    normalized = _normalize(message)
    toks = _tokens(normalized)
    detected_tokens = _detect_lab_tokens(message)
    if not normalized:
        return "greeting", 0.2

    if _has_any_phrase(normalized, _KEYWORDS_BY_INTENT["upload_report_guidance"]):
        return "upload_report_guidance", 0.97
    if _has_any_phrase(normalized, _KEYWORDS_BY_INTENT["report_explanation"]):
        return "report_explanation", 0.96

    priority_intent = _priority_non_analysis_intent(normalized, toks)
    if priority_intent:
        return priority_intent

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
    if any(_contains_keyword(normalized, k) for k in DEFINITION_PHRASES):
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


def _resolve_clarification(intent: str, slots: Dict[str, Any]) -> Tuple[bool, str]:
    contract = INTENT_SLOT_CONTRACT.get(intent, {})
    required_slots = contract.get("required_slots") or []
    required_any = contract.get("required_any") or []
    question = contract.get("clarification_question") or ""

    missing_required = [slot for slot in required_slots if not slots.get(slot)]
    if missing_required:
        return True, question

    if required_any:
        has_any = any(bool(slots.get(slot)) for slot in required_any)
        if not has_any:
            return True, question

    return False, ""


def get_intent_contract(intent: str) -> Dict[str, Any]:
    return INTENT_SLOT_CONTRACT.get(intent, {
        "required_slots": [],
        "required_any": [],
        "optional_slots": [],
        "clarification_question": "",
    })


def evaluate_clarification_for_intent(message: str, intent: str, slots: Dict[str, Any]) -> Tuple[bool, str]:
    _ = message  # reserved for future intent-specific conditional logic.
    return _resolve_clarification(intent, slots)


def classify_intent(message: str) -> Dict[str, Any]:
    intent, confidence = _heuristic_intent(message)
    slots = _extract_slots(message)

    if confidence < 0.5 and str(__import__("os").environ.get("INTENT_LLM_FALLBACK", "")).lower() in {"1", "true", "yes"}:
        llm_pick = _llm_fallback_classify(message)
        if llm_pick and llm_pick.get("intent") in INTENT_CATEGORIES:
            intent = llm_pick["intent"]
            confidence = float(llm_pick.get("confidence") or 0.6)

    if "analysis_name" not in slots and slots.get("analysis_code"):
        slots["analysis_name"] = slots["analysis_code"]
    needs_clarification, clarifying_question = evaluate_clarification_for_intent(message, intent, slots)

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

    if intent == "working_hours":
        hours = _resolve_hours_answer(message)
        return "working_hours", (hours or HOURS_FALLBACK_RESPONSE)

    return "general", None


def get_price_response() -> str:
    return CONTACT_RESPONSE



