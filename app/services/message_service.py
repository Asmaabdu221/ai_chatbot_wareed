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
from datetime import datetime, timedelta, timezone
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
from app.core.runtime_paths import FAQ_INDEX_PATH, TESTS_PRICE_INDEX_PATH, path_exists
from app.utils.arabic_normalizer import normalize_for_matching
from app.utils.gender_tone import apply_gender_variant, guess_gender, safe_clarify_message
from app.services.report_parser_service import parse_lab_report_text, compose_report_summary, is_report_explanation_request
from app.services.response_fallback_service import sanitize_for_ui, compose_context_fallback
from app.data.style_pipeline import search_style_examples
from app.services.context_cache import get_context_cache
from app.utils.text_normalize import normalize_text
from app.data.branches_service import (
    get_available_cities,
    find_branches_by_city,
    load_branches_index,
)
from app.data.packages_service import (
    match_single_package,
    search_packages,
    format_package_list,
    format_package_details,
    load_packages_index,
)
from app.services.packages_rag_service import semantic_search_packages

logger = logging.getLogger(__name__)

WAREED_CUSTOMER_SERVICE_PHONE = "920003694"

_FAQ_CACHE = None
_PRICES_CACHE = None

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
        f"{WAREED_CUSTOMER_SERVICE_PHONE}"
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

_SYMPTOM_QUERY_TOKENS = {
    "اعراض",
    "أعراض",
    "عندي",
    "احس",
    "أحس",
    "اشعر",
    "أشعر",
    "الم",
    "ألم",
    "ضيق",
    "خفقان",
    "كحه",
    "كحة",
    "حراره",
    "حرارة",
    "صداع",
    "غثيان",
    "اسهال",
    "إسهال",
    "دوخه",
    "دوخة",
}

_WORKING_HOURS_TRIGGERS = {
    "ساعات الدوام",
    "دوامكم",
    "متى تفتحون",
    "متى تقفلون",
    "وقت الدوام",
    "ساعه",
    "ساعات",
    "وقت",
}

_GENERAL_PRICE_TRIGGERS = {
    "الاسعار",
    "الأسعار",
    "كم السعر",
    "بكم",
    "سعر التحليل",
    "استعلام عن الاسعار",
    "استعلام عن الأسعار",
    "ابي سعر",
    "أبي سعر",
}


def load_runtime_faq():
    global _FAQ_CACHE
    if _FAQ_CACHE is not None:
        return _FAQ_CACHE
    if path_exists(FAQ_INDEX_PATH):
        with open(FAQ_INDEX_PATH, "r", encoding="utf-8") as f:
            _FAQ_CACHE = json.load(f)
            return _FAQ_CACHE
    _FAQ_CACHE = []
    return _FAQ_CACHE


def load_runtime_prices():
    global _PRICES_CACHE
    if _PRICES_CACHE is not None:
        return _PRICES_CACHE
    if path_exists(TESTS_PRICE_INDEX_PATH):
        with open(TESTS_PRICE_INDEX_PATH, "r", encoding="utf-8") as f:
            _PRICES_CACHE = json.load(f)
            return _PRICES_CACHE
    _PRICES_CACHE = []
    return _PRICES_CACHE


def normalize_text_ar(s: str) -> str:
    value = str(s or "").strip().lower()
    if not value:
        return ""
    value = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", value)
    value = (
        value.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ة", "ه")
    )
    value = re.sub(r"[^\w\s\u0600-\u06FF]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def contains_match(query_norm: str, candidate_norm: str) -> bool:
    q = (query_norm or "").strip()
    c = (candidate_norm or "").strip()
    if len(q) < 2 or len(c) < 2:
        return False
    return c in q or q in c


def _runtime_faq_lookup(query: str) -> dict | None:
    query_norm = normalize_text_ar(query)
    if not query_norm:
        return None
    faq_items = load_runtime_faq()
    if not isinstance(faq_items, list):
        return None

    exact_match = None
    contains_matches: list[dict] = []
    for item in faq_items:
        if not isinstance(item, dict):
            continue
        candidate_norm = normalize_text_ar(item.get("q_norm") or item.get("q") or "")
        if not candidate_norm:
            continue
        if candidate_norm == query_norm:
            exact_match = item
            break
        if contains_match(query_norm, candidate_norm):
            contains_matches.append(item)

    if exact_match:
        return exact_match
    if not contains_matches:
        return None
    contains_matches.sort(
        key=lambda it: len(normalize_text_ar(it.get("q_norm") or it.get("q") or "")),
        reverse=True,
    )
    return contains_matches[0]


def _runtime_price_lookup_reply(query: str) -> str | None:
    query_norm = normalize_text_ar(query)
    if not query_norm:
        return None

    if not any(k in query_norm for k in ("سعر", "بكم", "كم سعر", "تكلفه", "تكلفة", "السعر")):
        return None

    prices_data = load_runtime_prices()
    if isinstance(prices_data, dict):
        price_items = prices_data.get("records") or []
    elif isinstance(prices_data, list):
        price_items = prices_data
    else:
        price_items = []

    candidates: list[dict] = []
    for item in price_items:
        if not isinstance(item, dict):
            continue
        name_ar = item.get("name_ar") or ""
        name_en = item.get("canonical_en") or item.get("name_en") or ""
        ar_norm = normalize_text_ar(name_ar)
        en_norm = normalize_text_ar(name_en)
        if contains_match(query_norm, ar_norm) or contains_match(query_norm, en_norm):
            candidates.append(item)
            continue
        for key in (item.get("keys") or []):
            if contains_match(query_norm, normalize_text_ar(key)):
                candidates.append(item)
                break

    if len(candidates) != 1:
        return None

    matched = candidates[0]
    price_value = matched.get("price")
    name_ar = (matched.get("name_ar") or matched.get("name_en") or "التحليل").strip()
    matched_ref = matched.get("id") or matched.get("name_ar") or matched.get("name_en")
    print("PATH=runtime_lookup price", matched_ref)
    return f"سعر {name_ar}: {price_value if price_value is not None else 'غير متوفر'}"


def _normalize_light(text: str) -> str:
    value = normalize_text(text)
    if not value:
        return ""
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
    if _contains_any(
        merged,
        {
            "اقرب فرع",
            "أقرب فرع",
            "وين الفرع",
            "مكان الفرع",
            "موقع الفرع",
            "branch",
            "location",
            "وين اقرب",
            "وين اقرب فرع",
            "مكانكم",
            "وين مكان",
            "موقعكم",
            "عنوانكم",
            "وين موقع",
            "لوكيشن",
            "الموقع",
            "مكانك",
        },
    ):
        return "branch_location", meta
    if _contains_any(merged, {"كم سعر", "السعر", "اسعار", "أسعار", "تكلفة", "تكلفه", "price", "cost"}):
        return "pricing", meta
    if _contains_any(merged, {"استلام النتيجه", "استلام النتيجة", "كيف استلم", "كيف توصل النتيجه", "واتساب", "ايميل", "email", "تطبيق", "delivery"}):
        return "result_delivery", meta
    if _contains_any(merged, {"شكوى", "شكوي", "مشكلة", "مشكله", "غير راضي", "مو راضي", "سيئة", "سيئه", "complaint"}):
        return "complaint", meta
    return "other", meta


def _is_working_hours_query(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False

    # Avoid clashing with results/turnaround timing questions.
    result_time_markers = {
        "نتيجه",
        "نتيجة",
        "نتايج",
        "متى تطلع",
        "مدة النتيجة",
        "مده النتيجه",
        "وقت النتيجة",
        "وقت النتيجه",
    }
    if any(m in n for m in result_time_markers):
        return False

    return any(t in n for t in _WORKING_HOURS_TRIGGERS)


def _working_hours_deterministic_reply() -> str:
    return "ساعات الدوام: 24 ساعة يومياً.\nومتوفر أيضاً السحب المنزلي للحجز: 920003694"


def _is_general_price_query(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    return any(t in n for t in {_normalize_light(x) for x in _GENERAL_PRICE_TRIGGERS})


def _is_symptoms_query(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    hits = 0
    seen = set()
    for token in _SYMPTOM_QUERY_TOKENS:
        t = _normalize_light(token)
        if t and t not in seen and t in n:
            seen.add(t)
            hits += 1
    return hits >= 2


def _extract_tests_list_from_rag_test(test: dict) -> str:
    for key in ("complementary_tests", "related_tests", "alternative_tests"):
        value = (test.get(key) or "").strip()
        if value:
            return value
    return "المعلومة غير موجودة بشكل واضح في قاعدة المعرفة لهذه الأعراض."


def _format_symptoms_rag_reply(results: list[dict]) -> str:
    lines = ["هذه أقرب 3 خيارات حسب الأعراض المذكورة:"]
    for i, row in enumerate((results or [])[:3], 1):
        test = row.get("test") or {}
        title = (test.get("analysis_name_ar") or test.get("analysis_name_en") or "خيار غير محدد").strip()
        tests_list = _extract_tests_list_from_rag_test(test)
        lines.append(f"{i}) {title} — {tests_list}")
    lines.append("تنبيه: هذا محتوى تثقيفي من قاعدة المعرفة، وللتشخيص النهائي راجع الطبيب.")
    return "\n".join(lines)


def _symptoms_rag_bypass_reply(question: str) -> str | None:
    if not _is_symptoms_query(question):
        return None
    if not is_rag_ready():
        return None
    try:
        threshold = getattr(settings, "RAG_SIMILARITY_THRESHOLD", 0.58)
        rag_results, _has_hit = retrieve(question, max_results=3, similarity_threshold=threshold)
    except Exception as exc:
        logger.warning("symptoms rag bypass failed: %s", exc)
        return None
    if not rag_results:
        return None
    return _format_symptoms_rag_reply(rag_results[:3])


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
            f"وللدعم المباشر تقدر تتواصل على {WAREED_CUSTOMER_SERVICE_PHONE}."
        )
    return (
        "عشان نحدد أقرب فرع لك بدقة، اكتب المدينة أو الحي. "
        f"وللدعم المباشر تقدر تتواصل على {WAREED_CUSTOMER_SERVICE_PHONE}."
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
            f"أو تواصل مع خدمة العملاء على {WAREED_CUSTOMER_SERVICE_PHONE}."
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


def _package_state_key(conversation_id: UUID) -> str:
    return f"package_selection:{conversation_id}"


def _empty_package_state() -> dict:
    return {
        "active_flow": None,
        "step": None,
        "last_query": "",
        "options": [],
        "updated_at": None,
        "expires_at": None,
    }


def _set_package_state(conversation_id: UUID, payload: dict) -> dict:
    out = _empty_package_state()
    out.update(payload or {})
    now = _utc_now()
    out["updated_at"] = now.isoformat()
    out["expires_at"] = (now + timedelta(minutes=15)).isoformat()
    get_context_cache().set(_package_state_key(conversation_id), json.dumps(out, ensure_ascii=False))
    return out


def _get_package_state(conversation_id: UUID) -> dict:
    raw = get_context_cache().get(_package_state_key(conversation_id))
    if not raw:
        return _empty_package_state()
    try:
        state = json.loads(raw)
    except Exception:
        return _empty_package_state()
    if not isinstance(state, dict):
        return _empty_package_state()
    merged = _empty_package_state()
    merged.update(state)
    if _is_state_expired(merged):
        _reset_package_state(conversation_id)
        return _empty_package_state()
    return merged


def _reset_package_state(conversation_id: UUID) -> None:
    _set_package_state(conversation_id, _empty_package_state())


def _is_package_number_selection(text: str, options_len: int) -> int | None:
    return _is_number_selection(text, options_len)


_PACKAGE_QUERY_KEYWORDS = {
    "باقة",
    "باقه",
    "تحاليل",
    "تحالیل",
    "تحليل",
    "فحص",
    "بكم",
    "سعر",
}


def _is_package_query_candidate(query: str) -> bool:
    n = _normalize_light(query)
    if not n:
        return False
    return any(k in n for k in _PACKAGE_QUERY_KEYWORDS)


def _dedupe_package_records_for_options(records: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for rec in records or []:
        key = _normalize_light(rec.get("name_norm") or rec.get("name_raw") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(rec)
    return deduped


def _compact_package_options(records: list[dict]) -> list[dict]:
    return [
        {
            "id": rec.get("id"),
            "name_raw": rec.get("name_raw"),
            "row": rec.get("row"),
            "section": rec.get("section"),
        }
        for rec in records
    ]


def _format_package_list_strict(records: list[dict]) -> str:
    # Keep contract strict and names-only; packages_service already formats this correctly.
    return format_package_list(records)


def _extract_short_description_bullets(record: dict, min_items: int = 3, max_items: int = 5) -> list[str]:
    desc = str(record.get("description_raw") or "")
    turn = str(record.get("turnaround_text") or "").strip()
    sample = str(record.get("sample_type_text") or "").strip()

    banned = ("فرع", "خدمة العملاء", "maps", "رابط الموقع", "customer service")
    preferred = ("تشمل", "يُستخدم", "يستخدم", "يساعد", "يفيد", "مناسب", "مدة النتائج", "نوع العينة")

    lines: list[str] = []
    for ln in desc.splitlines():
        clean = re.sub(r"\s+", " ", ln).strip(" -\t•")
        if clean:
            lines.append(clean)

    bullets: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        value = re.sub(r"\s+", " ", (text or "")).strip()
        if not value:
            return
        low = value.lower()
        if any(b in low for b in banned):
            return
        norm = _normalize_light(value)
        if not norm or norm in seen:
            return
        seen.add(norm)
        bullets.append(value)

    # Priority fields first.
    if turn:
        add(turn)
    if sample:
        add(sample)

    for ln in lines:
        if len(bullets) >= max_items:
            break
        if any(k in ln for k in preferred):
            add(ln)

    # Fallback to first short lines/sentences.
    if len(bullets) < min_items:
        chunks = []
        for ln in lines:
            chunks.extend(re.split(r"[.!؟]+", ln))
        for ch in chunks:
            if len(bullets) >= min_items:
                break
            add(ch)

    return bullets[:max_items]


def _format_package_details_strict(record: dict) -> str:
    # Build details-only contract deterministically and avoid branch/escalation mentions.
    name = (record.get("name_raw") or "").strip()
    price_raw = (record.get("price_raw") or "").strip()

    lines = [name]
    if price_raw:
        lines.append(f"السعر: {price_raw}")
    else:
        lines.append("السعر: غير متوفر حالياً")

    # Prefer service formatter output structure, but enforce 3-5 bullets strictly.
    _ = format_package_details(record)
    bullets = _extract_short_description_bullets(record, min_items=3, max_items=5)
    for b in bullets:
        lines.append(f"- {b}")

    return "\n".join(lines)


def _find_package_record_by_id(record_id: str) -> dict | None:
    if not record_id:
        return None
    for rec in load_packages_index():
        if rec.get("id") == record_id:
            return rec
    return None


def _resolve_package_option_record(option: dict) -> dict | None:
    rec = _find_package_record_by_id(option.get("id"))
    if rec:
        return rec
    name = (option.get("name_raw") or "").strip()
    row = option.get("row")
    for item in load_packages_index():
        if (item.get("name_raw") or "").strip() == name and item.get("row") == row:
            return item
    if name:
        fallback = search_packages(name, top_k=1)
        if fallback:
            return fallback[0]
    return None


def _save_package_selection_state(conversation_id: UUID, query: str, records: list[dict]) -> None:
    records = _dedupe_package_records_for_options(records)
    options = _compact_package_options(records)
    _set_package_state(
        conversation_id,
        {
            "active_flow": "package_flow",
            "step": "awaiting_choice",
            "last_query": query,
            "options": options,
        },
    )
    _save_state(
        conversation_id,
        {
            "active_flow": "package_flow",
            "step": "awaiting_choice",
            "slots": {"last_query": query},
            "last_options": options,
            "last_prompt": "اختر رقم الخيار المناسب لأرسل لك التفاصيل والسعر.",
        },
    )


def _format_package_options_from_state(options: list[dict]) -> str:
    lines = ["هذه الخيارات المتاحة:"]
    for i, option in enumerate(options or [], 1):
        lines.append(f"{i}) {(option.get('name_raw') or '').strip()}")
    lines.append("اختر رقم الخيار المناسب لأرسل لك التفاصيل والسعر.")
    return "\n".join(lines)


def _handle_package_flow_active(conversation_id: UUID, message: str) -> str | None:
    p_state = _get_package_state(conversation_id)
    options = p_state.get("options") or []
    if not options:
        _reset_package_state(conversation_id)
        _save_state(conversation_id, _complete_flow(_default_flow_state()))
        return None

    selected = _is_package_number_selection(message, len(options))
    if selected is not None:
        rec = _resolve_package_option_record(options[selected - 1])
        _reset_package_state(conversation_id)
        _save_state(conversation_id, _complete_flow(_default_flow_state()))
        if rec:
            return _format_package_details_strict(rec)
        return "ما قدرت أحدد الباقة/التحليل من القائمة الحالية. اكتب الاسم بشكل أقرب أو اذكر الهدف (مثال: فيتامين د / حساسية / هرمونات)."

    numeric = _extract_number_choice(message)
    if numeric is not None:
        return "اختار رقم صحيح من القائمة:\n" + _format_package_options_from_state(options)

    # In active package flow, allow refining with a new package/test query.
    if _is_package_query_candidate(message):
        single = match_single_package(message)
        if single:
            _reset_package_state(conversation_id)
            _save_state(conversation_id, _complete_flow(_default_flow_state()))
            return _format_package_details_strict(single)

        new_options = _dedupe_package_records_for_options(search_packages(message, top_k=6))
        if new_options:
            _save_package_selection_state(conversation_id, message, new_options)
            return _format_package_list_strict(new_options)

        return "ما قدرت أحدد الباقة/التحليل من القائمة الحالية. اكتب الاسم بشكل أقرب أو اذكر الهدف (مثال: فيتامين د / حساسية / هرمونات)."

    return "اختار رقم صحيح من القائمة:\n" + _format_package_options_from_state(options)


def _package_lookup_bypass_reply(question: str, conversation_id: UUID) -> str | None:
    query = (question or "").strip()
    if not query:
        return None

    # Direct deterministic hit first.
    single = match_single_package(query)
    if single:
        _reset_package_state(conversation_id)
        _save_state(conversation_id, _complete_flow(_default_flow_state()))
        return _format_package_details_strict(single)

    candidates = _dedupe_package_records_for_options(search_packages(query, top_k=6))
    trigger = _is_package_query_candidate(query) or bool(candidates)
    if candidates:
        _save_package_selection_state(conversation_id, query, candidates)
        return _format_package_list_strict(candidates)

    # Semantic fallback over packages_kb.json only (after deterministic path fails).
    rag_threshold = 0.75
    trigger = _is_package_query_candidate(query)
    if trigger:
        rag_hits = semantic_search_packages(query, top_k=3)
        if rag_hits:
            top = rag_hits[0]
            if float(top.get("score") or 0.0) >= rag_threshold:
                rec = _find_package_record_by_id(str(top.get("id") or ""))
                if not rec:
                    rec = {
                        "name_raw": (top.get("name") or "").strip(),
                        "price_raw": None,
                        "description_raw": (top.get("content") or "").strip(),
                        "turnaround_text": None,
                        "sample_type_text": None,
                    }
                details = _format_package_details_strict(rec)
                return "حسب الوصف الأقرب في النظام:\n" + details

    if trigger:
        return "ما قدرت أحدد الباقة/التحليل من القائمة الحالية. اكتب الاسم بشكل أقرب أو اذكر الهدف (مثال: فيتامين د / حساسية / هرمونات)."
    return None


# Manual test plan (Phase 5):
# 1) "Well DNA Silver" -> details (no branch mention)
# 2) "باقات الحساسية" -> names-only list -> choose 1 -> details -> state cleared
# 3) "كم سعر تحاليل الكبد؟" -> list or details deterministically
# 4) Send "99" after list -> invalid -> correction + same list
# 5) While package_flow active: user says "وين اقرب فرع" -> package reset -> branch logic handles
# 6) User sends "2" without any list active -> should NOT select package


def _branch_phone() -> str:
    return WAREED_CUSTOMER_SERVICE_PHONE


def _last_assistant_message_within(
    db: Session,
    conversation_id: UUID,
    minutes: int = 15,
) -> str:
    cutoff = _utc_now() - timedelta(minutes=minutes)
    stmt = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.role == MessageRole.ASSISTANT,
            Message.deleted_at.is_(None),
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    msg = db.execute(stmt).scalars().first()
    if not msg:
        return ""
    created_at = msg.created_at
    if created_at is None:
        return ""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if created_at < cutoff:
        return ""
    return (msg.content or "").strip()


def _is_phone_followup_query(text: str, previous_assistant_text: str = "") -> bool:
    n = _normalize_light(text)
    if not n:
        return False

    explicit = {
        "كم رقم الهاتف",
        "رقم الهاتف",
        "رقمكم",
        "ابي الرقم",
        "أبي الرقم",
    }
    if any(k in n for k in explicit):
        return True

    if n in {"الرقم", "رقم"}:
        return True

    # Ambiguous "الرقم" should be treated as a follow-up only if prior assistant context supports it.
    if "الرقم" in n or n == "رقم":
        pn = _normalize_light(previous_assistant_text)
        context_keywords = {
            "حجز",
            "موعد",
            "زياره منزليه",
            "زيارة منزلية",
            "سحب منزلي",
            "خدمات",
            "سعر",
            "اسعار",
            "تكلفه",
            "تكلفة",
            "فرع",
            "فروع",
            "موقع",
            "لوكيشن",
            "خدمة العملاء",
        }
        return bool(pn and any(k in pn for k in context_keywords))

    return False


def _resolve_customer_phone_followup(
    db: Session,
    conversation_id: UUID,
    user_message: str,
) -> str | None:
    previous_assistant_text = _last_assistant_message_within(db, conversation_id, minutes=15)
    if _is_phone_followup_query(user_message, previous_assistant_text):
        return f"رقم خدمة العملاء: {WAREED_CUSTOMER_SERVICE_PHONE}"
    return None


def _is_home_visit_button_request(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    if "وريد كير" in n and "سحب منزلي" in n:
        return True
    if "ابغى خدمة سحب منزلي" in n or "أبغى خدمة سحب منزلي" in n:
        return True
    return False


def _is_booking_howto_query(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    return any(
        k in n
        for k in {
            "كيف احجز موعد",
            "كيف أحجز موعد",
            "كيف احجز",
            "كيف أحجز",
            "حجز موعد",
        }
    )


def _resolve_home_visit_booking_reply(
    db: Session,
    conversation_id: UUID,
    user_message: str,
) -> str | None:
    # Deterministic button/intent response.
    if _is_home_visit_button_request(user_message):
        return (
            "متوفر لدينا خدمة سحب العينات من المنزل أو مقر العمل مع الالتزام بمعايير التعقيم، "
            f"وضمان سرعة ظهور النتائج. للحجز: {WAREED_CUSTOMER_SERVICE_PHONE}"
        )

    # Deterministic short follow-up after the dedicated home-visit reply.
    if _is_booking_howto_query(user_message):
        previous_assistant_text = _last_assistant_message_within(db, conversation_id, minutes=15)
        if previous_assistant_text.startswith("متوفر لدينا خدمة سحب العينات من المنزل أو مقر العمل"):
            return f"للحجز: {WAREED_CUSTOMER_SERVICE_PHONE}"
    return None


def _is_preparation_button_trigger(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    return n == _normalize_light("التحضير قبل التحليل")


def _resolve_preparation_button_reply(user_message: str) -> str | None:
    if _is_preparation_button_trigger(user_message):
        return "أكيد. اكتب اسم التحليل اللي تبي تعرف التحضير له (مثال: فيتامين د / CBC / ألدوستيرون)."
    return None


def _is_services_branches_home_visit_start_trigger(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    triggers = {
        "الخدمات والفروع والسحب المنزلي",
        "ابدأ الطلب",
        "ابدا الطلب",
    }
    return n in {_normalize_light(t) for t in triggers}


def _resolve_services_branches_home_visit_start_reply(
    conversation_id: UUID,
    user_message: str,
) -> str | None:
    if not _is_services_branches_home_visit_start_trigger(user_message):
        return None
    # Prime existing branch flow so the next city message is handled by current branch matcher.
    _save_state(conversation_id, _start_flow("branch_flow"))
    return (
        "يقدم مختبر وريد خدمات التحاليل المخبرية، وباقات الفحوصات، وخدمة السحب المنزلي.\n"
        "للاستفسار أو الحجز: 920003694\n"
        "وإذا حاب تعرف الفرع الأقرب لك، اكتب اسم المدينة (مثال: الرياض / جدة) أو المدينة + الحي."
    )


def _flow_state_key(conversation_id: UUID) -> str:
    return f"flow_state:{conversation_id}"


def _default_flow_state() -> dict:
    return {
        "active_flow": None,
        "step": None,
        "slots": {},
        "last_options": None,
        "last_city": None,
        "last_prompt": None,
        "updated_at": None,
        "expires_at": None,
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_state_expired(state: dict) -> bool:
    expiry = (state or {}).get("expires_at")
    if not expiry:
        return True
    try:
        dt = datetime.fromisoformat(str(expiry))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt <= _utc_now()
    except Exception:
        return True


def _get_state(conversation_id: UUID) -> dict:
    raw = get_context_cache().get(_flow_state_key(conversation_id))
    if not raw:
        return _default_flow_state()
    try:
        state = json.loads(raw)
    except Exception:
        return _default_flow_state()
    if not isinstance(state, dict):
        return _default_flow_state()
    merged = _default_flow_state()
    merged.update(state)
    if _is_state_expired(merged):
        _reset_state(conversation_id)
        return _default_flow_state()
    return merged


def _save_state(conversation_id: UUID, state: dict) -> dict:
    out = _default_flow_state()
    out.update(state or {})
    now = _utc_now()
    out["updated_at"] = now.isoformat()
    out["expires_at"] = (now + timedelta(minutes=15)).isoformat()
    get_context_cache().set(_flow_state_key(conversation_id), json.dumps(out, ensure_ascii=False))
    return out


def _reset_state(conversation_id: UUID) -> None:
    _save_state(conversation_id, _default_flow_state())


def _is_cancel_message(text: str) -> bool:
    n = _normalize_light(text)
    return any(
        token in n
        for token in {
            "إلغاء",
            "الغاء",
            "cancel",
            "restart",
            "ابدا من جديد",
            "ابدأ من جديد",
        }
    )


def _is_number_selection(text: str, n: int) -> int | None:
    if n <= 0:
        return None
    choice = _extract_number_choice(text)
    if choice is None:
        return None
    return choice if 1 <= choice <= n else None


_FLOW_KEYWORDS_ORDER: list[tuple[str, set[str]]] = [
    (
        "branch_flow",
        {
            "اقرب فرع",
            "وين الفرع",
            "موقع الفرع",
            "الفرع القريب",
            "فروع",
            "branch",
            "location",
            "مكان الفرع",
            "مكانكم",
            "وين مكان",
            "موقعكم",
            "عنوانكم",
            "وين موقع",
            "لوكيشن",
            "الموقع",
            "مكانك",
        },
    ),
    (
        "package_flow",
        {
            "باقة",
            "باقه",
            "تحاليل",
            "تحالیل",
            "تحليل",
            "فحص",
        },
    ),
    (
        "pricing_flow",
        {"كم سعر", "سعر", "اسعار", "تكلفه", "تكلفة", "price", "pricing", "cost"},
    ),
    (
        "result_flow",
        {"نتيجه", "نتيجة", "نتايج", "متى تطلع", "رقم الطلب", "order", "result"},
    ),
    (
        "complaint_flow",
        {"شكوى", "شكوي", "مشكلة", "مشكله", "complaint", "اعتراض"},
    ),
]

_RESULT_FLOW_PROMPT = "زوّدني برقم الطلب أو رقم الجوال و تاريخ الزيارة، أو ارفق صورة/ملف للنتائج عشان أشرحها لك."


def _detect_bypass_flow(text: str) -> str | None:
    n = _normalize_light(text)
    if not n:
        return None
    for flow_name, keywords in _FLOW_KEYWORDS_ORDER:
        if any(k in n for k in keywords):
            return flow_name
    return None


def _detect_topic_switch(text: str) -> str | None:
    return _detect_bypass_flow(text)


def _is_result_flow_related_message(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    if _extract_identifier(text):
        return True
    result_markers = {
        "نتيجة",
        "نتيجه",
        "نتايج",
        "شرح النتائج",
        "شرح نتايج",
        "تفسير النتائج",
        "نتائج التحليل",
        "رقم الطلب",
        "تاريخ الزيارة",
        "ارفق",
        "أرفق",
        "صورة",
        "ملف",
        "report",
    }
    return any(m in n for m in result_markers)


def _extract_test_name_for_pricing(text: str) -> str:
    n = _normalize_light(text)
    if not n:
        return ""
    cleaned = re.sub(r"[؟?]", " ", n)
    cleaned = re.sub(r"\b(كم|سعر|تكلفه|في|الرياض|جده|price|pricing)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _extract_identifier(text: str) -> str:
    raw = _to_western_digits(text or "")
    m = re.search(r"\b\d{4,}\b", raw)
    if m:
        return m.group(0)
    m = re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", raw)
    if m:
        return m.group(0)
    return ""


def _format_branch_item(idx: int, branch: dict) -> str:
    return f"{idx}) {branch.get('branch_name', '').strip()}"


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


_BRANCH_LIKE_KEYWORDS = {
    "فرع",
    "الفرع",
    "فروع",
    "موقع",
    "الموقع",
    "عنوان",
    "لوكيشن",
    "مكان",
    "مكانكم",
    "مكانك",
    "موقعكم",
    "عنوانكم",
    "branch",
    "location",
}


def _has_branch_like_word(query: str) -> bool:
    n = _normalize_light(query)
    if not n:
        return False
    return any(k in n for k in _BRANCH_LIKE_KEYWORDS)


def _match_branch_by_name_in_query(query: str) -> dict | None:
    normalized_query = _normalize_light(query)
    if not normalized_query:
        return None

    best_match = None
    best_score = -1
    for row in load_branches_index():
        branch_name = (row.get("branch_name") or "").strip()
        if not branch_name:
            continue
        branch_name_n = _normalize_light(branch_name)
        if not branch_name_n:
            continue

        variants = {branch_name_n}
        if branch_name_n.startswith("فرع "):
            short_name = branch_name_n[4:].strip()
            if short_name:
                variants.add(short_name)
        if branch_name_n.startswith("الفرع "):
            short_name = branch_name_n[6:].strip()
            if short_name:
                variants.add(short_name)

        for variant in variants:
            if variant and variant in normalized_query:
                score = len(variant)
                if score > best_score:
                    best_match = row
                    best_score = score
                break
    return best_match


_BRANCH_FILLER_WORDS = {
    "فروعكم",
    "الفروع",
    "فروع",
    "المتوفره",
    "المتوفرة",
    "عندكم",
    "معاكم",
    "في",
    "وين",
    "اقرب",
    "فرع",
    "الفرع",
    "موجوده",
    "موجودة",
    "ماهي",
    "ما",
    "هي",
    "وش",
    "ايش",
    "ابي",
    "ابغى",
    "لو",
    "سمحت",
    "لوسمحت",
    "حدد",
    "لي",
    "مدينه",
    "مدينة",
}

_BRANCH_DISTRICT_IGNORE_TOKENS = {
    "فروعكم",
    "الفروع",
    "المتوفره",
    "المتوفرة",
    "عندكم",
    "معاكم",
    "في",
    "وين",
    "اقرب",
    "فرع",
    "الفرع",
    "موجوده",
    "موجودة",
}


def _extract_branch_district_from_query(query: str, city: str) -> str:
    normalized = _normalize_light(query)
    if not normalized:
        return ""

    city_n = _normalize_light(city)
    if city_n:
        normalized = normalized.replace(city_n, " ")

    normalized = re.sub(r"[^\w\s\u0600-\u06FF]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return ""

    tokens = normalized.split()
    cleaned_tokens = []
    for token in tokens:
        if token in _BRANCH_FILLER_WORDS:
            continue
        if len(token) < 3:
            continue
        if token in _BRANCH_DISTRICT_IGNORE_TOKENS:
            continue
        if token.isdigit():
            continue
        cleaned_tokens.append(token)

    if not cleaned_tokens:
        return ""
    return " ".join(cleaned_tokens)


def _extract_city_and_district(query: str) -> tuple[str, str]:
    city = _extract_city_from_query(query)
    if not city:
        return "", ""
    district = _extract_branch_district_from_query(query, city)
    return city, district


def _is_real_phone_number(value: str) -> bool:
    raw = (value or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    if "xxxx" in lowered or "xxx" in lowered:
        return False
    digits = re.sub(r"\D", "", _to_western_digits(raw))
    return 8 <= len(digits) <= 12


def _format_branch_names_only(city: str, branches: list[dict]) -> str:
    lines = [f"هذه الفروع المتوفرة في {city}:"]
    for i, b in enumerate(branches, 1):
        lines.append(f"{i}) {b.get('branch_name', '').strip()}")
    lines.append("حددي رقم الفرع الأقرب لك لأزوّدك برابط الموقع.")
    return "\n".join(lines)


def _format_selected_branch(choice: int, branch: dict) -> str:
    branch_name = (branch.get("branch_name") or "").strip()
    maps_url = (branch.get("maps_url") or "").strip()
    hours = (branch.get("hours") or "").strip()
    phone = (branch.get("phone") or "").strip()
    lines = [f"الفرع رقم {choice}: {branch_name}", ""]
    if maps_url:
        lines.append("رابط الموقع:")
        lines.append(maps_url)
    if _is_real_phone_number(phone):
        lines.append("")
        lines.append(f"هاتف الفرع: {phone}")
    if hours:
        if not _is_real_phone_number(phone):
            lines.append("")
        lines.append(f"ساعات العمل: {hours}")
    return "\n".join(lines)


def _format_city_not_found_reply(city: str) -> str:
    cities = get_available_cities()
    cities_text = "، ".join(cities) if cities else "-"
    return (
        f"حالياً لا يوجد لدينا فروع في {city}.\n"
        f"المدن المتوفرة لدينا حالياً في: {cities_text}\n"
        f"ولأي مساعدة إضافية: {_branch_phone()}"
    )


def _save_branch_selection_state(conversation_id: UUID, city: str, branches: list[dict]) -> None:
    _save_state(
        conversation_id,
        {
            "active_flow": "branch_flow",
            "step": "awaiting_branch_number",
            "slots": {"city": city},
            "last_city": city,
            "last_options": branches,
            "last_prompt": "حددي رقم الفرع الأقرب لك لأزوّدك برابط الموقع.",
        },
    )


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
    state = _get_state(conversation_id)
    if state.get("active_flow") in {"branch_flow", "branch_location"} and state.get("step") == "awaiting_branch_number":
        options = state.get("last_options") or []
        selected = _is_number_selection(question, len(options))
        if selected is not None:
            _save_state(conversation_id, _complete_flow(state))
            return _format_selected_branch(selected, options[selected - 1])

    # Backward-compatible numeric selection cache.
    choice = _extract_number_choice(question)
    if choice is not None:
        cached = _load_branch_selection(conversation_id)
        if cached and isinstance(cached.get("branches"), list):
            branches = cached["branches"]
            if 1 <= choice <= len(branches):
                return _format_selected_branch(choice, branches[choice - 1])

    if light_intent != "branch_location":
        return None

    direct_branch_match = _match_branch_by_name_in_query(question)
    if direct_branch_match:
        return _format_selected_branch(1, direct_branch_match)

    if _has_branch_like_word(question):
        city_probe, _ = _extract_city_and_district(question)
        if not city_probe:
            return "عشان أتحقق لك من الموقع بالضبط، خبرني عن المدينة اللي أنت فيها وبعرض لك الفروع المتوفرة وتختار الأقرب لك."

    # Case A: no city
    city_raw, district = _extract_city_and_district(question)
    if not city_raw:
        return "عشان أحدد أقرب فرع، اكتب اسم المدينة (مثال: الرياض / جدة) أو المدينة + الحي."

    city = _match_city_in_catalog(city_raw)
    if not city:
        return _format_city_not_found_reply(city_raw)

    city_branches = find_branches_by_city(city)
    if not city_branches:
        return _format_city_not_found_reply(city)

    # Case C: city + district
    if district:
        district_hits = []
        qn = _normalize_light(district)
        for b in city_branches:
            if qn and (qn in _normalize_light(b.get("branch_name", "")) or qn in _normalize_light(b.get("group", ""))):
                district_hits.append(b)
        if district_hits:
            _save_branch_selection_state(conversation_id, city, district_hits)
            return _format_branch_names_only(city, district_hits)
        _save_branch_selection_state(conversation_id, city, city_branches)
        return (
            f"ما لقينا الحي المذكور بالاسم داخل قائمتنا، لكن هذه فروع {city} المتوفرة:\n"
            + "\n"
            + _format_branch_names_only(city, city_branches)
        )

    # Case B: city only
    _save_branch_selection_state(conversation_id, city, city_branches)
    return _format_branch_names_only(city, city_branches)


def _start_flow(flow_name: str) -> dict:
    state = _default_flow_state()
    state["active_flow"] = flow_name
    state["slots"] = {}
    if flow_name in {"branch_flow", "branch_location"}:
        state["active_flow"] = "branch_flow"
        state["step"] = "awaiting_city"
        state["last_prompt"] = "عشان أحدد أقرب فرع، اكتب اسم المدينة (مثال: الرياض / جدة) أو المدينة + الحي."
    elif flow_name == "pricing_flow":
        state["step"] = "awaiting_test_name"
        state["last_prompt"] = "وش اسم التحليل اللي تبغى سعره؟"
    elif flow_name == "package_flow":
        state["step"] = "awaiting_choice"
        state["last_prompt"] = "اكتب اسم الباقة/التحليل أو اختر رقم من الخيارات إذا ظهرت لك قائمة."
    elif flow_name == "result_flow":
        state["step"] = "awaiting_identifier"
        state["last_prompt"] = _RESULT_FLOW_PROMPT
    elif flow_name == "complaint_flow":
        state["step"] = "awaiting_identifier"
        state["last_prompt"] = "لفتح شكوى بشكل صحيح، زوّدني برقم الطلب أو تاريخ الزيارة."
    else:
        state["step"] = None
        state["last_prompt"] = None
    return state


def _complete_flow(state: dict) -> dict:
    out = _default_flow_state()
    out["active_flow"] = None
    out["step"] = "done"
    out["slots"] = {}
    out["last_options"] = None
    out["last_prompt"] = None
    return out


def _run_branch_flow(message: str, state: dict) -> tuple[str, dict, bool]:
    step = state.get("step") or "awaiting_city"
    slots = state.get("slots") or {}
    options = state.get("last_options") or []

    if step in {"showing_branches", "awaiting_selection", "awaiting_branch_number"} and options:
        selected = _is_number_selection(message, len(options))
        if selected is not None:
            return _format_selected_branch(selected, options[selected - 1]), _complete_flow(state), True

    direct_branch_match = _match_branch_by_name_in_query(message)
    if direct_branch_match:
        return _format_selected_branch(1, direct_branch_match), _complete_flow(state), True

    city_raw, district = _extract_city_and_district(message)
    if not city_raw:
        # allow using already captured city in ongoing branch flow
        city_raw = (slots.get("city") or "").strip()
        district = district or ""

    if not city_raw:
        if _has_branch_like_word(message):
            state["step"] = "awaiting_city"
            state["last_prompt"] = "عشان أتحقق لك من الموقع بالضبط، خبرني عن المدينة اللي أنت فيها وبعرض لك الفروع المتوفرة وتختار الأقرب لك."
            return state["last_prompt"], state, False
        state["step"] = "awaiting_city"
        state["last_prompt"] = "عشان أحدد أقرب فرع، اكتب اسم المدينة (مثال: الرياض / جدة) أو المدينة + الحي."
        return state["last_prompt"], state, False

    city = _match_city_in_catalog(city_raw)
    if not city:
        return _format_city_not_found_reply(city_raw), _complete_flow(state), True

    city_branches = find_branches_by_city(city)
    if not city_branches:
        return _format_city_not_found_reply(city), _complete_flow(state), True

    if district:
        qn = _normalize_light(district)
        district_hits = [
            b
            for b in city_branches
            if qn and (qn in _normalize_light(b.get("branch_name", "")) or qn in _normalize_light(b.get("group", "")))
        ]
        if district_hits:
            state["slots"] = {"city": city, "district": district}
            state["step"] = "awaiting_branch_number"
            state["active_flow"] = "branch_flow"
            state["last_city"] = city
            state["last_options"] = district_hits
            state["last_prompt"] = "حددي رقم الفرع الأقرب لك لأزوّدك برابط الموقع."
            return _format_branch_names_only(city, district_hits), state, False
        state["slots"] = {"city": city, "district": district}
        state["step"] = "awaiting_branch_number"
        state["active_flow"] = "branch_flow"
        state["last_city"] = city
        state["last_options"] = city_branches
        state["last_prompt"] = "حددي رقم الفرع الأقرب لك لأزوّدك برابط الموقع."
        msg = (
            f"ما لقينا الحي المذكور بالاسم داخل قائمتنا، لكن هذه فروع {city} المتوفرة:\n"
            + "\n"
            + _format_branch_names_only(city, city_branches)
        )
        return msg, state, False

    state["slots"] = {"city": city}
    state["step"] = "awaiting_branch_number"
    state["active_flow"] = "branch_flow"
    state["last_city"] = city
    state["last_options"] = city_branches
    state["last_prompt"] = "حددي رقم الفرع الأقرب لك لأزوّدك برابط الموقع."
    return _format_branch_names_only(city, city_branches), state, False


def _run_pricing_flow(message: str, state: dict) -> tuple[str, dict, bool]:
    step = state.get("step") or "awaiting_test_name"
    slots = state.get("slots") or {}

    if step == "awaiting_test_name":
        test_name = _extract_test_name_for_pricing(message)
        if not test_name:
            state["last_prompt"] = "وش اسم التحليل اللي تبغى سعره؟"
            return state["last_prompt"], state, False
        slots["test_name"] = test_name
        state["slots"] = slots
        state["step"] = "awaiting_city"
        state["last_prompt"] = "اكتب المدينة إذا تحب (مثال: الرياض)، أو اكتب: بدون مدينة."
        return state["last_prompt"], state, False

    if step == "awaiting_city":
        city, _district = _extract_city_and_district(message)
        if city and _match_city_in_catalog(city):
            slots["city"] = _match_city_in_catalog(city)
        reply = (
            f"بالنسبة لسعر {slots.get('test_name', 'التحليل المطلوب')}"
            + (f" في {slots['city']}" if slots.get("city") else "")
            + f"، للاستفسار الدقيق تقدر تتواصل مع خدمة العملاء على {_branch_phone()}."
        )
        return reply, _complete_flow(state), True

    state["last_prompt"] = "وش اسم التحليل اللي تبغى سعره؟"
    state["step"] = "awaiting_test_name"
    return state["last_prompt"], state, False


def _run_result_flow(message: str, state: dict) -> tuple[str, dict, bool]:
    ident = _extract_identifier(message)
    if not ident:
        state["step"] = "awaiting_identifier"
        state["last_prompt"] = _RESULT_FLOW_PROMPT
        return state["last_prompt"], state, False
    reply = f"لخدمة النتائج بشكل مباشر، تقدر تتواصل مع خدمة العملاء على {_branch_phone()}."
    return reply, _complete_flow(state), True


def _run_complaint_flow(message: str, state: dict) -> tuple[str, dict, bool]:
    ident = _extract_identifier(message)
    if not ident:
        state["step"] = "awaiting_identifier"
        state["last_prompt"] = "لفتح شكوى بشكل صحيح، زوّدني برقم الطلب أو تاريخ الزيارة."
        return state["last_prompt"], state, False
    reply = f"تم استلام طلبك. لإكمال معالجة الشكوى بسرعة، تواصل مع خدمة العملاء على {_branch_phone()}."
    return reply, _complete_flow(state), True


_FLOW_DEFINITIONS = {
    "branch_flow": {
        "required_slots": ["city"],
        "handler": _run_branch_flow,
    },
    "pricing_flow": {
        "required_slots": ["test_name"],
        "handler": _run_pricing_flow,
    },
    "result_flow": {
        "required_slots": ["order_id_or_phone_or_visit_date"],
        "handler": _run_result_flow,
    },
    "complaint_flow": {
        "required_slots": ["order_id_or_visit_date"],
        "handler": _run_complaint_flow,
    },
    "default_chat_flow": {
        "required_slots": [],
        "handler": None,
    },
}


def _run_flow_by_name(flow_name: str, message: str, state: dict) -> tuple[str, dict, bool] | None:
    definition = _FLOW_DEFINITIONS.get(flow_name)
    if not definition:
        return None
    handler = definition.get("handler")
    if handler is None:
        return None
    return handler(message, state)


def _handle_stateful_conversation(conversation_id: UUID, message: str) -> str | None:
    if _is_cancel_message(message):
        _reset_state(conversation_id)
        _reset_package_state(conversation_id)
        return "تم إلغاء العملية. نقدر نبدأ من جديد، كيف أقدر أخدمك؟"

    state = _get_state(conversation_id)
    active_flow = state.get("active_flow") or None
    topic_switch = _detect_bypass_flow(message)

    if active_flow == "package_flow":
        if topic_switch and topic_switch != "package_flow":
            _reset_package_state(conversation_id)
            state = _start_flow(topic_switch)
            active_flow = topic_switch
        else:
            package_reply = _handle_package_flow_active(conversation_id, message)
            if package_reply:
                return package_reply

    if active_flow and topic_switch and topic_switch != active_flow:
        if active_flow == "package_flow":
            _reset_package_state(conversation_id)
        state = _start_flow(topic_switch)
        active_flow = topic_switch
    elif active_flow:
        # Continue active flow first if no strong topic switch.
        pass
    elif topic_switch:
        state = _start_flow(topic_switch)
        active_flow = topic_switch

    if not active_flow or active_flow == "default_chat_flow":
        return None

    if active_flow == "result_flow" and not _is_result_flow_related_message(message):
        _reset_state(conversation_id)
        return None

    if active_flow == "branch_location":
        # Backward compatibility for older cached states.
        active_flow = "branch_flow"
        state["active_flow"] = "branch_flow"

    if active_flow == "package_flow":
        # Deterministic package flow is handled via dedicated state key.
        package_reply = _handle_package_flow_active(conversation_id, message)
        if package_reply:
            return package_reply
        return None

    result = _run_flow_by_name(active_flow, message, state)
    if result is None:
        return None
    reply, next_state, _done = result

    _save_state(conversation_id, next_state)
    return reply


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

    user_obj = getattr(conv, "user", None)
    display_name = None
    if user_obj is not None:
        display_name = (
            getattr(user_obj, "display_name", None)
            or getattr(user_obj, "username", None)
            or getattr(user_obj, "email", None)
        )
    gender = guess_gender(display_name)

    def tone(text_male: str, text_female: str, text_neutral: str) -> str:
        return apply_gender_variant(text_male, text_female, text_neutral, gender)

    def _apply_gender_addressing(text: str) -> str:
        content = str(text or "")
        if not content:
            return content
        tafaddal = tone("تفضل", "تفضلين", "تفضل")
        tawasal = tone("تواصل", "تواصلي", "تواصل")
        arsil = tone("ارسل", "ارسلي", "ارسل")
        token_map = (
            ("تفضلين", tafaddal),
            ("تفضل", tafaddal),
            ("تواصلي", tawasal),
            ("تواصل", tawasal),
            ("ارسلي", arsil),
            ("ارسل", arsil),
        )
        for src, dst in token_map:
            content = re.sub(rf"(?<![\u0600-\u06FF]){re.escape(src)}(?![\u0600-\u06FF])", dst, content)
        return content

    def _save_assistant_reply(raw_text: str, token_count: int = 0) -> tuple[Message, Message]:
        final_text = sanitize_for_ui(_apply_gender_addressing(raw_text))
        assistant_msg = add_message(
            db,
            conversation_id,
            MessageRole.ASSISTANT,
            final_text,
            token_count=token_count,
        )
        db.commit()
        db.refresh(assistant_msg)
        return user_msg, assistant_msg

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

    services_start_reply = _resolve_services_branches_home_visit_start_reply(conversation_id, question_for_ai)
    if services_start_reply:
        return _save_assistant_reply(services_start_reply)

    prep_button_reply = _resolve_preparation_button_reply(question_for_ai)
    if prep_button_reply:
        return _save_assistant_reply(prep_button_reply)

    home_visit_booking_reply = _resolve_home_visit_booking_reply(db, conversation_id, question_for_ai)
    if home_visit_booking_reply:
        return _save_assistant_reply(home_visit_booking_reply)

    phone_followup_reply = _resolve_customer_phone_followup(db, conversation_id, question_for_ai)
    if phone_followup_reply:
        return _save_assistant_reply(phone_followup_reply)

    if _is_working_hours_query(question_for_ai):
        return _save_assistant_reply(_working_hours_deterministic_reply())

    runtime_price_reply = _runtime_price_lookup_reply(question_for_ai)
    if runtime_price_reply:
        return _save_assistant_reply(runtime_price_reply)

    if _is_general_price_query(question_for_ai):
        specific_pkg = match_single_package(question_for_ai)
        if specific_pkg and (specific_pkg.get("price_raw") is not None):
            return _save_assistant_reply(_format_package_details_strict(specific_pkg))

        return _save_assistant_reply("للاستفسار عن الأسعار: 920003694")

    stateful_reply = _handle_stateful_conversation(conversation_id, question_for_ai)
    if stateful_reply:
        return _save_assistant_reply(stateful_reply)

    runtime_faq_match = _runtime_faq_lookup(question_for_ai)
    if runtime_faq_match and runtime_faq_match.get("a"):
        print("PATH=runtime_lookup faq", runtime_faq_match.get("id"))
        return _save_assistant_reply(str(runtime_faq_match.get("a")).strip())

    user_asked_home_visit = _user_explicitly_asked_home_visit(question_for_ai)

    light_intent, light_intent_meta = _classify_light_intent(question_for_ai)
    logger.info(
        "light intent classification | intent=%s | meta=%s",
        light_intent,
        light_intent_meta,
    )

    branch_bypass_reply = _branch_lookup_bypass_reply(question_for_ai, conversation_id, light_intent)
    if branch_bypass_reply:
        return _save_assistant_reply(branch_bypass_reply)

    symptoms_bypass_reply = _symptoms_rag_bypass_reply(question_for_ai)
    if symptoms_bypass_reply:
        return _save_assistant_reply(symptoms_bypass_reply)

    package_bypass_reply = _package_lookup_bypass_reply(question_for_ai, conversation_id)
    if package_bypass_reply:
        return _save_assistant_reply(package_bypass_reply)

    if light_intent == "branch_location" and not light_intent_meta.get("has_city_or_area"):
        return _save_assistant_reply(_branch_location_prompt())

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
        return _save_assistant_reply(fixed_reply)

    if intent_payload.get("needs_clarification") and intent_payload.get("clarifying_question"):
        clarify_reply = safe_clarify_message(WAREED_CUSTOMER_SERVICE_PHONE, gender)
        return _save_assistant_reply(clarify_reply)

    if light_intent == "branch_location":
        verified_branch_answer = _direct_kb_faq_answer(question_for_ai, "branches_locations")
        if verified_branch_answer and _has_verified_branch_info(verified_branch_answer):
            verified_branch_answer = _sanitize_branch_location_response(
                verified_branch_answer,
                bool(light_intent_meta.get("has_city_or_area")),
                allow_home_visit=user_asked_home_visit,
            )
            return _save_assistant_reply(verified_branch_answer)
        return _save_assistant_reply(_branch_location_prompt(light_intent_meta.get("city_or_area") or ""))

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
                return _save_assistant_reply(_branch_location_prompt(light_intent_meta.get("city_or_area") or ""))
            faq_answer = _sanitize_branch_location_response(
                faq_answer,
                bool(light_intent_meta.get("has_city_or_area")),
                allow_home_visit=user_asked_home_visit,
            )
            return _save_assistant_reply(faq_answer)
        if faq_answer:
            return _save_assistant_reply(faq_answer)

    if intent == "symptom_based_suggestion":
        suggestion = _symptom_guidance(question_for_ai)
        return _save_assistant_reply(suggestion)

    # PDF report summarizer (works even if LLM is unavailable).
    is_pdf_attachment = bool(attachment_content and (attachment_filename or "").lower().endswith(".pdf"))
    wants_report_explain = intent in {"report_explanation", "test_definition"} or is_report_explanation_request(question_for_ai)
    if is_pdf_attachment and wants_report_explain and extracted_context:
        parsed_rows = parse_lab_report_text(extracted_context)
        report_reply = compose_report_summary(parsed_rows)
        return _save_assistant_reply(report_reply)

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

    return _save_assistant_reply(assistant_content, token_count=tokens)
