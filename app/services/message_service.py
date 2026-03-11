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
from difflib import SequenceMatcher
from pathlib import Path
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
    get_grounded_context,
    get_site_fallback_context,
    RAG_KNOWLEDGE_PATH,
    RAG_EMBEDDINGS_PATH,
    expand_test_query as rag_expand_test_query,
    expand_query_with_concepts as rag_expand_query_with_concepts,
    _collect_concept_matches as rag_collect_concept_matches,
    _is_direct_entity_query as rag_is_direct_entity_query,
    _collect_direct_test_matches as rag_collect_direct_test_matches,
)
from app.core.config import settings
from app.core.runtime_paths import FAQ_CLEAN_PATH, TESTS_PRICE_INDEX_PATH, path_exists
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
_SYNONYMS_CACHE = None

SYNONYMS_PATH = Path("app/data/runtime/synonyms/synonyms_ar.json")

_ESCALATION_BLOCKED_PHRASES = (
    "we will contact you",
    "we'll contact you",
    "someone will reach out",
    "we will forward your request",
    "Ø³ÙˆÙ Ù†ØªÙˆØ§ØµÙ„",
    "Ø³Ù†Ù‚ÙˆÙ… Ø¨Ø§Ù„ØªÙˆØ§ØµÙ„",
    "Ø³ÙŠØªÙ… Ø§Ù„ØªÙˆØ§ØµÙ„",
    "Ø±Ø§Ø­ Ù†ØªÙˆØ§ØµÙ„",
    "Ø³Ù†Ø­ÙˆÙ„ Ø·Ù„Ø¨Ùƒ",
    "Ø±Ø§Ø­ Ù†Ø­ÙˆÙ„ Ø·Ù„Ø¨Ùƒ",
)


def _build_direct_support_message() -> str:
    return (
        "Ù„Ù„Ø­ØµÙˆÙ„ Ø¹Ù„Ù‰ Ø¯Ø¹Ù… Ù…Ø¨Ø§Ø´Ø±ØŒ ØªÙ‚Ø¯Ø± ØªØªÙˆØ§ØµÙ„ Ù…Ø¹ Ø®Ø¯Ù…Ø© Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡ Ø¹Ù„Ù‰ Ø§Ù„Ø±Ù‚Ù… Ø§Ù„ØªØ§Ù„ÙŠ: "
        f"{WAREED_CUSTOMER_SERVICE_PHONE}"
    )


def _enforce_escalation_policy(text: str) -> str:
    content = (text or "").strip()
    lowered = content.lower()
    if any(phrase in lowered for phrase in _ESCALATION_BLOCKED_PHRASES):
        return _build_direct_support_message()
    return content


_LIGHT_INTENT_CITIES = {
    "Ø§Ù„Ø±ÙŠØ§Ø¶", "Ø¬Ø¯Ø©", "Ù…ÙƒØ©", "Ø§Ù„Ù…Ø¯ÙŠÙ†Ù‡", "Ø§Ù„Ù…Ø¯ÙŠÙ†Ø©", "Ø§Ù„Ø¯Ù…Ø§Ù…", "Ø§Ù„Ø®Ø¨Ø±", "Ø§Ù„Ù‚ØµÙŠÙ…", "ØªØ¨ÙˆÙƒ", "Ø§Ø¨Ù‡Ø§", "Ø£Ø¨Ù‡Ø§",
    "Ø­Ø§Ø¦Ù„", "Ø¬Ø§Ø²Ø§Ù†", "Ø§Ù„Ø·Ø§ÙŠÙ", "Ø§Ù„Ø·Ø§Ø¦Ù", "Ø§Ù„Ø¬Ø¨ÙŠÙ„", "Ø®Ù…ÙŠØ³ Ù…Ø´ÙŠØ·", "Ù†Ø¬Ø±Ø§Ù†", "Ø§Ù„Ø§Ø­Ø³Ø§Ø¡", "Ø§Ù„Ø£Ø­Ø³Ø§Ø¡",
}

_SYMPTOM_QUERY_TOKENS = {
    "Ø§Ø¹Ø±Ø§Ø¶",
    "Ø£Ø¹Ø±Ø§Ø¶",
    "Ø¹Ù†Ø¯ÙŠ",
    "Ø§Ø­Ø³",
    "Ø£Ø­Ø³",
    "Ø§Ø´Ø¹Ø±",
    "Ø£Ø´Ø¹Ø±",
    "Ø§Ù„Ù…",
    "Ø£Ù„Ù…",
    "Ø¶ÙŠÙ‚",
    "Ø®ÙÙ‚Ø§Ù†",
    "ÙƒØ­Ù‡",
    "ÙƒØ­Ø©",
    "Ø­Ø±Ø§Ø±Ù‡",
    "Ø­Ø±Ø§Ø±Ø©",
    "ØµØ¯Ø§Ø¹",
    "ØºØ«ÙŠØ§Ù†",
    "Ø§Ø³Ù‡Ø§Ù„",
    "Ø¥Ø³Ù‡Ø§Ù„",
    "Ø¯ÙˆØ®Ù‡",
    "Ø¯ÙˆØ®Ø©",
}

_WORKING_HOURS_TRIGGERS = {
    "Ø³Ø§Ø¹Ø§Øª Ø§Ù„Ø¯ÙˆØ§Ù…",
    "Ø¯ÙˆØ§Ù…ÙƒÙ…",
    "Ù…ØªÙ‰ ØªÙØªØ­ÙˆÙ†",
    "Ù…ØªÙ‰ ØªÙ‚ÙÙ„ÙˆÙ†",
    "ÙˆÙ‚Øª Ø§Ù„Ø¯ÙˆØ§Ù…",
    "Ø³Ø§Ø¹Ù‡",
    "Ø³Ø§Ø¹Ø§Øª",
    "ÙˆÙ‚Øª",
}

_GENERAL_PRICE_TRIGGERS = {
    "Ø§Ù„Ø§Ø³Ø¹Ø§Ø±",
    "Ø§Ù„Ø£Ø³Ø¹Ø§Ø±",
    "ÙƒÙ… Ø§Ù„Ø³Ø¹Ø±",
    "Ø¨ÙƒÙ…",
    "Ø³Ø¹Ø± Ø§Ù„ØªØ­Ù„ÙŠÙ„",
    "Ø§Ø³ØªØ¹Ù„Ø§Ù… Ø¹Ù† Ø§Ù„Ø§Ø³Ø¹Ø§Ø±",
    "Ø§Ø³ØªØ¹Ù„Ø§Ù… Ø¹Ù† Ø§Ù„Ø£Ø³Ø¹Ø§Ø±",
    "Ø§Ø¨ÙŠ Ø³Ø¹Ø±",
    "Ø£Ø¨ÙŠ Ø³Ø¹Ø±",
}

_PRICE_QUERY_KEYWORDS = ("Ø³Ø¹Ø±", "Ø¨ÙƒÙ…", "ÙƒÙ… Ø³Ø¹Ø±", "ØªÙƒÙ„ÙÙ‡", "ØªÙƒÙ„ÙØ©", "Ø§Ù„Ø³Ø¹Ø±")


def load_runtime_faq():
    global _FAQ_CACHE
    if _FAQ_CACHE is not None:
        return _FAQ_CACHE
    if not path_exists(FAQ_CLEAN_PATH):
        logger.warning("faq loader missing source | source=%s", FAQ_CLEAN_PATH)
        _FAQ_CACHE = []
        return _FAQ_CACHE

    items: list[dict] = []
    try:
        with open(FAQ_CLEAN_PATH, "r", encoding="utf-8") as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = (raw_line or "").strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception as exc:
                    logger.warning(
                        "faq loader malformed jsonl row | source=%s | line=%s | error=%s",
                        FAQ_CLEAN_PATH,
                        line_no,
                        exc,
                    )
                    continue

                faq_id = str(row.get("id") or "").strip()
                question = str(row.get("question") or "").strip()
                answer = str(row.get("answer") or "").strip()
                q_norm = str(row.get("q_norm") or "").strip()
                if not faq_id or not question or not answer or not q_norm:
                    logger.warning(
                        "faq loader skipped invalid row | source=%s | line=%s | missing_required_fields=id/question/answer/q_norm",
                        FAQ_CLEAN_PATH,
                        line_no,
                    )
                    continue

                items.append(
                    {
                        "id": faq_id,
                        "question": question,
                        "answer": answer,
                        "q_norm": q_norm,
                    }
                )
    except Exception as exc:
        logger.warning("faq loader failed | source=%s | error=%s", FAQ_CLEAN_PATH, exc)
        items = []

    logger.info("faq loader ready | source=%s | records=%s", FAQ_CLEAN_PATH, len(items))
    _FAQ_CACHE = items
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


def load_runtime_synonyms():
    global _SYNONYMS_CACHE
    if _SYNONYMS_CACHE is not None:
        return _SYNONYMS_CACHE
    if path_exists(SYNONYMS_PATH):
        with open(SYNONYMS_PATH, "r", encoding="utf-8") as f:
            _SYNONYMS_CACHE = json.load(f)
            return _SYNONYMS_CACHE
    _SYNONYMS_CACHE = {}
    return _SYNONYMS_CACHE


def normalize_text_ar(s: str) -> str:
    value = str(s or "").strip().lower()
    if not value:
        return ""
    value = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", value)
    value = (
        value.replace("Ø£", "Ø§")
        .replace("Ø¥", "Ø§")
        .replace("Ø¢", "Ø§")
        .replace("Ù‰", "ÙŠ")
        .replace("Ø©", "Ù‡")
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


def _faq_similarity_score(query_norm: str, candidate_norm: str) -> float:
    q = (query_norm or "").strip()
    c = (candidate_norm or "").strip()
    if len(q) < 2 or len(c) < 2:
        return 0.0
    ratio = SequenceMatcher(None, q, c).ratio()
    q_tokens = {t for t in q.split() if t}
    c_tokens = {t for t in c.split() if t}
    if not q_tokens or not c_tokens:
        return ratio
    inter = q_tokens & c_tokens
    if not inter:
        return ratio
    candidate_coverage = len(inter) / len(c_tokens)
    jaccard = len(inter) / len(q_tokens | c_tokens)
    blended = (0.65 * candidate_coverage) + (0.35 * jaccard)
    return max(ratio, blended)


def _expand_faq_query_aliases(query_norm: str) -> list[str]:
    """
    Expand common user FAQ phrasings into canonical dataset-like forms.
    This stays intentionally narrow to avoid broad FAQ hijacking.
    """
    base = normalize_text_ar(query_norm)
    if not base:
        return []

    variants: set[str] = {base}
    alias_pairs = [
        ("هل لديكم خدمة منزلية", "هل يوفر مختبر وريد خدمة الزيارات المنزلية"),
        ("خدمة منزلية", "خدمة الزيارات المنزلية"),
        ("زيارة منزلية", "خدمة الزيارات المنزلية"),
        ("كيف استلم النتائج", "هل يتم ارسال النتائج الكترونيا"),
        ("كيف أستلم النتائج", "هل يتم ارسال النتائج الكترونيا"),
        ("استلم النتائج", "ارسال النتائج الكترونيا"),
        ("أستلم النتائج", "ارسال النتائج الكترونيا"),
        ("استلام النتائج", "ارسال النتائج الكترونيا"),
        ("هل النتائج سرية", "هل نتائج التحاليل سرية"),
        ("النتائج سرية", "نتائج التحاليل سرية"),
    ]

    for raw_src, raw_dst in alias_pairs:
        src = normalize_text_ar(raw_src)
        dst = normalize_text_ar(raw_dst)
        if not src or not dst:
            continue
        current = list(variants)
        for value in current:
            if src in value:
                variants.add(re.sub(re.escape(src), dst, value))

    return sorted(variants, key=lambda v: len(v), reverse=True)


def _recognize_faq_class_intent(query: str) -> str | None:
    """
    Recognize FAQ-class intents from natural Arabic/Saudi phrasing.
    Kept narrow and rule-based to avoid broad hijacking.
    """
    n = normalize_text_ar(query)
    if not n:
        return None

    home_location = {"بيت", "البيت", "منزل", "المنزل", "مكتب", "المكتب"}
    home_action = {"سحب", "عينه", "العينه", "عيّنه", "زياره", "الزيارات", "تجون", "تاخذون", "متوفر", "خدمه"}
    if (
        "سحب منزلي" in n
        or "سحب عينات من البيت" in n
        or "زيارات منزليه" in n
        or ("منزلي" in n and "سحب" in n)
        or (
            any(t in n for t in home_location)
            and any(t in n for t in home_action)
        )
    ):
        return "home_visit"

    result_core = {"نتيجه", "النتيجه", "نتيجة", "النتيجة", "نتائج", "النتائج"}
    result_delivery = {
        "استلم",
        "استلام",
        "تجيني",
        "ترسلون",
        "واتساب",
        "ايميل",
        "اونلاين",
        "online",
        "تطبيق",
        "الكتروني",
        "الكترونيا",
    }
    has_result_core = any(t in n for t in result_core)
    has_result_delivery = any(t in n for t in result_delivery)
    if (
        ("هل يتم ارسال النتائج" in n)
        or ("ارسال النتائج" in n)
        or (has_result_core and has_result_delivery)
        or ("واتساب" in n and ("ترسل" in n or has_result_core))
        or ("اونلاين" in n and has_result_core)
        or ("online" in n and has_result_core)
    ):
        return "results_delivery"

    privacy_tokens = {
        "سري",
        "سريه",
        "سرية",
        "خصوصيه",
        "خصوصية",
        "خاصه",
        "خاصة",
        "يشوف نتيجتي",
        "يقدر يشوف",
        "المعلومات الطبيه",
        "المعلومات الطبية",
        "بياناتي",
    }
    if any(t in n for t in privacy_tokens):
        return "privacy"

    return None


def _runtime_faq_lookup_by_class_intent(intent: str) -> dict | None:
    faq_items = load_runtime_faq()
    if not isinstance(faq_items, list):
        return None

    intent_patterns: dict[str, tuple[str, ...]] = {
        "home_visit": ("الزيارات المنزلية", "سحب", "منزل"),
        "results_delivery": ("ارسال النتائج", "الكترونيا", "واتساب", "تطبيق", "البريد"),
        "privacy": ("نتائج التحاليل سري", "سرية", "خصوصية"),
    }
    patterns = intent_patterns.get(intent) or ()
    if not patterns:
        return None

    best_item: dict | None = None
    best_score = 0
    for item in faq_items:
        if not isinstance(item, dict):
            continue
        candidate = normalize_text_ar(
            f"{item.get('q_norm') or ''} {item.get('question') or ''} {item.get('answer') or ''}"
        )
        if not candidate:
            continue
        score = sum(1 for p in patterns if normalize_text_ar(p) in candidate)
        if score > best_score:
            best_score = score
            best_item = item

    if best_item is None or best_score <= 0:
        return None

    matched = dict(best_item)
    matched["_match_method"] = "faq_class_intent"
    matched["_match_score"] = float(best_score)
    matched["_matched_q_norm"] = normalize_text_ar(matched.get("q_norm") or matched.get("question") or "")
    return matched


def _safe_faq_class_fallback_reply(intent: str) -> str:
    if intent == "home_visit":
        return f"بالنسبة لخدمة السحب المنزلي، هل تقصد السحب من البيت أو من مقر العمل؟ وللدعم المباشر: {WAREED_CUSTOMER_SERVICE_PHONE}"
    if intent == "results_delivery":
        return "بالنسبة لاستلام النتائج، هل تقصد الاستلام عبر الواتساب أو التطبيق أو البريد الإلكتروني؟"
    if intent == "privacy":
        return "نقدر نوضح لك سياسة خصوصية النتائج. هل تقصد سرية نتائج التحاليل أو صلاحيات الاطلاع على النتيجة؟"
    return safe_clarify_message(WAREED_CUSTOMER_SERVICE_PHONE, "unknown")


def _faq_hijack_guard_reason(query: str) -> str | None:
    n = _normalize_light(query)
    if not n:
        return None

    if _is_general_price_query(query) or any(t in n for t in {"سعر", "اسعار", "أسعار", "تكلفه", "تكلفة", "بكم", "price", "cost"}):
        return "price_query"

    if _is_symptoms_query(query):
        return "symptoms_query"

    light_intent, light_meta = _classify_light_intent(query)
    if light_intent == "branch_location" and bool(light_meta.get("has_city_or_area")):
        return "branch_detail_query"

    package_markers = {"باقه", "باقة", "باقات", "الباقات", "package", "packages"}
    package_detail_markers = {"تفاصيل", "مكونات", "تشمل", "محتوى", "المحتوى", "وش فيها", "ايش فيها", "includes", "list"}
    if any(t in n for t in package_markers) and any(t in n for t in package_detail_markers):
        return "package_detail_query"

    test_explain_markers = {"شرح", "تفسير", "فسر", "ما معنى", "وش يعني", "explain", "interpret", "what is"}
    if is_test_related_question(query) and any(t in n for t in test_explain_markers):
        return "test_explanation_query"

    return None


def expand_query_with_synonyms(text: str) -> str:
    query_norm = normalize_text_ar(text)
    if not query_norm:
        return ""

    synonyms = load_runtime_synonyms()
    if not isinstance(synonyms, dict):
        return query_norm

    additions: list[str] = []
    seen = {query_norm}

    def _add_term(term: str) -> None:
        n = normalize_text_ar(term)
        if not n or n in seen:
            return
        seen.add(n)
        additions.append(n)

    def _match_aliases(aliases: list[str], display: str = "") -> None:
        matched = []
        for alias in aliases:
            a = normalize_text_ar(alias)
            if not a:
                continue
            if a in query_norm or query_norm in a:
                matched.append(a)
        if matched:
            if display:
                _add_term(display)
            for m in matched[:4]:
                _add_term(m)

    for bucket_key in ("tests", "packages", "branches"):
        bucket = synonyms.get(bucket_key) or {}
        if not isinstance(bucket, dict):
            continue
        for concept in bucket.values():
            if not isinstance(concept, dict):
                continue
            aliases = concept.get("aliases") or []
            if not isinstance(aliases, list):
                continue
            display_name = str(concept.get("display_name") or "").strip()
            _match_aliases([str(a) for a in aliases], display=display_name)

    faq_intents = synonyms.get("faq_intents") or {}
    if isinstance(faq_intents, dict):
        for intent_key, aliases in faq_intents.items():
            if not isinstance(aliases, list):
                continue
            _match_aliases([str(a) for a in aliases], display=str(intent_key))

    routing = synonyms.get("routing") or {}
    if isinstance(routing, dict):
        for route_key, aliases in routing.items():
            if not isinstance(aliases, list):
                continue
            _match_aliases([str(a) for a in aliases], display=str(route_key))

    expanded = " ".join([query_norm, *additions]).strip()
    return expanded


def _runtime_faq_lookup(query: str) -> dict | None:
    query_norm = normalize_text_ar(query)
    if not query_norm:
        return None
    query_variants = _expand_faq_query_aliases(query_norm) or [query_norm]
    guard_reason = _faq_hijack_guard_reason(query)
    if guard_reason:
        logger.info(
            "faq route skipped | route=faq_skip | reason=%s | query='%s'",
            guard_reason,
            str(query or "")[:120],
        )
        return None
    faq_items = load_runtime_faq()
    if not isinstance(faq_items, list):
        return None

    best_match: dict | None = None
    best_score = 0.0
    best_method = ""
    best_q_norm = ""
    for item in faq_items:
        if not isinstance(item, dict):
            continue
        candidate_norms = [
            normalize_text_ar(item.get("q_norm") or ""),
            normalize_text_ar(item.get("question") or ""),
        ]
        for candidate_norm in [c for c in candidate_norms if c]:
            for v_idx, query_value in enumerate(query_variants):
                if candidate_norm == query_value:
                    matched = dict(item)
                    matched["_match_method"] = "exact" if v_idx == 0 else "alias_exact"
                    matched["_match_score"] = 1.0
                    matched["_matched_q_norm"] = candidate_norm
                    return matched

                score = _faq_similarity_score(query_value, candidate_norm)
                token_intersection = len(set(query_value.split()) & set(candidate_norm.split()))
                high_confidence = (
                    score >= 0.93
                    or (score >= 0.86 and token_intersection >= 4)
                    or (score >= 0.78 and token_intersection >= 5)
                )
                if not high_confidence:
                    continue
                if score > best_score:
                    best_score = score
                    best_match = item
                    best_method = "high_confidence_similarity" if v_idx == 0 else "alias_similarity"
                    best_q_norm = candidate_norm

    if not best_match:
        return None
    matched = dict(best_match)
    matched["_match_method"] = best_method
    matched["_match_score"] = round(float(best_score), 4)
    matched["_matched_q_norm"] = best_q_norm
    return matched


def extract_price_query_candidate(text: str) -> str:
    normalized = normalize_text_ar(text)
    if not normalized:
        return ""
    # Remove query fillers to keep only the core test phrase/code.
    normalized = normalized.replace("ÙƒÙ… Ø³Ø¹Ø±", " ")
    drop_words = {
        "ÙƒÙ…",
        "Ø³Ø¹Ø±",
        "Ø¨ÙƒÙ…",
        "ØªÙƒÙ„ÙÙ‡",
        "ØªÙƒÙ„ÙØ©",
        "Ø§Ù„Ø³Ø¹Ø±",
        "Ø§Ù„ØªØ­Ù„ÙŠÙ„",
        "ØªØ­Ù„ÙŠÙ„",
        "ÙØ­Øµ",
        "Ø§Ø®ØªØ¨Ø§Ø±",
    }
    tokens = [t for t in normalized.split() if t and t not in drop_words]
    return re.sub(r"\s+", " ", " ".join(tokens)).strip()


def build_price_aliases(record: dict) -> list[str]:
    aliases: set[str] = set()

    def _add(value: str | None) -> None:
        text = str(value or "").strip()
        if text:
            aliases.add(text)

    for key in ("name_ar", "name_en", "canonical_name_clean", "canonical_name"):
        _add(record.get(key))

    code_value = record.get("code")
    if code_value is not None and str(code_value).strip():
        _add(str(code_value).strip())

    for key in (record.get("keys") or []):
        _add(str(key))

    derived: set[str] = set()
    for alias in list(aliases):
        cleaned = re.sub(r"[\(\)\[\]\{\}]", " ", alias)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        _add(cleaned)

        dashed = re.sub(r"[-/]+", " ", cleaned)
        dashed = re.sub(r"\s+", " ", dashed).strip()
        _add(dashed)

        for part in re.split(r"[-/]", alias):
            part = part.strip()
            if part:
                derived.add(part)

        norm_words = normalize_text_ar(cleaned).split()
        for token in norm_words:
            if token.isdigit() or len(token) > 3:
                derived.add(token)
        if len(norm_words) >= 2:
            for i in range(len(norm_words) - 1):
                bi = f"{norm_words[i]} {norm_words[i + 1]}".strip()
                if bi:
                    derived.add(bi)
        if len(norm_words) >= 3:
            tri = " ".join(norm_words[:3]).strip()
            if tri:
                derived.add(tri)

    for item in derived:
        _add(item)

    return sorted(aliases)


def _runtime_price_lookup_reply(query: str, gender: str) -> str | None:
    query_norm = normalize_text_ar(query)
    if not query_norm:
        return None

    is_price_question = any(k in query_norm for k in _PRICE_QUERY_KEYWORDS) or _is_general_price_query(query)
    if not is_price_question:
        return None

    prices_data = load_runtime_prices()
    if isinstance(prices_data, dict):
        price_items = prices_data.get("records") or []
    elif isinstance(prices_data, list):
        price_items = prices_data
    else:
        price_items = []

    def _cap_terms(text: str, max_terms: int, max_chars: int) -> str:
        n = normalize_text_ar(text)
        if not n:
            return ""
        kept: list[str] = []
        seen: set[str] = set()
        for tok in n.split():
            if not tok or tok in seen:
                continue
            seen.add(tok)
            kept.append(tok)
            if len(kept) >= max_terms:
                break
        out = " ".join(kept).strip()
        if len(out) > max_chars:
            out = out[:max_chars].strip()
        return out

    def _cap_relative(base_text: str, expanded_text: str, max_extra_terms: int, max_chars: int) -> str:
        base = _cap_terms(base_text, max_terms=14, max_chars=max_chars)
        exp = _cap_terms(expanded_text, max_terms=40, max_chars=max_chars * 2)
        base_set = set(base.split())
        extras: list[str] = []
        for tok in exp.split():
            if tok in base_set or tok in extras:
                continue
            extras.append(tok)
            if len(extras) >= max_extra_terms:
                break
        out = " ".join([base, *extras]).strip()
        if len(out) > max_chars:
            out = out[:max_chars].strip()
        return out

    candidate_raw = extract_price_query_candidate(query)
    candidate_norm_seed = normalize_text_ar(candidate_raw)
    candidate_tokens = candidate_norm_seed.split()
    is_broad_ar_seed = bool(candidate_norm_seed) and not re.search(r"[a-z0-9]", candidate_norm_seed) and len(candidate_tokens) <= 3
    use_candidate_seed = bool(candidate_norm_seed)
    if (
        use_candidate_seed
        and len(candidate_tokens) <= 1
        and len(candidate_norm_seed) <= 6
        and not re.search(r"[a-zA-Z0-9]", candidate_norm_seed)
    ):
        use_candidate_seed = False
    base_price_query = candidate_raw if use_candidate_seed else query
    expansion_seed = candidate_norm_seed or normalize_text_ar(base_price_query)

    syn_full = expand_query_with_synonyms(expansion_seed) or expansion_seed
    expanded_syn_query = _cap_terms(syn_full, max_terms=14, max_chars=180)
    if is_broad_ar_seed:
        expanded_test_query = expanded_syn_query
        expanded_query = expanded_syn_query
    else:
        test_full = rag_expand_test_query(expanded_syn_query) or expanded_syn_query
        expanded_test_query = _cap_relative(expanded_syn_query, test_full, max_extra_terms=8, max_chars=220)
        concept_full = rag_expand_query_with_concepts(expanded_test_query) or expanded_test_query
        expanded_query = _cap_relative(expanded_test_query, concept_full, max_extra_terms=8, max_chars=260)

    expanded_candidate_raw = extract_price_query_candidate(expanded_query)
    candidate_norm = normalize_text_ar(candidate_raw)
    expanded_candidate_norm = normalize_text_ar(expanded_candidate_raw)
    if not candidate_norm:
        candidate_norm = expanded_candidate_norm or query_norm

    concept_query_seed = candidate_norm_seed or normalize_text_ar(base_price_query)
    concept_matches = rag_collect_concept_matches(concept_query_seed, max_matches=8)
    concept_related_tests: list[str] = []
    concept_related_norm: list[str] = []
    seen_related: set[str] = set()
    for m in concept_matches:
        related = (m.get("related_tests") or []) if isinstance(m, dict) else []
        for rt in related:
            rt_s = str(rt or "").strip()
            rt_n = normalize_text_ar(rt_s)
            if not rt_n or rt_n in seen_related:
                continue
            seen_related.add(rt_n)
            concept_related_tests.append(rt_s)
            concept_related_norm.append(rt_n)
            if len(concept_related_norm) >= 5:
                break
        if len(concept_related_norm) >= 5:
            break

    raw_candidate_token = re.sub(r"\s+", "", str(candidate_raw or "").strip())
    is_short_lab_abbrev = bool(re.fullmatch(r"[A-Za-z]{2,6}\d{0,2}[A-Za-z]{0,2}", raw_candidate_token))
    direct_seed = expanded_candidate_norm or candidate_norm
    has_latin_or_digits = bool(re.search(r"[a-z0-9]", direct_seed or ""))
    likely_direct_seed = has_latin_or_digits or is_short_lab_abbrev
    direct_matches = rag_collect_direct_test_matches(direct_seed, max_matches=8) if likely_direct_seed else []
    direct_alias_terms: set[str] = set()
    direct_name_terms: set[str] = set()
    top_direct_score = float(direct_matches[0].get("score") or 0.0) if direct_matches else 0.0
    for m in direct_matches:
        if not isinstance(m, dict):
            continue
        m_score = float(m.get("score") or 0.0)
        if m_score + 0.02 < top_direct_score:
            continue
        m_type = str(m.get("match_type") or "")
        display_n = normalize_text_ar(m.get("display_name") or "")
        if display_n and m_score >= 0.9:
            direct_name_terms.add(display_n)
        key_n = normalize_text_ar(m.get("key") or "")
        if key_n and m_score >= 0.9:
            direct_name_terms.add(key_n)
        for mt in (m.get("matched_terms") or [])[:4]:
            mt_n = normalize_text_ar(str(mt))
            if mt_n:
                if m_type in {"exact_alias", "abbreviation_or_code"} and m_score >= 0.9:
                    direct_alias_terms.add(mt_n)
                if mt_n == direct_seed and m_score >= 0.88:
                    direct_alias_terms.add(mt_n)
    is_direct_entity = (rag_is_direct_entity_query(direct_seed) if likely_direct_seed else False) or is_short_lab_abbrev
    is_broad_concept_query = bool(concept_related_norm) and not is_short_lab_abbrev and not has_latin_or_digits
    mode_used = "direct_entity" if is_direct_entity else ("concept_related" if is_broad_concept_query else "hybrid")

    print(
        "PRICE_ENTITY_DEBUG",
        {
            "query": str(query or "").encode("unicode_escape").decode("ascii"),
            "expanded": str(expanded_query[:200]).encode("unicode_escape").decode("ascii"),
            "concept_tests": [
                str(x).encode("unicode_escape").decode("ascii")
                for x in concept_related_tests[:5]
            ],
        },
    )
    print(
        "PRICE_RUNTIME_DEBUG",
        {
            "query": str(query or "").encode("unicode_escape").decode("ascii"),
            "candidate": str(candidate_norm or "").encode("unicode_escape").decode("ascii"),
            "expanded_len": len(expanded_query or ""),
            "related_tests_count": len(concept_related_norm),
            "mode": mode_used,
        },
    )

    is_numeric_candidate = bool(re.fullmatch(r"\d+", candidate_norm))
    candidate_len = len(candidate_norm)
    query_code_tokens: set[str] = set()
    for tok in re.findall(r"\b[A-Za-z]{2,10}\d{0,3}[A-Za-z]{0,3}\d{0,2}\b", query or ""):
        t = normalize_text_ar(tok)
        if t:
            query_code_tokens.add(t)
    for tok in re.findall(r"\b[A-Za-z]{2,10}\d{0,3}[A-Za-z]{0,3}\d{0,2}\b", expanded_query or ""):
        t = normalize_text_ar(tok)
        if t:
            query_code_tokens.add(t)

    def _debug_payload(best_match: str | None, score: float) -> dict:
        safe_candidate = str(candidate_norm).encode("unicode_escape").decode("ascii")
        safe_match = (
            str(best_match).encode("unicode_escape").decode("ascii")
            if best_match is not None
            else None
        )
        return {"candidate": safe_candidate, "best_match": safe_match, "best_score": score}

    # Numeric-only rule: only strict code match is allowed.
    if is_numeric_candidate:
        for item in price_items:
            if not isinstance(item, dict):
                continue
            code_value = str(item.get("code") or "").strip()
            if code_value and code_value == candidate_norm:
                display_name = (
                    (item.get("name_ar") or "").strip()
                    or (item.get("canonical_name_clean") or "").strip()
                    or (item.get("name_en") or "").strip()
                    or "Ø§Ù„ØªØ­Ù„ÙŠÙ„"
                )
                price_value = item.get("price")
                print("PATH=runtime_price code")
                print(
                    "PRICE_MATCH_DEBUG",
                    _debug_payload(display_name, 1000),
                )
                if price_value is None:
                    return f"Ø³Ø¹Ø± {display_name}: ØºÙŠØ± Ù…ØªÙˆÙØ± Ø­Ø§Ù„ÙŠØ§Ù‹"
                return f"Ø³Ø¹Ø± {display_name}: {price_value}"
        print("PATH=runtime_price no_match")
        print(
            "PRICE_MATCH_DEBUG",
            _debug_payload(None, 0),
        )
        return None

    generic_alias_blacklist = {"vit", "test", "analysis", "serum", "lab", "blood"}
    MAX_SCAN_ITEMS = 450
    MAX_FUZZY_BUDGET = 450

    def _item_norm_fields(item: dict) -> tuple[list[str], list[str], str]:
        aliases = build_price_aliases(item)
        alias_norms: list[str] = []
        for alias in aliases:
            alias_n = normalize_text_ar(alias)
            if alias_n:
                alias_norms.append(alias_n)
        alias_norms = list(dict.fromkeys(alias_norms))

        filtered_aliases: list[str] = []
        for alias_n in alias_norms:
            if len(alias_n) < 3:
                continue
            tokens = alias_n.split()
            if len(tokens) == 1 and tokens[0] in generic_alias_blacklist:
                continue
            filtered_aliases.append(alias_n)

        normalized_names: list[str] = []
        for key in ("name_ar", "canonical_name_clean", "name_en", "canonical_name"):
            val = normalize_text_ar(item.get(key) or "")
            if val:
                normalized_names.append(val)
        normalized_names = list(dict.fromkeys(normalized_names))
        code_norm = normalize_text_ar(str(item.get("code") or ""))
        return filtered_aliases, normalized_names, code_norm

    # Fast direct abbreviation mode: prefer exact alias/name/code and return quickly.
    if is_short_lab_abbrev:
        scanned = 0
        for item in price_items:
            if not isinstance(item, dict):
                continue
            scanned += 1
            if scanned > MAX_SCAN_ITEMS:
                break
            filtered_aliases, normalized_names, code_norm = _item_norm_fields(item)
            if (
                (code_norm and code_norm == candidate_norm)
                or (candidate_norm in filtered_aliases)
                or (candidate_norm in normalized_names)
            ):
                display_name = (
                    (item.get("name_ar") or "").strip()
                    or (item.get("canonical_name_clean") or "").strip()
                    or (item.get("name_en") or "").strip()
                    or "Ø§Ù„ØªØ­Ù„ÙŠÙ„"
                )
                price_value = item.get("price")
                path = "code" if code_norm and code_norm == candidate_norm else "exact"
                print(f"PATH=runtime_price {path}")
                print("PRICE_MATCH_DEBUG", _debug_payload(display_name, 950))
                if price_value is None:
                    return f"Ø³Ø¹Ø± {display_name}: ØºÙŠØ± Ù…ØªÙˆÙØ± Ø­Ø§Ù„ÙŠØ§Ù‹"
                return f"Ø³Ø¹Ø± {display_name}: {price_value}"
        print("PATH=runtime_price no_match")
        print("PRICE_MATCH_DEBUG", _debug_payload(None, 0))
        return None

    # Broad concept mode: try related tests directly in ranked order, then exit quickly.
    if is_broad_concept_query:
        if not concept_related_norm:
            print("PATH=runtime_price no_match")
            print("PRICE_MATCH_DEBUG", _debug_payload(None, 0))
            return None
        scanned = 0
        max_concept_scan = 180
        for rel in concept_related_norm[:5]:
            for item in price_items:
                if not isinstance(item, dict):
                    continue
                scanned += 1
                if scanned > max_concept_scan:
                    print("PATH=runtime_price no_match")
                    print("PRICE_MATCH_DEBUG", _debug_payload(None, 0))
                    return None
                code_norm = normalize_text_ar(str(item.get("code") or ""))
                normalized_names = []
                for key in ("name_ar", "canonical_name_clean", "name_en", "canonical_name"):
                    val = normalize_text_ar(item.get(key) or "")
                    if val:
                        normalized_names.append(val)
                for key_item in (item.get("keys") or []):
                    kn = normalize_text_ar(str(key_item))
                    if kn:
                        normalized_names.append(kn)
                normalized_names = list(dict.fromkeys(normalized_names))
                if (
                    rel in normalized_names
                    or (code_norm and rel == code_norm)
                    or any(len(rel) >= 3 and (rel in n or n in rel) for n in normalized_names[:12])
                ):
                    display_name = (
                        (item.get("name_ar") or "").strip()
                        or (item.get("canonical_name_clean") or "").strip()
                        or (item.get("name_en") or "").strip()
                        or "Ø§Ù„ØªØ­Ù„ÙŠÙ„"
                    )
                    price_value = item.get("price")
                    print("PATH=runtime_price alias")
                    print("PRICE_MATCH_DEBUG", _debug_payload(display_name, 700))
                    if price_value is None:
                        return f"Ø³Ø¹Ø± {display_name}: ØºÙŠØ± Ù…ØªÙˆÙØ± Ø­Ø§Ù„ÙŠØ§Ù‹"
                    return f"Ø³Ø¹Ø± {display_name}: {price_value}"
        print("PATH=runtime_price no_match")
        print("PRICE_MATCH_DEBUG", _debug_payload(None, 0))
        return None

    best_item: dict | None = None
    best_path = "no_match"
    best_score = -1.0
    second_score = -1.0
    fuzzy_budget = MAX_FUZZY_BUDGET
    scanned_items = 0

    try:
        from difflib import SequenceMatcher
    except Exception:
        SequenceMatcher = None

    for idx, item in enumerate(price_items):
        if not isinstance(item, dict):
            continue
        scanned_items += 1
        if scanned_items > MAX_SCAN_ITEMS:
            break

        filtered_aliases, normalized_names, code_norm = _item_norm_fields(item)
        if not filtered_aliases:
            continue

        local_path = "no_match"
        local_score = -1.0

        # 1) exact test code
        if code_norm and (
            candidate_norm == code_norm
            or expanded_candidate_norm == code_norm
            or code_norm in query_code_tokens
        ):
            local_path = "code"
            local_score = 1000 - (idx / 10000)

        # 2) direct test alias
        if local_score < 900:
            if (
                candidate_norm in filtered_aliases
                or (expanded_candidate_norm and expanded_candidate_norm in filtered_aliases)
                or (direct_alias_terms and any(a in direct_alias_terms for a in filtered_aliases))
            ):
                local_path = "exact"
                local_score = 900 - (idx / 10000)

        # 3) canonical/display name
        if local_score < 800:
            if (
                candidate_norm in normalized_names
                or (expanded_candidate_norm and expanded_candidate_norm in normalized_names)
                or (direct_name_terms and any(n in direct_name_terms for n in normalized_names))
            ):
                local_path = "name_exact"
                local_score = 800 - (idx / 10000)

        # 4) concept related_tests
        if local_score < 700 and concept_related_norm:
            found_concept_rel = False
            for crt in concept_related_norm:
                if crt in filtered_aliases or crt in normalized_names:
                    found_concept_rel = True
                    break
                if any(len(crt) >= 3 and (crt in a or a in crt) for a in filtered_aliases):
                    found_concept_rel = True
                    break
            if found_concept_rel:
                local_path = "concept"
                local_score = 700 - (idx / 10000)

        # 5) alias contains candidate (candidate length >= 5)
        if local_score < 650 and candidate_len >= 5:
            for alias_n in filtered_aliases:
                if candidate_norm in alias_n:
                    coverage = (candidate_len / max(len(alias_n), 1)) * 100.0
                    score = 600 + min(coverage, 50) - (idx / 10000)
                    if score > local_score:
                        local_score = score
                        local_path = "alias"

        # candidate contains alias (alias length >= 5)
        if local_score < 560:
            for alias_n in filtered_aliases:
                if len(alias_n) < 5:
                    continue
                if alias_n in candidate_norm:
                    coverage = (len(alias_n) / max(candidate_len, 1)) * 100.0
                    score = 560 + min(coverage, 40) - (idx / 10000)
                    if score > local_score:
                        local_score = score
                        local_path = "alias"

        # 6) fuzzy match with stricter thresholds
        if local_score < 300 and SequenceMatcher is not None and len(candidate_norm) >= 3 and fuzzy_budget > 0:
            max_ratio = 0.0
            for alias_n in filtered_aliases:
                if fuzzy_budget <= 0:
                    break
                fuzzy_budget -= 1
                ratio = SequenceMatcher(None, candidate_norm, alias_n).ratio() * 100
                threshold = 90 if len(alias_n) < 8 else 85
                if ratio < threshold:
                    continue
                if ratio > max_ratio:
                    max_ratio = ratio
            if max_ratio > 0:
                local_path = "fuzzy"
                local_score = 300 + max_ratio - (idx / 10000)

        # Direct-entity tie-break preference.
        if is_direct_entity and local_score >= 0:
            if local_path in {"exact", "name_exact", "code"}:
                local_score += 20
            elif local_path == "concept":
                local_score += 5

        if local_score > second_score:
            second_score = local_score
        if local_score > best_score:
            second_score = best_score
            best_score = local_score
            best_item = item
            best_path = local_path

    if scanned_items > MAX_SCAN_ITEMS:
        print("PATH=runtime_price no_match")
        print(
            "PRICE_MATCH_DEBUG",
            _debug_payload(None, round(best_score, 2) if best_score >= 0 else 0),
        )
        return None

    if not best_item or best_score < 300:
        print("PATH=runtime_price no_match")
        print(
            "PRICE_MATCH_DEBUG",
            _debug_payload(None, round(best_score, 2) if best_score >= 0 else 0),
        )
        return None

    # Ambiguous top results should not return a possibly wrong price.
    if second_score >= 0 and abs(best_score - second_score) < 5:
        best_name = (
            (best_item.get("name_ar") or "").strip()
            or (best_item.get("canonical_name_clean") or "").strip()
            or (best_item.get("name_en") or "").strip()
            or "Ø§Ù„ØªØ­Ù„ÙŠÙ„"
        )
        print("PATH=runtime_price no_match")
        print(
            "PRICE_MATCH_DEBUG",
            _debug_payload(best_name, round(best_score, 2)),
        )
        return None

    display_name = (
        (best_item.get("name_ar") or "").strip()
        or (best_item.get("canonical_name_clean") or "").strip()
        or (best_item.get("name_en") or "").strip()
        or "Ø§Ù„ØªØ­Ù„ÙŠÙ„"
    )
    price_value = best_item.get("price")

    if best_path == "code":
        print("PATH=runtime_price code")
    elif best_path == "exact":
        print("PATH=runtime_price exact")
    elif best_path == "name_exact":
        print("PATH=runtime_price exact")
    elif best_path == "concept":
        print("PATH=runtime_price alias")
    elif best_path == "fuzzy":
        print("PATH=runtime_price fuzzy")
    elif best_path == "alias":
        print("PATH=runtime_price alias")
    else:
        print("PATH=runtime_price no_match")
        print(
            "PRICE_MATCH_DEBUG",
            _debug_payload(None, round(best_score, 2)),
        )
        return None

    print(
        "PRICE_MATCH_DEBUG",
        _debug_payload(display_name, round(best_score, 2)),
    )
    if price_value is None:
        return f"Ø³Ø¹Ø± {display_name}: ØºÙŠØ± Ù…ØªÙˆÙØ± Ø­Ø§Ù„ÙŠØ§Ù‹"
    return f"Ø³Ø¹Ø± {display_name}: {price_value}"


def is_test_related_question(text: str) -> bool:
    value = str(text or "")
    if not value.strip():
        return False
    lowered = value.lower()
    markers = (
        "ØªØ­Ù„ÙŠÙ„",
        "ÙØ­Øµ",
        "Ø§Ø®ØªØ¨Ø§Ø±",
        "Ø§Ø¹Ø±Ø§Ø¶",
        "Ø£Ø¹Ø±Ø§Ø¶",
        "ØµÙŠØ§Ù…",
        "ØªØ­Ø¶ÙŠØ±",
        "Ù‚Ø¨Ù„ Ø§Ù„ØªØ­Ù„ÙŠÙ„",
        "hba1c",
        "Ø³ÙƒØ±",
        "cbc",
        "ferritin",
        "tsh",
        "vit",
        "vitamin",
        "ÙÙŠØªØ§Ù…ÙŠÙ†",
    )
    return any(marker in value or marker in lowered for marker in markers)


def _is_simple_greeting(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    greetings = {
        "Ù…Ø±Ø­Ø¨Ø§",
        "Ø§Ù‡Ù„Ø§",
        "Ø£Ù‡Ù„Ø§",
        "Ù‡Ù„Ø§",
        "Ø§Ù„Ø³Ù„Ø§Ù… Ø¹Ù„ÙŠÙƒÙ…",
        "Ø§Ù„Ø³Ù„Ø§Ù…",
        "hi",
        "hello",
        "hey",
    }
    if n in greetings:
        return True
    if len(n.split()) <= 2 and any(g in n for g in greetings):
        return True
    return False


def _greeting_reply() -> str:
    return "Ø£Ù‡Ù„Ø§Ù‹ Ø¨ÙƒØŒ ÙƒÙŠÙ Ø£Ù‚Ø¯Ø± Ø£Ø³Ø§Ø¹Ø¯Ùƒ Ø§Ù„ÙŠÙˆÙ…ØŸ"


def _select_top_rag_result(rag_results: list[dict]) -> dict | None:
    candidates = [
        r for r in (rag_results or [])
        if isinstance(r, dict) and isinstance(r.get("test"), dict)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: float(r.get("score") or 0.0), reverse=True)
    return candidates[0]


def _format_compact_test_fallback_reply(question: str, rag_results: list[dict]) -> str | None:
    if not rag_results:
        return None
    best = _select_top_rag_result(rag_results) or {}
    test = (best.get("test") or {}) if isinstance(best, dict) else {}
    name = (
        str(test.get("analysis_name_ar") or "").strip()
        or str(test.get("analysis_name_en") or "").strip()
        or "Ø§Ù„ØªØ­Ù„ÙŠÙ„"
    )
    selected_test_id = str(test.get("test_id") or test.get("id") or "").strip() or None
    print(
        "COMPACT_FALLBACK_DEBUG",
        {
            "query": question,
            "selected_test_name": name,
            "selected_test_id": selected_test_id,
            "source_of_selection": "format_compact_top_rag_result",
        },
    )
    desc = str(test.get("description") or "").strip()
    prep = str(test.get("preparation") or "").strip()
    symptoms = str(test.get("symptoms") or "").strip()
    price = test.get("price")
    qn = _normalize_light(question)

    if any(k in qn for k in {"Ø³Ø¹Ø±", "Ø¨ÙƒÙ…", "ØªÙƒÙ„ÙØ©", "ØªÙƒÙ„ÙÙ‡", "price", "cost"}):
        if price is None:
            return f"Ø³Ø¹Ø± {name} ØºÙŠØ± Ù…ØªÙˆÙØ± Ø­Ø§Ù„ÙŠØ§Ù‹ØŒ ÙˆÙ„Ù„Ø§Ø³ØªÙØ³Ø§Ø± ØªÙ‚Ø¯Ø± ØªØªÙˆØ§ØµÙ„ Ù…Ø¹Ù†Ø§ Ø¹Ù„Ù‰ {WAREED_CUSTOMER_SERVICE_PHONE}."
        return f"Ø³Ø¹Ø± {name}: {price}."

    if any(k in qn for k in {"ØµÙŠØ§Ù…", "ØªØ­Ø¶ÙŠØ±", "Ù‚Ø¨Ù„ Ø§Ù„ØªØ­Ù„ÙŠÙ„", "preparation", "fasting"}):
        if prep:
            return f"Ø¨Ø§Ù„Ù†Ø³Ø¨Ø© Ø¥Ù„Ù‰ {name}: {prep}"
        if desc:
            return f"{name}: {desc}"
        return f"Ø­Ø§Ù„ÙŠØ§Ù‹ Ù…Ø§ Ø¹Ù†Ø¯Ù†Ø§ ØªÙØ§ØµÙŠÙ„ ÙƒØ§ÙÙŠØ© Ø¹Ù† {name}."

    if any(k in qn for k in {"Ø§Ø¹Ø±Ø§Ø¶", "Ø£Ø¹Ø±Ø§Ø¶", "Ø¹Ù†Ø¯ÙŠ", "Ø§Ø­Ø³", "Ø£Ø­Ø³", "Ø¯ÙˆØ®Ù‡", "Ø¯ÙˆØ®Ø©", "Ø®Ù…ÙˆÙ„"}):
        if symptoms:
            return f"Ù…Ù† Ø§Ù„ØªØ­Ø§Ù„ÙŠÙ„ Ø§Ù„Ù…Ø±ØªØ¨Ø·Ø© Ø¨Ù€ {name}: {symptoms}"
        if desc:
            return f"{name}: {desc}"
        return f"Ø­Ø§Ù„ÙŠØ§Ù‹ Ù…Ø§ Ø¹Ù†Ø¯Ù†Ø§ ØªÙØ§ØµÙŠÙ„ ÙƒØ§ÙÙŠØ© Ø¹Ù† {name}."

    if desc:
        return f"{name}: {desc}"
    if prep:
        return f"{name}: {prep}"
    return f"Ø­Ø§Ù„ÙŠØ§Ù‹ Ù…Ø§ Ø¹Ù†Ø¯Ù†Ø§ ØªÙØ§ØµÙŠÙ„ ÙƒØ§ÙÙŠØ© Ø¹Ù† {name}."


def _runtime_tests_rag_reply(question: str, expanded_query: str, history: list | None) -> str | None:
    if not is_rag_ready():
        return None
    threshold = getattr(settings, "RAG_SIMILARITY_THRESHOLD", 0.58)
    ctx, has_match = get_grounded_context(
        question,
        max_tests=2,
        similarity_threshold=threshold,
        include_prices=True,
        use_cache=True,
    )
    if (not has_match or not ctx or not ctx.strip()) and expanded_query and expanded_query != question:
        ctx, has_match = get_grounded_context(
            expanded_query,
            max_tests=2,
            similarity_threshold=threshold,
            include_prices=True,
            use_cache=True,
        )
    if not has_match or not ctx or not ctx.strip():
        print(
            "TEST_ANSWER_PATH",
            {
                "query": question,
                "has_match": bool(has_match),
                "used_openai": False,
                "used_compact_fallback": False,
                "short_circuited": False,
            },
        )
        return None

    used_openai = False
    used_compact_fallback = False
    ai_result = openai_service.generate_response(
        user_message=question,
        knowledge_context=ctx,
        conversation_history=history,
    )
    used_openai = True
    ai_response = ""
    ai_success = False
    if isinstance(ai_result, dict):
        ai_response = str(ai_result.get("response") or "").strip()
        ai_success = bool(ai_result.get("success")) and bool(ai_response)
    ai_unusable = (
        not ai_success
        or "Ù„Ø§ ØªØªÙˆÙØ± Ù„Ø¯ÙŠ Ù…Ø¹Ù„ÙˆÙ…Ø§Øª" in ai_response
        or NO_INFO_MESSAGE in ai_response
    )
    if not ai_unusable:
        print(
            "TEST_ANSWER_PATH",
            {
                "query": question,
                "has_match": True,
                "used_openai": used_openai,
                "used_compact_fallback": False,
                "short_circuited": True,
            },
        )
        return ai_response

    rag_results, has_hit = retrieve(
        question,
        max_results=3,
        similarity_threshold=threshold,
    )
    source_of_selection = "retrieve(question)"
    if (not has_hit or not rag_results) and expanded_query and expanded_query != question:
        rag_results, has_hit = retrieve(
            expanded_query,
            max_results=3,
            similarity_threshold=threshold,
        )
        source_of_selection = "retrieve(expanded_query)"

    if has_hit and rag_results:
        selected = _select_top_rag_result(rag_results)
        selected_test = (selected or {}).get("test") if isinstance(selected, dict) else {}
        print(
            "COMPACT_FALLBACK_DEBUG",
            {
                "query": question,
                "selected_test_name": (
                    str((selected_test or {}).get("analysis_name_ar") or "").strip()
                    or str((selected_test or {}).get("analysis_name_en") or "").strip()
                    or None
                ),
                "selected_test_id": str((selected_test or {}).get("test_id") or (selected_test or {}).get("id") or "").strip() or None,
                "source_of_selection": source_of_selection,
            },
        )
        compact_reply = _format_compact_test_fallback_reply(
            question,
            [selected] if selected else rag_results,
        )
        if compact_reply:
            used_compact_fallback = True
            print(
                "TEST_ANSWER_PATH",
                {
                    "query": question,
                    "has_match": True,
                    "used_openai": used_openai,
                    "used_compact_fallback": used_compact_fallback,
                    "short_circuited": True,
                },
            )
            return compact_reply

    # Last fallback: compact context itself (already cleaned in rag_pipeline).
    print(
        "TEST_ANSWER_PATH",
        {
            "query": question,
            "has_match": True,
            "used_openai": used_openai,
            "used_compact_fallback": used_compact_fallback,
            "short_circuited": True,
        },
    )
    return ctx.strip()


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
    if any(w in n for w in {"Ø­ÙŠ", "Ø§Ù„Ø­ÙŠ", "Ø§Ù„Ù…Ù†Ø·Ù‚Ø©", "Ù…Ù†Ø·Ù‚Ù‡", "Ø§Ù„Ù…Ù†Ø·Ù‚Ù‡", "district", "area"}):
        return True, "area"
    return False, ""


def _classify_light_intent(text: str) -> tuple[str, dict]:
    raw = (text or "").strip().lower()
    n = _normalize_light(text)
    merged = f"{raw} {n}".strip()
    has_city, city = _detect_city_or_area(text)
    meta = {"has_city_or_area": has_city, "city_or_area": city}

    if _contains_any(merged, {"Ù…ØªÙ‰ ØªØ·Ù„Ø¹", "Ù…ØªÙ‰ ØªØ¬Ù‡Ø²", "Ù…Ø¯Ø© Ø§Ù„Ù†ØªÙŠØ¬Ø©", "Ù…Ø¯Ù‡ Ø§Ù„Ù†ØªÙŠØ¬Ù‡", "ÙˆÙ‚Øª Ø§Ù„Ù†ØªÙŠØ¬Ø©", "ÙˆÙ‚Øª Ø§Ù„Ù†ØªÙŠØ¬Ù‡", "ÙƒÙ… ÙŠÙˆÙ…", "Ø§Ù„Ù†ØªØ§Ø¦Ø¬", "Ø§Ù„Ù†ØªØ§ÙŠØ¬", "turnaround", "results time"}):
        return "result_time", meta
    if _contains_any(
        merged,
        {
            "Ø§Ù‚Ø±Ø¨ ÙØ±Ø¹",
            "Ø£Ù‚Ø±Ø¨ ÙØ±Ø¹",
            "ÙˆÙŠÙ† Ø§Ù„ÙØ±Ø¹",
            "Ù…ÙƒØ§Ù† Ø§Ù„ÙØ±Ø¹",
            "Ù…ÙˆÙ‚Ø¹ Ø§Ù„ÙØ±Ø¹",
            "branch",
            "location",
            "ÙˆÙŠÙ† Ø§Ù‚Ø±Ø¨",
            "ÙˆÙŠÙ† Ø§Ù‚Ø±Ø¨ ÙØ±Ø¹",
            "Ù…ÙƒØ§Ù†ÙƒÙ…",
            "ÙˆÙŠÙ† Ù…ÙƒØ§Ù†",
            "Ù…ÙˆÙ‚Ø¹ÙƒÙ…",
            "Ø¹Ù†ÙˆØ§Ù†ÙƒÙ…",
            "ÙˆÙŠÙ† Ù…ÙˆÙ‚Ø¹",
            "Ù„ÙˆÙƒÙŠØ´Ù†",
            "Ø§Ù„Ù…ÙˆÙ‚Ø¹",
            "Ù…ÙƒØ§Ù†Ùƒ",
        },
    ):
        return "branch_location", meta
    if _contains_any(merged, {"ÙƒÙ… Ø³Ø¹Ø±", "Ø§Ù„Ø³Ø¹Ø±", "Ø§Ø³Ø¹Ø§Ø±", "Ø£Ø³Ø¹Ø§Ø±", "ØªÙƒÙ„ÙØ©", "ØªÙƒÙ„ÙÙ‡", "price", "cost"}):
        return "pricing", meta
    if _contains_any(merged, {"Ø§Ø³ØªÙ„Ø§Ù… Ø§Ù„Ù†ØªÙŠØ¬Ù‡", "Ø§Ø³ØªÙ„Ø§Ù… Ø§Ù„Ù†ØªÙŠØ¬Ø©", "ÙƒÙŠÙ Ø§Ø³ØªÙ„Ù…", "ÙƒÙŠÙ ØªÙˆØµÙ„ Ø§Ù„Ù†ØªÙŠØ¬Ù‡", "ÙˆØ§ØªØ³Ø§Ø¨", "Ø§ÙŠÙ…ÙŠÙ„", "email", "ØªØ·Ø¨ÙŠÙ‚", "delivery"}):
        return "result_delivery", meta
    if _contains_any(merged, {"Ø´ÙƒÙˆÙ‰", "Ø´ÙƒÙˆÙŠ", "Ù…Ø´ÙƒÙ„Ø©", "Ù…Ø´ÙƒÙ„Ù‡", "ØºÙŠØ± Ø±Ø§Ø¶ÙŠ", "Ù…Ùˆ Ø±Ø§Ø¶ÙŠ", "Ø³ÙŠØ¦Ø©", "Ø³ÙŠØ¦Ù‡", "complaint"}):
        return "complaint", meta
    return "other", meta


def _is_working_hours_query(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False

    # Avoid clashing with results/turnaround timing questions.
    result_time_markers = {
        "Ù†ØªÙŠØ¬Ù‡",
        "Ù†ØªÙŠØ¬Ø©",
        "Ù†ØªØ§ÙŠØ¬",
        "Ù…ØªÙ‰ ØªØ·Ù„Ø¹",
        "Ù…Ø¯Ø© Ø§Ù„Ù†ØªÙŠØ¬Ø©",
        "Ù…Ø¯Ù‡ Ø§Ù„Ù†ØªÙŠØ¬Ù‡",
        "ÙˆÙ‚Øª Ø§Ù„Ù†ØªÙŠØ¬Ø©",
        "ÙˆÙ‚Øª Ø§Ù„Ù†ØªÙŠØ¬Ù‡",
    }
    if any(m in n for m in result_time_markers):
        return False

    return any(t in n for t in _WORKING_HOURS_TRIGGERS)


def _working_hours_deterministic_reply() -> str:
    return "Ø³Ø§Ø¹Ø§Øª Ø§Ù„Ø¯ÙˆØ§Ù…: 24 Ø³Ø§Ø¹Ø© ÙŠÙˆÙ…ÙŠØ§Ù‹.\nÙˆÙ…ØªÙˆÙØ± Ø£ÙŠØ¶Ø§Ù‹ Ø§Ù„Ø³Ø­Ø¨ Ø§Ù„Ù…Ù†Ø²Ù„ÙŠ Ù„Ù„Ø­Ø¬Ø²: 920003694"


def _is_general_price_query(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    return any(t in n for t in {_normalize_light(x) for x in _GENERAL_PRICE_TRIGGERS})


def _detect_preparation_priority(question: str, expanded_query: str = "") -> bool:
    qn = _normalize_light(question)
    if not qn:
        return False
    prep_tokens = {"ØµÙŠØ§Ù…", "ØªØ­Ø¶ÙŠØ±", "Ù‚Ø¨Ù„ Ø§Ù„ØªØ­Ù„ÙŠÙ„", "preparation", "fasting"}
    if not any(t in qn for t in prep_tokens):
        return False
    # Generic short prep prompts should keep button flow unless a concept match exists.
    if len(qn.split()) <= 3 and not re.search(r"[a-z0-9]", qn):
        seed = _normalize_light(expanded_query) or qn
        return bool(rag_collect_concept_matches(seed, max_matches=1))
    if is_test_related_question(question):
        return True
    seed = _normalize_light(expanded_query) or qn
    return bool(rag_collect_concept_matches(seed, max_matches=2))


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
    return "Ø§Ù„Ù…Ø¹Ù„ÙˆÙ…Ø© ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯Ø© Ø¨Ø´ÙƒÙ„ ÙˆØ§Ø¶Ø­ ÙÙŠ Ù‚Ø§Ø¹Ø¯Ø© Ø§Ù„Ù…Ø¹Ø±ÙØ© Ù„Ù‡Ø°Ù‡ Ø§Ù„Ø£Ø¹Ø±Ø§Ø¶."


def _format_symptoms_rag_reply(results: list[dict]) -> str:
    lines = ["Ù‡Ø°Ù‡ Ø£Ù‚Ø±Ø¨ 3 Ø®ÙŠØ§Ø±Ø§Øª Ø­Ø³Ø¨ Ø§Ù„Ø£Ø¹Ø±Ø§Ø¶ Ø§Ù„Ù…Ø°ÙƒÙˆØ±Ø©:"]
    for i, row in enumerate((results or [])[:3], 1):
        test = row.get("test") or {}
        title = (test.get("analysis_name_ar") or test.get("analysis_name_en") or "Ø®ÙŠØ§Ø± ØºÙŠØ± Ù…Ø­Ø¯Ø¯").strip()
        tests_list = _extract_tests_list_from_rag_test(test)
        lines.append(f"{i}) {title} â€” {tests_list}")
    lines.append("ØªÙ†Ø¨ÙŠÙ‡: Ù‡Ø°Ø§ Ù…Ø­ØªÙˆÙ‰ ØªØ«Ù‚ÙŠÙÙŠ Ù…Ù† Ù‚Ø§Ø¹Ø¯Ø© Ø§Ù„Ù…Ø¹Ø±ÙØ©ØŒ ÙˆÙ„Ù„ØªØ´Ø®ÙŠØµ Ø§Ù„Ù†Ù‡Ø§Ø¦ÙŠ Ø±Ø§Ø¬Ø¹ Ø§Ù„Ø·Ø¨ÙŠØ¨.")
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
        "result_time": {"Ù†ØªÙŠØ¬Ù‡", "Ù†ØªÙŠØ¬Ø©", "ØªØ·Ù„Ø¹", "Ø¬Ø§Ù‡Ø²Ù‡", "Ø¬Ø§Ù‡Ø²Ø©", "ÙˆÙ‚Øª"},
        "branch_location": {"ÙØ±Ø¹", "Ø¹Ù†ÙˆØ§Ù†", "Ù…ÙˆÙ‚Ø¹", "Ø§Ù‚Ø±Ø¨"},
        "pricing": {"Ø³Ø¹Ø±", "ØªÙƒÙ„ÙÙ‡", "ØªÙƒÙ„ÙØ©", "price", "cost"},
        "result_delivery": {"ÙˆØ§ØªØ³Ø§Ø¨", "Ø§ÙŠÙ…ÙŠÙ„", "email", "ØªØ·Ø¨ÙŠÙ‚", "Ø§Ø³ØªÙ„Ø§Ù…"},
        "complaint": {"Ø´ÙƒÙˆÙ‰", "Ø´ÙƒÙˆÙŠ", "Ø§Ø¹ØªØ°Ø§Ø±", "ØªØ¹ÙˆÙŠØ¶", "Ø§Ø³ÙÙŠÙ†", "Ù…Ø´ÙƒÙ„Ø©", "Ù…Ø´ÙƒÙ„Ù‡"},
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

    lines = ["ðŸŽ¯ **Style Guidance Examples (tone only):**"]
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
    parts = ["ðŸ“Š **Ù…Ø¹Ù„ÙˆÙ…Ø§Øª Ø§Ù„ØªØ­Ø§Ù„ÙŠÙ„ Ø°Ø§Øª Ø§Ù„ØµÙ„Ø©:**\n"]
    for i, row in enumerate(rag_results[:3], 1):
        test = row.get("test") or {}
        lines = [f"ðŸ”¬ **{test.get('analysis_name_ar', 'ØºÙŠØ± Ù…ØªÙˆÙØ±')}**"]
        if test.get("analysis_name_en"):
            lines.append(f"   ({test.get('analysis_name_en')})")
        if test.get("description"):
            lines.append(f"\nðŸ“ **Ø§Ù„ÙˆØµÙ:** {test.get('description')}")
        if include_prices and test.get("price") is not None:
            lines.append(f"\nðŸ’µ **Ø§Ù„Ø³Ø¹Ø±:** {test.get('price')}")
        if test.get("category"):
            lines.append(f"\nðŸ“‚ **Ø§Ù„ØªØµÙ†ÙŠÙ:** {test.get('category')}")
        parts.append(f"\n{i}. " + "\n".join(lines) + "\n" + "-" * 50 + "\n")
    return "".join(parts)


def _branch_location_prompt(city_or_area: str = "") -> str:
    if city_or_area and city_or_area != "area":
        return (
            f"Ù„ØªØ­Ø¯ÙŠØ¯ Ø£Ù‚Ø±Ø¨ ÙØ±Ø¹ ÙÙŠ {city_or_area} Ø¨Ø¯Ù‚Ø©ØŒ Ø´Ø§Ø±ÙƒÙ†Ø§ Ø§Ø³Ù… Ø§Ù„Ø­ÙŠ/Ø§Ù„Ù…Ù†Ø·Ù‚Ø©. "
            f"ÙˆÙ„Ù„Ø¯Ø¹Ù… Ø§Ù„Ù…Ø¨Ø§Ø´Ø± ØªÙ‚Ø¯Ø± ØªØªÙˆØ§ØµÙ„ Ø¹Ù„Ù‰ {WAREED_CUSTOMER_SERVICE_PHONE}."
        )
    return (
        "Ø¹Ø´Ø§Ù† Ù†Ø­Ø¯Ø¯ Ø£Ù‚Ø±Ø¨ ÙØ±Ø¹ Ù„Ùƒ Ø¨Ø¯Ù‚Ø©ØŒ Ø§ÙƒØªØ¨ Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© Ø£Ùˆ Ø§Ù„Ø­ÙŠ. "
        f"ÙˆÙ„Ù„Ø¯Ø¹Ù… Ø§Ù„Ù…Ø¨Ø§Ø´Ø± ØªÙ‚Ø¯Ø± ØªØªÙˆØ§ØµÙ„ Ø¹Ù„Ù‰ {WAREED_CUSTOMER_SERVICE_PHONE}."
    )


def _user_explicitly_asked_home_visit(text: str) -> bool:
    n = _normalize_light(text)
    return any(k in n for k in {"Ø²ÙŠØ§Ø±Ø© Ù…Ù†Ø²Ù„ÙŠØ©", "Ø³Ø­Ø¨ Ù…Ù†Ø²Ù„ÙŠ", "home visit", "Ù…Ù†Ø²Ù„ÙŠ"})


def _sanitize_branch_location_response(text: str, has_city_or_area: bool, allow_home_visit: bool = False) -> str:
    n = _normalize_light(text)
    if not allow_home_visit and any(k in n for k in {"Ø²ÙŠØ§Ø±Ø© Ù…Ù†Ø²Ù„ÙŠØ©", "Ø³Ø­Ø¨ Ù…Ù†Ø²Ù„ÙŠ", "home visit", "Ù…Ù†Ø²Ù„ÙŠ"}):
        if not has_city_or_area:
            return _branch_location_prompt()
        return (
            "Ù„ØªØ­Ø¯ÙŠØ¯ Ø£Ù‚Ø±Ø¨ ÙØ±Ø¹ Ø¨Ø¯Ù‚Ø© Ø¯Ø§Ø®Ù„ Ù…Ø¯ÙŠÙ†ØªÙƒØŒ Ø§ÙƒØªØ¨ Ø§Ø³Ù… Ø§Ù„Ø­ÙŠ/Ø§Ù„Ù…Ù†Ø·Ù‚Ø© "
            f"Ø£Ùˆ ØªÙˆØ§ØµÙ„ Ù…Ø¹ Ø®Ø¯Ù…Ø© Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡ Ø¹Ù„Ù‰ {WAREED_CUSTOMER_SERVICE_PHONE}."
        )
    return text


def _has_verified_branch_info(kb_context: str) -> bool:
    raw_text = (kb_context or "").lower()
    text = _normalize_light(kb_context or "")
    if not raw_text and not text:
        return False
    raw_signals = ("Ø§Ù„Ø¹Ù†ÙˆØ§Ù†", "Ø³Ø§Ø¹Ø§Øª Ø§Ù„Ø¹Ù…Ù„", "Ø§ÙˆÙ‚Ø§Øª Ø§Ù„Ø¹Ù…Ù„", "Ù…ÙˆØ§Ø¹ÙŠØ¯ Ø§Ù„Ø¹Ù…Ù„", "Ø£ÙˆÙ‚Ø§Øª Ø§Ù„Ø¹Ù…Ù„")
    if any(sig in raw_text for sig in raw_signals):
        return True
    strong_signals = (
        "Ø§Ù„Ø¹Ù†ÙˆØ§Ù†",
        "Ø³Ø§Ø¹Ø§Øª Ø§Ù„Ø¹Ù…Ù„",
        "Ø§ÙˆÙ‚Ø§Øª Ø§Ù„Ø¹Ù…Ù„",
        "Ù…ÙˆØ§Ø¹ÙŠØ¯ Ø§Ù„Ø¹Ù…Ù„",
    )
    if "Ø§Ù„Ø¹Ù†ÙˆØ§Ù†" in text and any(sig in text for sig in ("Ø³Ø§Ø¹Ø§Øª Ø§Ù„Ø¹Ù…Ù„", "Ø§ÙˆÙ‚Ø§Øª Ø§Ù„Ø¹Ù…Ù„", "Ù…ÙˆØ§Ø¹ÙŠØ¯ Ø§Ù„Ø¹Ù…Ù„", "Ø¯ÙˆØ§Ù…")):
        return True
    if any(sig in text for sig in strong_signals):
        return True
    return bool(re.search(r"(ÙØ±Ø¹|branch).{0,40}(Ø§Ù„Ø¹Ù†ÙˆØ§Ù†|Ø³Ø§Ø¹Ø§Øª|Ø¯ÙˆØ§Ù…|Ù…ÙˆØ§Ø¹ÙŠØ¯)", text))


def _ensure_result_time_clause(text: str, light_intent: str) -> str:
    if light_intent != "result_time":
        return text
    required_clause = "Ø¨Ø¹Ø¶ Ø§Ù„ÙØ­ÙˆØµØ§Øª Ù‚Ø¯ ØªØ­ØªØ§Ø¬ ÙˆÙ‚Øª Ø£Ø·ÙˆÙ„ Ø­Ø³Ø¨ Ù†ÙˆØ¹Ù‡Ø§"
    if required_clause in (text or ""):
        return text
    clean = (text or "").strip()
    if not clean:
        return required_clause
    return f"{clean}\n\n{required_clause}"


def _branch_state_key(conversation_id: UUID) -> str:
    return f"branch_selection:{conversation_id}"


def _to_western_digits(text) -> str:
    try:
        if text is None:
            return ""
        if isinstance(text, (int, float)):
            value = str(text)
        elif isinstance(text, str):
            value = text
        else:
            value = str(text)

        trans = {ord(chr(0x0660 + i)): ord(str(i)) for i in range(10)}
        return value.translate(trans)
    except Exception:
        try:
            return "" if text is None else str(text)
        except Exception:
            return ""


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
    "باقات",
    "تحليل",
    "تحاليل",
    "فحص",
    "بكم",
    "سعر",
    "تفاصيل",
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

    banned = ("ÙØ±Ø¹", "Ø®Ø¯Ù…Ø© Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡", "maps", "Ø±Ø§Ø¨Ø· Ø§Ù„Ù…ÙˆÙ‚Ø¹", "customer service")
    preferred = ("ØªØ´Ù…Ù„", "ÙŠÙØ³ØªØ®Ø¯Ù…", "ÙŠØ³ØªØ®Ø¯Ù…", "ÙŠØ³Ø§Ø¹Ø¯", "ÙŠÙÙŠØ¯", "Ù…Ù†Ø§Ø³Ø¨", "Ù…Ø¯Ø© Ø§Ù„Ù†ØªØ§Ø¦Ø¬", "Ù†ÙˆØ¹ Ø§Ù„Ø¹ÙŠÙ†Ø©")

    lines: list[str] = []
    for ln in desc.splitlines():
        clean = re.sub(r"\s+", " ", ln).strip(" -\tâ€¢")
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
            chunks.extend(re.split(r"[.!ØŸ]+", ln))
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
            "last_prompt": "Ø§Ø®ØªØ± Ø±Ù‚Ù… Ø§Ù„Ø®ÙŠØ§Ø± Ø§Ù„Ù…Ù†Ø§Ø³Ø¨ Ù„Ø£Ø±Ø³Ù„ Ù„Ùƒ Ø§Ù„ØªÙØ§ØµÙŠÙ„ ÙˆØ§Ù„Ø³Ø¹Ø±.",
        },
    )


def _format_package_options_from_state(options: list[dict]) -> str:
    lines = ["Ù‡Ø°Ù‡ Ø§Ù„Ø®ÙŠØ§Ø±Ø§Øª Ø§Ù„Ù…ØªØ§Ø­Ø©:"]
    for i, option in enumerate(options or [], 1):
        lines.append(f"{i}) {(option.get('name_raw') or '').strip()}")
    lines.append("Ø§Ø®ØªØ± Ø±Ù‚Ù… Ø§Ù„Ø®ÙŠØ§Ø± Ø§Ù„Ù…Ù†Ø§Ø³Ø¨ Ù„Ø£Ø±Ø³Ù„ Ù„Ùƒ Ø§Ù„ØªÙØ§ØµÙŠÙ„ ÙˆØ§Ù„Ø³Ø¹Ø±.")
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
        return "Ù…Ø§ Ù‚Ø¯Ø±Øª Ø£Ø­Ø¯Ø¯ Ø§Ù„Ø¨Ø§Ù‚Ø©/Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ù…Ù† Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø­Ø§Ù„ÙŠØ©. Ø§ÙƒØªØ¨ Ø§Ù„Ø§Ø³Ù… Ø¨Ø´ÙƒÙ„ Ø£Ù‚Ø±Ø¨ Ø£Ùˆ Ø§Ø°ÙƒØ± Ø§Ù„Ù‡Ø¯Ù (Ù…Ø«Ø§Ù„: ÙÙŠØªØ§Ù…ÙŠÙ† Ø¯ / Ø­Ø³Ø§Ø³ÙŠØ© / Ù‡Ø±Ù…ÙˆÙ†Ø§Øª)."

    numeric = _extract_number_choice(message)
    if numeric is not None:
        return "Ø§Ø®ØªØ§Ø± Ø±Ù‚Ù… ØµØ­ÙŠØ­ Ù…Ù† Ø§Ù„Ù‚Ø§Ø¦Ù…Ø©:\n" + _format_package_options_from_state(options)

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

        return "Ù…Ø§ Ù‚Ø¯Ø±Øª Ø£Ø­Ø¯Ø¯ Ø§Ù„Ø¨Ø§Ù‚Ø©/Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ù…Ù† Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø­Ø§Ù„ÙŠØ©. Ø§ÙƒØªØ¨ Ø§Ù„Ø§Ø³Ù… Ø¨Ø´ÙƒÙ„ Ø£Ù‚Ø±Ø¨ Ø£Ùˆ Ø§Ø°ÙƒØ± Ø§Ù„Ù‡Ø¯Ù (Ù…Ø«Ø§Ù„: ÙÙŠØªØ§Ù…ÙŠÙ† Ø¯ / Ø­Ø³Ø§Ø³ÙŠØ© / Ù‡Ø±Ù…ÙˆÙ†Ø§Øª)."

    return "Ø§Ø®ØªØ§Ø± Ø±Ù‚Ù… ØµØ­ÙŠØ­ Ù…Ù† Ø§Ù„Ù‚Ø§Ø¦Ù…Ø©:\n" + _format_package_options_from_state(options)


def _package_lookup_bypass_reply(question: str, conversation_id: UUID) -> str | None:
    query = (question or "").strip()
    if not query:
        return None

    faq_class_intent = _recognize_faq_class_intent(query)
    if faq_class_intent:
        logger.info(
            "package route skipped | reason=faq_class_intent | faq_intent=%s | query='%s'",
            faq_class_intent,
            query[:120],
        )
        return None

    trigger = _is_package_query_candidate(query)
    if not trigger:
        return None

    # Direct deterministic hit first.
    single = match_single_package(query)
    if single:
        _reset_package_state(conversation_id)
        _save_state(conversation_id, _complete_flow(_default_flow_state()))
        return _format_package_details_strict(single)

    candidates = _dedupe_package_records_for_options(search_packages(query, top_k=6))
    if candidates:
        _save_package_selection_state(conversation_id, query, candidates)
        return _format_package_list_strict(candidates)

    # Semantic fallback over packages_kb.json only (after deterministic path fails).
    rag_threshold = 0.75
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
                return "Ø­Ø³Ø¨ Ø§Ù„ÙˆØµÙ Ø§Ù„Ø£Ù‚Ø±Ø¨ ÙÙŠ Ø§Ù„Ù†Ø¸Ø§Ù…:\n" + details

    if trigger:
        return "Ù…Ø§ Ù‚Ø¯Ø±Øª Ø£Ø­Ø¯Ø¯ Ø§Ù„Ø¨Ø§Ù‚Ø©/Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ù…Ù† Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø­Ø§Ù„ÙŠØ©. Ø§ÙƒØªØ¨ Ø§Ù„Ø§Ø³Ù… Ø¨Ø´ÙƒÙ„ Ø£Ù‚Ø±Ø¨ Ø£Ùˆ Ø§Ø°ÙƒØ± Ø§Ù„Ù‡Ø¯Ù (Ù…Ø«Ø§Ù„: ÙÙŠØªØ§Ù…ÙŠÙ† Ø¯ / Ø­Ø³Ø§Ø³ÙŠØ© / Ù‡Ø±Ù…ÙˆÙ†Ø§Øª)."
    return None


# Manual test plan (Phase 5):
# 1) "Well DNA Silver" -> details (no branch mention)
# 2) "Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ø­Ø³Ø§Ø³ÙŠØ©" -> names-only list -> choose 1 -> details -> state cleared
# 3) "ÙƒÙ… Ø³Ø¹Ø± ØªØ­Ø§Ù„ÙŠÙ„ Ø§Ù„ÙƒØ¨Ø¯ØŸ" -> list or details deterministically
# 4) Send "99" after list -> invalid -> correction + same list
# 5) While package_flow active: user says "ÙˆÙŠÙ† Ø§Ù‚Ø±Ø¨ ÙØ±Ø¹" -> package reset -> branch logic handles
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
        "ÙƒÙ… Ø±Ù‚Ù… Ø§Ù„Ù‡Ø§ØªÙ",
        "Ø±Ù‚Ù… Ø§Ù„Ù‡Ø§ØªÙ",
        "Ø±Ù‚Ù…ÙƒÙ…",
        "Ø§Ø¨ÙŠ Ø§Ù„Ø±Ù‚Ù…",
        "Ø£Ø¨ÙŠ Ø§Ù„Ø±Ù‚Ù…",
    }
    if any(k in n for k in explicit):
        return True

    if n in {"Ø§Ù„Ø±Ù‚Ù…", "Ø±Ù‚Ù…"}:
        return True

    # Ambiguous "Ø§Ù„Ø±Ù‚Ù…" should be treated as a follow-up only if prior assistant context supports it.
    if "Ø§Ù„Ø±Ù‚Ù…" in n or n == "Ø±Ù‚Ù…":
        pn = _normalize_light(previous_assistant_text)
        context_keywords = {
            "Ø­Ø¬Ø²",
            "Ù…ÙˆØ¹Ø¯",
            "Ø²ÙŠØ§Ø±Ù‡ Ù…Ù†Ø²Ù„ÙŠÙ‡",
            "Ø²ÙŠØ§Ø±Ø© Ù…Ù†Ø²Ù„ÙŠØ©",
            "Ø³Ø­Ø¨ Ù…Ù†Ø²Ù„ÙŠ",
            "Ø®Ø¯Ù…Ø§Øª",
            "Ø³Ø¹Ø±",
            "Ø§Ø³Ø¹Ø§Ø±",
            "ØªÙƒÙ„ÙÙ‡",
            "ØªÙƒÙ„ÙØ©",
            "ÙØ±Ø¹",
            "ÙØ±ÙˆØ¹",
            "Ù…ÙˆÙ‚Ø¹",
            "Ù„ÙˆÙƒÙŠØ´Ù†",
            "Ø®Ø¯Ù…Ø© Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡",
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
        return f"Ø±Ù‚Ù… Ø®Ø¯Ù…Ø© Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡: {WAREED_CUSTOMER_SERVICE_PHONE}"
    return None


def _is_home_visit_button_request(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    if "ÙˆØ±ÙŠØ¯ ÙƒÙŠØ±" in n and "Ø³Ø­Ø¨ Ù…Ù†Ø²Ù„ÙŠ" in n:
        return True
    if "Ø§Ø¨ØºÙ‰ Ø®Ø¯Ù…Ø© Ø³Ø­Ø¨ Ù…Ù†Ø²Ù„ÙŠ" in n or "Ø£Ø¨ØºÙ‰ Ø®Ø¯Ù…Ø© Ø³Ø­Ø¨ Ù…Ù†Ø²Ù„ÙŠ" in n:
        return True
    return False


def _is_booking_howto_query(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    return any(
        k in n
        for k in {
            "ÙƒÙŠÙ Ø§Ø­Ø¬Ø² Ù…ÙˆØ¹Ø¯",
            "ÙƒÙŠÙ Ø£Ø­Ø¬Ø² Ù…ÙˆØ¹Ø¯",
            "ÙƒÙŠÙ Ø§Ø­Ø¬Ø²",
            "ÙƒÙŠÙ Ø£Ø­Ø¬Ø²",
            "Ø­Ø¬Ø² Ù…ÙˆØ¹Ø¯",
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
            "Ù…ØªÙˆÙØ± Ù„Ø¯ÙŠÙ†Ø§ Ø®Ø¯Ù…Ø© Ø³Ø­Ø¨ Ø§Ù„Ø¹ÙŠÙ†Ø§Øª Ù…Ù† Ø§Ù„Ù…Ù†Ø²Ù„ Ø£Ùˆ Ù…Ù‚Ø± Ø§Ù„Ø¹Ù…Ù„ Ù…Ø¹ Ø§Ù„Ø§Ù„ØªØ²Ø§Ù… Ø¨Ù…Ø¹Ø§ÙŠÙŠØ± Ø§Ù„ØªØ¹Ù‚ÙŠÙ…ØŒ "
            f"ÙˆØ¶Ù…Ø§Ù† Ø³Ø±Ø¹Ø© Ø¸Ù‡ÙˆØ± Ø§Ù„Ù†ØªØ§Ø¦Ø¬. Ù„Ù„Ø­Ø¬Ø²: {WAREED_CUSTOMER_SERVICE_PHONE}"
        )

    # Deterministic short follow-up after the dedicated home-visit reply.
    if _is_booking_howto_query(user_message):
        previous_assistant_text = _last_assistant_message_within(db, conversation_id, minutes=15)
        if previous_assistant_text.startswith("Ù…ØªÙˆÙØ± Ù„Ø¯ÙŠÙ†Ø§ Ø®Ø¯Ù…Ø© Ø³Ø­Ø¨ Ø§Ù„Ø¹ÙŠÙ†Ø§Øª Ù…Ù† Ø§Ù„Ù…Ù†Ø²Ù„ Ø£Ùˆ Ù…Ù‚Ø± Ø§Ù„Ø¹Ù…Ù„"):
            return f"Ù„Ù„Ø­Ø¬Ø²: {WAREED_CUSTOMER_SERVICE_PHONE}"
    return None


def _is_preparation_button_trigger(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    return n == _normalize_light("Ø§Ù„ØªØ­Ø¶ÙŠØ± Ù‚Ø¨Ù„ Ø§Ù„ØªØ­Ù„ÙŠÙ„")


def _resolve_preparation_button_reply(user_message: str) -> str | None:
    if _is_preparation_button_trigger(user_message):
        return "Ø£ÙƒÙŠØ¯. Ø§ÙƒØªØ¨ Ø§Ø³Ù… Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ø§Ù„Ù„ÙŠ ØªØ¨ÙŠ ØªØ¹Ø±Ù Ø§Ù„ØªØ­Ø¶ÙŠØ± Ù„Ù‡ (Ù…Ø«Ø§Ù„: ÙÙŠØªØ§Ù…ÙŠÙ† Ø¯ / CBC / Ø£Ù„Ø¯ÙˆØ³ØªÙŠØ±ÙˆÙ†)."
    return None


def _is_services_branches_home_visit_start_trigger(text: str) -> bool:
    n = _normalize_light(text)
    if not n:
        return False
    triggers = {
        "Ø§Ù„Ø®Ø¯Ù…Ø§Øª ÙˆØ§Ù„ÙØ±ÙˆØ¹ ÙˆØ§Ù„Ø³Ø­Ø¨ Ø§Ù„Ù…Ù†Ø²Ù„ÙŠ",
        "Ø§Ø¨Ø¯Ø£ Ø§Ù„Ø·Ù„Ø¨",
        "Ø§Ø¨Ø¯Ø§ Ø§Ù„Ø·Ù„Ø¨",
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
        "ÙŠÙ‚Ø¯Ù… Ù…Ø®ØªØ¨Ø± ÙˆØ±ÙŠØ¯ Ø®Ø¯Ù…Ø§Øª Ø§Ù„ØªØ­Ø§Ù„ÙŠÙ„ Ø§Ù„Ù…Ø®Ø¨Ø±ÙŠØ©ØŒ ÙˆØ¨Ø§Ù‚Ø§Øª Ø§Ù„ÙØ­ÙˆØµØ§ØªØŒ ÙˆØ®Ø¯Ù…Ø© Ø§Ù„Ø³Ø­Ø¨ Ø§Ù„Ù…Ù†Ø²Ù„ÙŠ.\n"
        "Ù„Ù„Ø§Ø³ØªÙØ³Ø§Ø± Ø£Ùˆ Ø§Ù„Ø­Ø¬Ø²: 920003694\n"
        "ÙˆØ¥Ø°Ø§ Ø­Ø§Ø¨ ØªØ¹Ø±Ù Ø§Ù„ÙØ±Ø¹ Ø§Ù„Ø£Ù‚Ø±Ø¨ Ù„ÙƒØŒ Ø§ÙƒØªØ¨ Ø§Ø³Ù… Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© (Ù…Ø«Ø§Ù„: Ø§Ù„Ø±ÙŠØ§Ø¶ / Ø¬Ø¯Ø©) Ø£Ùˆ Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© + Ø§Ù„Ø­ÙŠ."
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
            "Ø¥Ù„ØºØ§Ø¡",
            "Ø§Ù„ØºØ§Ø¡",
            "cancel",
            "restart",
            "Ø§Ø¨Ø¯Ø§ Ù…Ù† Ø¬Ø¯ÙŠØ¯",
            "Ø§Ø¨Ø¯Ø£ Ù…Ù† Ø¬Ø¯ÙŠØ¯",
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
            "Ø§Ù‚Ø±Ø¨ ÙØ±Ø¹",
            "ÙˆÙŠÙ† Ø§Ù„ÙØ±Ø¹",
            "Ù…ÙˆÙ‚Ø¹ Ø§Ù„ÙØ±Ø¹",
            "Ø§Ù„ÙØ±Ø¹ Ø§Ù„Ù‚Ø±ÙŠØ¨",
            "ÙØ±ÙˆØ¹",
            "branch",
            "location",
            "Ù…ÙƒØ§Ù† Ø§Ù„ÙØ±Ø¹",
            "Ù…ÙƒØ§Ù†ÙƒÙ…",
            "ÙˆÙŠÙ† Ù…ÙƒØ§Ù†",
            "Ù…ÙˆÙ‚Ø¹ÙƒÙ…",
            "Ø¹Ù†ÙˆØ§Ù†ÙƒÙ…",
            "ÙˆÙŠÙ† Ù…ÙˆÙ‚Ø¹",
            "Ù„ÙˆÙƒÙŠØ´Ù†",
            "Ø§Ù„Ù…ÙˆÙ‚Ø¹",
            "Ù…ÙƒØ§Ù†Ùƒ",
        },
    ),
    (
        "package_flow",
        {
            "Ø¨Ø§Ù‚Ø©",
            "Ø¨Ø§Ù‚Ù‡",
            "ØªØ­Ø§Ù„ÙŠÙ„",
            "ØªØ­Ø§Ù„ÛŒÙ„",
            "ØªØ­Ù„ÙŠÙ„",
            "ÙØ­Øµ",
        },
    ),
    (
        "pricing_flow",
        {"ÙƒÙ… Ø³Ø¹Ø±", "Ø³Ø¹Ø±", "Ø§Ø³Ø¹Ø§Ø±", "ØªÙƒÙ„ÙÙ‡", "ØªÙƒÙ„ÙØ©", "price", "pricing", "cost"},
    ),
    (
        "result_flow",
        {"Ù†ØªÙŠØ¬Ù‡", "Ù†ØªÙŠØ¬Ø©", "Ù†ØªØ§ÙŠØ¬", "Ù…ØªÙ‰ ØªØ·Ù„Ø¹", "Ø±Ù‚Ù… Ø§Ù„Ø·Ù„Ø¨", "order", "result"},
    ),
    (
        "complaint_flow",
        {"Ø´ÙƒÙˆÙ‰", "Ø´ÙƒÙˆÙŠ", "Ù…Ø´ÙƒÙ„Ø©", "Ù…Ø´ÙƒÙ„Ù‡", "complaint", "Ø§Ø¹ØªØ±Ø§Ø¶"},
    ),
]

_RESULT_FLOW_PROMPT = "Ø²ÙˆÙ‘Ø¯Ù†ÙŠ Ø¨Ø±Ù‚Ù… Ø§Ù„Ø·Ù„Ø¨ Ø£Ùˆ Ø±Ù‚Ù… Ø§Ù„Ø¬ÙˆØ§Ù„ Ùˆ ØªØ§Ø±ÙŠØ® Ø§Ù„Ø²ÙŠØ§Ø±Ø©ØŒ Ø£Ùˆ Ø§Ø±ÙÙ‚ ØµÙˆØ±Ø©/Ù…Ù„Ù Ù„Ù„Ù†ØªØ§Ø¦Ø¬ Ø¹Ø´Ø§Ù† Ø£Ø´Ø±Ø­Ù‡Ø§ Ù„Ùƒ."


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
        "Ù†ØªÙŠØ¬Ø©",
        "Ù†ØªÙŠØ¬Ù‡",
        "Ù†ØªØ§ÙŠØ¬",
        "Ø´Ø±Ø­ Ø§Ù„Ù†ØªØ§Ø¦Ø¬",
        "Ø´Ø±Ø­ Ù†ØªØ§ÙŠØ¬",
        "ØªÙØ³ÙŠØ± Ø§Ù„Ù†ØªØ§Ø¦Ø¬",
        "Ù†ØªØ§Ø¦Ø¬ Ø§Ù„ØªØ­Ù„ÙŠÙ„",
        "Ø±Ù‚Ù… Ø§Ù„Ø·Ù„Ø¨",
        "ØªØ§Ø±ÙŠØ® Ø§Ù„Ø²ÙŠØ§Ø±Ø©",
        "Ø§Ø±ÙÙ‚",
        "Ø£Ø±ÙÙ‚",
        "ØµÙˆØ±Ø©",
        "Ù…Ù„Ù",
        "report",
    }
    return any(m in n for m in result_markers)


def _extract_test_name_for_pricing(text: str) -> str:
    n = _normalize_light(text)
    if not n:
        return ""
    cleaned = re.sub(r"[ØŸ?]", " ", n)
    cleaned = re.sub(r"\b(ÙƒÙ…|Ø³Ø¹Ø±|ØªÙƒÙ„ÙÙ‡|ÙÙŠ|Ø§Ù„Ø±ÙŠØ§Ø¶|Ø¬Ø¯Ù‡|price|pricing)\b", " ", cleaned, flags=re.IGNORECASE)
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
    lines = [f"Ù‡Ø°Ù‡ ÙØ±ÙˆØ¹Ù†Ø§ Ø§Ù„Ù…ØªÙˆÙØ±Ø© ÙÙŠ {city}:"]
    for i, b in enumerate(branches, 1):
        lines.append("")
        lines.append(_format_branch_item(i, b))
    lines.append("")
    lines.append("Ø§ÙƒØªØ¨ Ø§Ø³Ù… Ø§Ù„Ø­ÙŠ Ø£Ùˆ Ø±Ù‚Ù… Ø§Ù„ÙØ±Ø¹ Ø¥Ø°Ø§ ØªØ­Ø¨ Ø£Ø­Ø¯Ø¯ Ù„Ùƒ Ø§Ù„Ø£Ù†Ø³Ø¨.")
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
    "ÙØ±Ø¹",
    "Ø§Ù„ÙØ±Ø¹",
    "ÙØ±ÙˆØ¹",
    "Ù…ÙˆÙ‚Ø¹",
    "Ø§Ù„Ù…ÙˆÙ‚Ø¹",
    "Ø¹Ù†ÙˆØ§Ù†",
    "Ù„ÙˆÙƒÙŠØ´Ù†",
    "Ù…ÙƒØ§Ù†",
    "Ù…ÙƒØ§Ù†ÙƒÙ…",
    "Ù…ÙƒØ§Ù†Ùƒ",
    "Ù…ÙˆÙ‚Ø¹ÙƒÙ…",
    "Ø¹Ù†ÙˆØ§Ù†ÙƒÙ…",
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
        if branch_name_n.startswith("ÙØ±Ø¹ "):
            short_name = branch_name_n[4:].strip()
            if short_name:
                variants.add(short_name)
        if branch_name_n.startswith("Ø§Ù„ÙØ±Ø¹ "):
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
    "ÙØ±ÙˆØ¹ÙƒÙ…",
    "Ø§Ù„ÙØ±ÙˆØ¹",
    "ÙØ±ÙˆØ¹",
    "Ø§Ù„Ù…ØªÙˆÙØ±Ù‡",
    "Ø§Ù„Ù…ØªÙˆÙØ±Ø©",
    "Ø¹Ù†Ø¯ÙƒÙ…",
    "Ù…Ø¹Ø§ÙƒÙ…",
    "ÙÙŠ",
    "ÙˆÙŠÙ†",
    "Ø§Ù‚Ø±Ø¨",
    "ÙØ±Ø¹",
    "Ø§Ù„ÙØ±Ø¹",
    "Ù…ÙˆØ¬ÙˆØ¯Ù‡",
    "Ù…ÙˆØ¬ÙˆØ¯Ø©",
    "Ù…Ø§Ù‡ÙŠ",
    "Ù…Ø§",
    "Ù‡ÙŠ",
    "ÙˆØ´",
    "Ø§ÙŠØ´",
    "Ø§Ø¨ÙŠ",
    "Ø§Ø¨ØºÙ‰",
    "Ù„Ùˆ",
    "Ø³Ù…Ø­Øª",
    "Ù„ÙˆØ³Ù…Ø­Øª",
    "Ø­Ø¯Ø¯",
    "Ù„ÙŠ",
    "Ù…Ø¯ÙŠÙ†Ù‡",
    "Ù…Ø¯ÙŠÙ†Ø©",
}

_BRANCH_DISTRICT_IGNORE_TOKENS = {
    "ÙØ±ÙˆØ¹ÙƒÙ…",
    "Ø§Ù„ÙØ±ÙˆØ¹",
    "Ø§Ù„Ù…ØªÙˆÙØ±Ù‡",
    "Ø§Ù„Ù…ØªÙˆÙØ±Ø©",
    "Ø¹Ù†Ø¯ÙƒÙ…",
    "Ù…Ø¹Ø§ÙƒÙ…",
    "ÙÙŠ",
    "ÙˆÙŠÙ†",
    "Ø§Ù‚Ø±Ø¨",
    "ÙØ±Ø¹",
    "Ø§Ù„ÙØ±Ø¹",
    "Ù…ÙˆØ¬ÙˆØ¯Ù‡",
    "Ù…ÙˆØ¬ÙˆØ¯Ø©",
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
    lines = [f"Ù‡Ø°Ù‡ Ø§Ù„ÙØ±ÙˆØ¹ Ø§Ù„Ù…ØªÙˆÙØ±Ø© ÙÙŠ {city}:"]
    for i, b in enumerate(branches, 1):
        lines.append(f"{i}) {b.get('branch_name', '').strip()}")
    lines.append("Ø­Ø¯Ø¯ÙŠ Ø±Ù‚Ù… Ø§Ù„ÙØ±Ø¹ Ø§Ù„Ø£Ù‚Ø±Ø¨ Ù„Ùƒ Ù„Ø£Ø²ÙˆÙ‘Ø¯Ùƒ Ø¨Ø±Ø§Ø¨Ø· Ø§Ù„Ù…ÙˆÙ‚Ø¹.")
    return "\n".join(lines)


def _format_selected_branch(choice: int, branch: dict) -> str:
    branch_name = (branch.get("branch_name") or "").strip()
    maps_url = (branch.get("maps_url") or "").strip()
    hours = (branch.get("hours") or "").strip()
    phone = (branch.get("phone") or "").strip()
    lines = [f"Ø§Ù„ÙØ±Ø¹ Ø±Ù‚Ù… {choice}: {branch_name}", ""]
    if maps_url:
        lines.append("Ø±Ø§Ø¨Ø· Ø§Ù„Ù…ÙˆÙ‚Ø¹:")
        lines.append(maps_url)
    if _is_real_phone_number(phone):
        lines.append("")
        lines.append(f"Ù‡Ø§ØªÙ Ø§Ù„ÙØ±Ø¹: {phone}")
    if hours:
        if not _is_real_phone_number(phone):
            lines.append("")
        lines.append(f"Ø³Ø§Ø¹Ø§Øª Ø§Ù„Ø¹Ù…Ù„: {hours}")
    return "\n".join(lines)


def _format_city_not_found_reply(city: str) -> str:
    cities = get_available_cities()
    cities_text = "ØŒ ".join(cities) if cities else "-"
    return (
        f"Ø­Ø§Ù„ÙŠØ§Ù‹ Ù„Ø§ ÙŠÙˆØ¬Ø¯ Ù„Ø¯ÙŠÙ†Ø§ ÙØ±ÙˆØ¹ ÙÙŠ {city}.\n"
        f"Ø§Ù„Ù…Ø¯Ù† Ø§Ù„Ù…ØªÙˆÙØ±Ø© Ù„Ø¯ÙŠÙ†Ø§ Ø­Ø§Ù„ÙŠØ§Ù‹ ÙÙŠ: {cities_text}\n"
        f"ÙˆÙ„Ø£ÙŠ Ù…Ø³Ø§Ø¹Ø¯Ø© Ø¥Ø¶Ø§ÙÙŠØ©: {_branch_phone()}"
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
            "last_prompt": "Ø­Ø¯Ø¯ÙŠ Ø±Ù‚Ù… Ø§Ù„ÙØ±Ø¹ Ø§Ù„Ø£Ù‚Ø±Ø¨ Ù„Ùƒ Ù„Ø£Ø²ÙˆÙ‘Ø¯Ùƒ Ø¨Ø±Ø§Ø¨Ø· Ø§Ù„Ù…ÙˆÙ‚Ø¹.",
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
            return "Ø¹Ø´Ø§Ù† Ø£ØªØ­Ù‚Ù‚ Ù„Ùƒ Ù…Ù† Ø§Ù„Ù…ÙˆÙ‚Ø¹ Ø¨Ø§Ù„Ø¶Ø¨Ø·ØŒ Ø®Ø¨Ø±Ù†ÙŠ Ø¹Ù† Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© Ø§Ù„Ù„ÙŠ Ø£Ù†Øª ÙÙŠÙ‡Ø§ ÙˆØ¨Ø¹Ø±Ø¶ Ù„Ùƒ Ø§Ù„ÙØ±ÙˆØ¹ Ø§Ù„Ù…ØªÙˆÙØ±Ø© ÙˆØªØ®ØªØ§Ø± Ø§Ù„Ø£Ù‚Ø±Ø¨ Ù„Ùƒ."

    # Case A: no city
    city_raw, district = _extract_city_and_district(question)
    if not city_raw:
        return "Ø¹Ø´Ø§Ù† Ø£Ø­Ø¯Ø¯ Ø£Ù‚Ø±Ø¨ ÙØ±Ø¹ØŒ Ø§ÙƒØªØ¨ Ø§Ø³Ù… Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© (Ù…Ø«Ø§Ù„: Ø§Ù„Ø±ÙŠØ§Ø¶ / Ø¬Ø¯Ø©) Ø£Ùˆ Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© + Ø§Ù„Ø­ÙŠ."

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
            f"Ù…Ø§ Ù„Ù‚ÙŠÙ†Ø§ Ø§Ù„Ø­ÙŠ Ø§Ù„Ù…Ø°ÙƒÙˆØ± Ø¨Ø§Ù„Ø§Ø³Ù… Ø¯Ø§Ø®Ù„ Ù‚Ø§Ø¦Ù…ØªÙ†Ø§ØŒ Ù„ÙƒÙ† Ù‡Ø°Ù‡ ÙØ±ÙˆØ¹ {city} Ø§Ù„Ù…ØªÙˆÙØ±Ø©:\n"
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
        state["last_prompt"] = "Ø¹Ø´Ø§Ù† Ø£Ø­Ø¯Ø¯ Ø£Ù‚Ø±Ø¨ ÙØ±Ø¹ØŒ Ø§ÙƒØªØ¨ Ø§Ø³Ù… Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© (Ù…Ø«Ø§Ù„: Ø§Ù„Ø±ÙŠØ§Ø¶ / Ø¬Ø¯Ø©) Ø£Ùˆ Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© + Ø§Ù„Ø­ÙŠ."
    elif flow_name == "pricing_flow":
        state["step"] = "awaiting_test_name"
        state["last_prompt"] = "ÙˆØ´ Ø§Ø³Ù… Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ø§Ù„Ù„ÙŠ ØªØ¨ØºÙ‰ Ø³Ø¹Ø±Ù‡ØŸ"
    elif flow_name == "package_flow":
        state["step"] = "awaiting_choice"
        state["last_prompt"] = "Ø§ÙƒØªØ¨ Ø§Ø³Ù… Ø§Ù„Ø¨Ø§Ù‚Ø©/Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ø£Ùˆ Ø§Ø®ØªØ± Ø±Ù‚Ù… Ù…Ù† Ø§Ù„Ø®ÙŠØ§Ø±Ø§Øª Ø¥Ø°Ø§ Ø¸Ù‡Ø±Øª Ù„Ùƒ Ù‚Ø§Ø¦Ù…Ø©."
    elif flow_name == "result_flow":
        state["step"] = "awaiting_identifier"
        state["last_prompt"] = _RESULT_FLOW_PROMPT
    elif flow_name == "complaint_flow":
        state["step"] = "awaiting_identifier"
        state["last_prompt"] = "Ù„ÙØªØ­ Ø´ÙƒÙˆÙ‰ Ø¨Ø´ÙƒÙ„ ØµØ­ÙŠØ­ØŒ Ø²ÙˆÙ‘Ø¯Ù†ÙŠ Ø¨Ø±Ù‚Ù… Ø§Ù„Ø·Ù„Ø¨ Ø£Ùˆ ØªØ§Ø±ÙŠØ® Ø§Ù„Ø²ÙŠØ§Ø±Ø©."
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
            state["last_prompt"] = "Ø¹Ø´Ø§Ù† Ø£ØªØ­Ù‚Ù‚ Ù„Ùƒ Ù…Ù† Ø§Ù„Ù…ÙˆÙ‚Ø¹ Ø¨Ø§Ù„Ø¶Ø¨Ø·ØŒ Ø®Ø¨Ø±Ù†ÙŠ Ø¹Ù† Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© Ø§Ù„Ù„ÙŠ Ø£Ù†Øª ÙÙŠÙ‡Ø§ ÙˆØ¨Ø¹Ø±Ø¶ Ù„Ùƒ Ø§Ù„ÙØ±ÙˆØ¹ Ø§Ù„Ù…ØªÙˆÙØ±Ø© ÙˆØªØ®ØªØ§Ø± Ø§Ù„Ø£Ù‚Ø±Ø¨ Ù„Ùƒ."
            return state["last_prompt"], state, False
        state["step"] = "awaiting_city"
        state["last_prompt"] = "Ø¹Ø´Ø§Ù† Ø£Ø­Ø¯Ø¯ Ø£Ù‚Ø±Ø¨ ÙØ±Ø¹ØŒ Ø§ÙƒØªØ¨ Ø§Ø³Ù… Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© (Ù…Ø«Ø§Ù„: Ø§Ù„Ø±ÙŠØ§Ø¶ / Ø¬Ø¯Ø©) Ø£Ùˆ Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© + Ø§Ù„Ø­ÙŠ."
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
            state["last_prompt"] = "Ø­Ø¯Ø¯ÙŠ Ø±Ù‚Ù… Ø§Ù„ÙØ±Ø¹ Ø§Ù„Ø£Ù‚Ø±Ø¨ Ù„Ùƒ Ù„Ø£Ø²ÙˆÙ‘Ø¯Ùƒ Ø¨Ø±Ø§Ø¨Ø· Ø§Ù„Ù…ÙˆÙ‚Ø¹."
            return _format_branch_names_only(city, district_hits), state, False
        state["slots"] = {"city": city, "district": district}
        state["step"] = "awaiting_branch_number"
        state["active_flow"] = "branch_flow"
        state["last_city"] = city
        state["last_options"] = city_branches
        state["last_prompt"] = "Ø­Ø¯Ø¯ÙŠ Ø±Ù‚Ù… Ø§Ù„ÙØ±Ø¹ Ø§Ù„Ø£Ù‚Ø±Ø¨ Ù„Ùƒ Ù„Ø£Ø²ÙˆÙ‘Ø¯Ùƒ Ø¨Ø±Ø§Ø¨Ø· Ø§Ù„Ù…ÙˆÙ‚Ø¹."
        msg = (
            f"Ù…Ø§ Ù„Ù‚ÙŠÙ†Ø§ Ø§Ù„Ø­ÙŠ Ø§Ù„Ù…Ø°ÙƒÙˆØ± Ø¨Ø§Ù„Ø§Ø³Ù… Ø¯Ø§Ø®Ù„ Ù‚Ø§Ø¦Ù…ØªÙ†Ø§ØŒ Ù„ÙƒÙ† Ù‡Ø°Ù‡ ÙØ±ÙˆØ¹ {city} Ø§Ù„Ù…ØªÙˆÙØ±Ø©:\n"
            + "\n"
            + _format_branch_names_only(city, city_branches)
        )
        return msg, state, False

    state["slots"] = {"city": city}
    state["step"] = "awaiting_branch_number"
    state["active_flow"] = "branch_flow"
    state["last_city"] = city
    state["last_options"] = city_branches
    state["last_prompt"] = "Ø­Ø¯Ø¯ÙŠ Ø±Ù‚Ù… Ø§Ù„ÙØ±Ø¹ Ø§Ù„Ø£Ù‚Ø±Ø¨ Ù„Ùƒ Ù„Ø£Ø²ÙˆÙ‘Ø¯Ùƒ Ø¨Ø±Ø§Ø¨Ø· Ø§Ù„Ù…ÙˆÙ‚Ø¹."
    return _format_branch_names_only(city, city_branches), state, False


def _run_pricing_flow(message: str, state: dict) -> tuple[str, dict, bool]:
    step = state.get("step") or "awaiting_test_name"
    slots = state.get("slots") or {}

    if step == "awaiting_test_name":
        test_name = _extract_test_name_for_pricing(message)
        if not test_name:
            state["last_prompt"] = "ÙˆØ´ Ø§Ø³Ù… Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ø§Ù„Ù„ÙŠ ØªØ¨ØºÙ‰ Ø³Ø¹Ø±Ù‡ØŸ"
            return state["last_prompt"], state, False
        slots["test_name"] = test_name
        state["slots"] = slots
        state["step"] = "awaiting_city"
        state["last_prompt"] = "Ø§ÙƒØªØ¨ Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© Ø¥Ø°Ø§ ØªØ­Ø¨ (Ù…Ø«Ø§Ù„: Ø§Ù„Ø±ÙŠØ§Ø¶)ØŒ Ø£Ùˆ Ø§ÙƒØªØ¨: Ø¨Ø¯ÙˆÙ† Ù…Ø¯ÙŠÙ†Ø©."
        return state["last_prompt"], state, False

    if step == "awaiting_city":
        city, _district = _extract_city_and_district(message)
        if city and _match_city_in_catalog(city):
            slots["city"] = _match_city_in_catalog(city)
        reply = (
            f"Ø¨Ø§Ù„Ù†Ø³Ø¨Ø© Ù„Ø³Ø¹Ø± {slots.get('test_name', 'Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ø§Ù„Ù…Ø·Ù„ÙˆØ¨')}"
            + (f" ÙÙŠ {slots['city']}" if slots.get("city") else "")
            + f"ØŒ Ù„Ù„Ø§Ø³ØªÙØ³Ø§Ø± Ø§Ù„Ø¯Ù‚ÙŠÙ‚ ØªÙ‚Ø¯Ø± ØªØªÙˆØ§ØµÙ„ Ù…Ø¹ Ø®Ø¯Ù…Ø© Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡ Ø¹Ù„Ù‰ {_branch_phone()}."
        )
        return reply, _complete_flow(state), True

    state["last_prompt"] = "ÙˆØ´ Ø§Ø³Ù… Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ø§Ù„Ù„ÙŠ ØªØ¨ØºÙ‰ Ø³Ø¹Ø±Ù‡ØŸ"
    state["step"] = "awaiting_test_name"
    return state["last_prompt"], state, False


def _run_result_flow(message: str, state: dict) -> tuple[str, dict, bool]:
    ident = _extract_identifier(message)
    if not ident:
        state["step"] = "awaiting_identifier"
        state["last_prompt"] = _RESULT_FLOW_PROMPT
        return state["last_prompt"], state, False
    reply = f"Ù„Ø®Ø¯Ù…Ø© Ø§Ù„Ù†ØªØ§Ø¦Ø¬ Ø¨Ø´ÙƒÙ„ Ù…Ø¨Ø§Ø´Ø±ØŒ ØªÙ‚Ø¯Ø± ØªØªÙˆØ§ØµÙ„ Ù…Ø¹ Ø®Ø¯Ù…Ø© Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡ Ø¹Ù„Ù‰ {_branch_phone()}."
    return reply, _complete_flow(state), True


def _run_complaint_flow(message: str, state: dict) -> tuple[str, dict, bool]:
    ident = _extract_identifier(message)
    if not ident:
        state["step"] = "awaiting_identifier"
        state["last_prompt"] = "Ù„ÙØªØ­ Ø´ÙƒÙˆÙ‰ Ø¨Ø´ÙƒÙ„ ØµØ­ÙŠØ­ØŒ Ø²ÙˆÙ‘Ø¯Ù†ÙŠ Ø¨Ø±Ù‚Ù… Ø§Ù„Ø·Ù„Ø¨ Ø£Ùˆ ØªØ§Ø±ÙŠØ® Ø§Ù„Ø²ÙŠØ§Ø±Ø©."
        return state["last_prompt"], state, False
    reply = f"ØªÙ… Ø§Ø³ØªÙ„Ø§Ù… Ø·Ù„Ø¨Ùƒ. Ù„Ø¥ÙƒÙ…Ø§Ù„ Ù…Ø¹Ø§Ù„Ø¬Ø© Ø§Ù„Ø´ÙƒÙˆÙ‰ Ø¨Ø³Ø±Ø¹Ø©ØŒ ØªÙˆØ§ØµÙ„ Ù…Ø¹ Ø®Ø¯Ù…Ø© Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡ Ø¹Ù„Ù‰ {_branch_phone()}."
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
        return "ØªÙ… Ø¥Ù„ØºØ§Ø¡ Ø§Ù„Ø¹Ù…Ù„ÙŠØ©. Ù†Ù‚Ø¯Ø± Ù†Ø¨Ø¯Ø£ Ù…Ù† Ø¬Ø¯ÙŠØ¯ØŒ ÙƒÙŠÙ Ø£Ù‚Ø¯Ø± Ø£Ø®Ø¯Ù…ÙƒØŸ"

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
            query_seed = "Ø³Ø§Ø¹Ø§Øª Ø§Ù„Ø¯ÙˆØ§Ù… ÙˆÙ‚Øª Ø§Ù„Ø¯ÙˆØ§Ù… Ù…ØªÙ‰ ØªÙØªØ­ÙˆÙ† Ù…ØªÙ‰ ØªÙ‚ÙÙ„ÙˆÙ† " + question
        elif intent == "contact_support":
            query_seed = "Ø±Ù‚Ù… Ø§Ù„ØªÙˆØ§ØµÙ„ Ø®Ø¯Ù…Ø© Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡ ÙˆØ§ØªØ³Ø§Ø¨ Ø§ÙŠÙ…ÙŠÙ„ " + question
        elif intent == "branches_locations":
            query_seed = "ÙØ±ÙˆØ¹ Ø§Ù„Ù…ÙˆÙ‚Ø¹ Ø§Ù„Ø¹Ù†ÙˆØ§Ù† Ø§Ù„Ù…Ø¯ÙŠÙ†Ø© " + question
        elif intent == "home_visit":
            query_seed = "Ø²ÙŠØ§Ø±Ø© Ù…Ù†Ø²Ù„ÙŠØ© Ø³Ø­Ø¨ Ù…Ù†Ø²Ù„ÙŠ " + question
        elif intent == "payment_insurance_privacy":
            query_seed = "Ø§Ù„Ø¯ÙØ¹ Ø§Ù„ØªØ£Ù…ÙŠÙ† Ø§Ù„Ø®ØµÙˆØµÙŠØ© Ø§Ù„Ø¨ÙŠØ§Ù†Ø§Øª " + question
        results = kb.search_faqs(query_seed, min_score=45, max_results=1)
        if results:
            return sanitize_for_ui(results[0]["faq"].get("answer") or "")
    except Exception as exc:
        logger.warning("KB FAQ direct route failed: %s", exc)
    return None


def _symptom_guidance(question: str) -> str:
    n = normalize_for_matching(question or "")
    picks = ["CBC", "Ferritin", "TSH", "Vitamin D (25 OH-Vit D -Total)"]
    if "Ø³ÙƒØ±" in n or "Ø¯ÙˆØ®Ù‡" in n:
        picks.append("HbA1c")
    unique = []
    for p in picks:
        if p not in unique:
            unique.append(p)
    return (
        "Ø­Ø³Ø¨ Ø§Ù„Ø£Ø¹Ø±Ø§Ø¶ Ø§Ù„Ù…Ø°ÙƒÙˆØ±Ø© ØºØ§Ù„Ø¨Ø§Ù‹ ÙŠØ¨Ø¯Ø£ Ø§Ù„Ø·Ø¨ÙŠØ¨ Ø¨ÙØ­ÙˆØµØ§Øª:\n"
        + "\n".join([f"- {p}" for p in unique[:5]])
        + "\n\nÙ‡Ø°Ø§ ØªÙˆØ¬ÙŠÙ‡ ØªØ«Ù‚ÙŠÙÙŠ ÙÙ‚Ø·ØŒ ÙˆØ§Ù„ØªØ´Ø®ÙŠØµ Ø§Ù„Ù†Ù‡Ø§Ø¦ÙŠ ÙŠÙƒÙˆÙ† Ø¹Ù†Ø¯ Ø§Ù„Ø·Ø¨ÙŠØ¨."
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
        tafaddal = tone("ØªÙØ¶Ù„", "ØªÙØ¶Ù„ÙŠÙ†", "ØªÙØ¶Ù„")
        tawasal = tone("ØªÙˆØ§ØµÙ„", "ØªÙˆØ§ØµÙ„ÙŠ", "ØªÙˆØ§ØµÙ„")
        arsil = tone("Ø§Ø±Ø³Ù„", "Ø§Ø±Ø³Ù„ÙŠ", "Ø§Ø±Ø³Ù„")
        token_map = (
            ("ØªÙØ¶Ù„ÙŠÙ†", tafaddal),
            ("ØªÙØ¶Ù„", tafaddal),
            ("ØªÙˆØ§ØµÙ„ÙŠ", tawasal),
            ("ØªÙˆØ§ØµÙ„", tawasal),
            ("Ø§Ø±Ø³Ù„ÙŠ", arsil),
            ("Ø§Ø±Ø³Ù„", arsil),
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
    expanded_query = expand_query_with_synonyms(question_for_ai) or question_for_ai
    print(
        "PATH=synonyms_expanded",
        {"original": question_for_ai, "expanded": expanded_query[:200]},
    )
    ai_prompt = question_for_ai
    if attachment_content:
        ai_prompt = (
            f"Ø³ÙŠØ§Ù‚ Ù…Ù† Ø§Ù„Ù…Ø±ÙÙ‚ ({attachment_filename or 'Ù…Ù„Ù'}):\n"
            f"{extracted_context}\n\n"
            f"Ø³Ø¤Ø§Ù„ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…: {question_for_ai}"
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

    # ══════════════════════════════════════════════════════════════════════
    # ROUTING LADDER  A → B → C → D → E → F → G → H → I → J
    # Each path returns immediately on match.
    # Legacy route_question() / intent routing / LLM pipeline are bypassed
    # for plain text chat (emergency routing lockdown).
    # ══════════════════════════════════════════════════════════════════════

    # A. GREETING
    if _is_simple_greeting(question_for_ai):
        print("PATH=greeting")
        return _save_assistant_reply(
            "مرحبا، معاكم مختبر وريد الطبية، كيف ممكن أخدمك اليوم؟"
        )

    # B. FAQ – runtime lookup from faq_clean.jsonl wins unconditionally.
    runtime_faq_match = _runtime_faq_lookup(question_for_ai)
    faq_answer = ""
    if runtime_faq_match:
        faq_answer = str(runtime_faq_match.get("answer") or runtime_faq_match.get("a") or "").strip()
    if runtime_faq_match and faq_answer:
        logger.info(
            "faq route matched | route=faq | faq_id=%s | match_method=%s | match_score=%s | matched_q_norm=%s",
            runtime_faq_match.get("id"),
            runtime_faq_match.get("_match_method", "unknown"),
            runtime_faq_match.get("_match_score", "n/a"),
            str(runtime_faq_match.get("_matched_q_norm") or runtime_faq_match.get("q_norm") or "")[:180],
        )
        print("PATH=faq")
        return _save_assistant_reply(faq_answer)

    faq_class_intent = _recognize_faq_class_intent(question_for_ai)
    if faq_class_intent:
        intent_faq_match = _runtime_faq_lookup_by_class_intent(faq_class_intent)
        intent_faq_answer = ""
        if intent_faq_match:
            intent_faq_answer = str(intent_faq_match.get("answer") or "").strip()
        if intent_faq_match and intent_faq_answer:
            logger.info(
                "faq route matched | route=faq | faq_intent=%s | faq_id=%s | match_method=%s | match_score=%s | matched_q_norm=%s",
                faq_class_intent,
                intent_faq_match.get("id"),
                intent_faq_match.get("_match_method", "faq_class_intent"),
                intent_faq_match.get("_match_score", "n/a"),
                str(intent_faq_match.get("_matched_q_norm") or intent_faq_match.get("q_norm") or "")[:180],
            )
            print("PATH=faq")
            return _save_assistant_reply(intent_faq_answer)
        logger.info(
            "faq route fallback | route=faq_safe | faq_intent=%s | query='%s'",
            faq_class_intent,
            question_for_ai[:120],
        )
        print("PATH=faq_safe")
        return _save_assistant_reply(_safe_faq_class_fallback_reply(faq_class_intent))

    # C. PRICE – fixed contact message (emergency lockdown, all price intents unified).
    price_query_norm = normalize_text_ar(question_for_ai)
    is_price_query = _is_general_price_query(question_for_ai) or any(
        token in price_query_norm for token in ("سعر", "اسعار", "أسعار", "price", "cost")
    )
    if is_price_query:
        print("PATH=price")
        return _save_assistant_reply(
            "للاستفسار عن الأسعار يرجى التواصل مع الفريق على الرقم: 920003694"
        )

    # Lightweight flags for strict routing steps D-H.
    preparation_priority = _detect_preparation_priority(question_for_ai, expanded_query)
    test_related_for_rag = is_test_related_question(question_for_ai) or preparation_priority
    symptoms_query = _is_symptoms_query(question_for_ai)
    user_asked_home_visit = _user_explicitly_asked_home_visit(question_for_ai)

    # Light-intent classification used only to gate deterministic branch routing.
    light_intent, light_intent_meta = _classify_light_intent(expanded_query)
    logger.info(
        "light intent classification | intent=%s | meta=%s",
        light_intent,
        light_intent_meta,
    )

    # D. BRANCHES
    branch_bypass_reply = _branch_lookup_bypass_reply(expanded_query, conversation_id, light_intent)
    if branch_bypass_reply:
        print("PATH=branches")
        return _save_assistant_reply(branch_bypass_reply)

    # E. PACKAGES
    package_bypass_reply = _package_lookup_bypass_reply(expanded_query, conversation_id)
    if package_bypass_reply:
        print("PATH=packages")
        return _save_assistant_reply(package_bypass_reply)

    # F. TEST_DEFINITION
    if test_related_for_rag and not preparation_priority and not symptoms_query:
        rag_reply = _runtime_tests_rag_reply(
            question=question_for_ai,
            expanded_query=expanded_query,
            history=history,
        )
        if rag_reply:
            print("PATH=test_definition")
            return _save_assistant_reply(rag_reply)

    # G. TEST_PREPARATION
    if preparation_priority:
        prep_button_reply = _resolve_preparation_button_reply(question_for_ai)
        if prep_button_reply:
            print("PATH=test_preparation")
            return _save_assistant_reply(prep_button_reply)
        prep_rag_reply = _runtime_tests_rag_reply(
            question=question_for_ai,
            expanded_query=expanded_query,
            history=history,
        )
        if prep_rag_reply:
            print("PATH=test_preparation")
            return _save_assistant_reply(prep_rag_reply)

    # H. TEST_SYMPTOMS
    symptoms_bypass_reply = _symptoms_rag_bypass_reply(question_for_ai)
    if symptoms_bypass_reply:
        print("PATH=test_symptoms")
        return _save_assistant_reply(symptoms_bypass_reply)

    # I. SITE_FALLBACK – general website info only (site_knowledge_chunks_hard.jsonl).
    site_context = get_site_fallback_context(question_for_ai, max_chunks=3)
    if site_context and site_context.strip():
        print("PATH=site_fallback")
        return _save_assistant_reply("حسب معلومات الموقع:\n" + site_context)

    # J. CLARIFY
    # Nothing in A-I matched. For plain text / voice, stop here and clarify.
    # Bypassed:  route_question(), legacy intent routing (branches_locations /
    #            working_hours / symptom_based_suggestion etc.), and the generic
    #            RAG+LLM pipeline.  These were the source of repeated wrong answers.
    is_pdf_attachment = bool(
        attachment_content and (attachment_filename or "").lower().endswith(".pdf")
    )
    if not is_pdf_attachment:
        logger.warning(
            "ROUTING_LOCKDOWN | no route A-J matched | bypassing legacy routing | q='%s'",
            question_for_ai[:120],
        )
        print("PATH=clarify")
        return _save_assistant_reply(safe_clarify_message(WAREED_CUSTOMER_SERVICE_PHONE, gender))

    # ── PDF attachment path only beyond this point ──────────────────────────
    # route_question() and legacy intent routing are NOT called.
    route_type = "pdf_attachment"
    intent_payload = classify_intent(question_for_ai)
    intent = intent_payload.get("intent", "services_overview")
    slots = intent_payload.get("slots", {}) or {}
    detected_tokens = slots.get("detected_tokens") or []

    # PDF report summarizer (works even if LLM is unavailable).
    wants_report_explain = (
        intent in {"report_explanation", "test_definition"}
        or is_report_explanation_request(question_for_ai)
    )
    if wants_report_explain and extracted_context:
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

    # If KB hit exists but model produced generic miss, retry with explicit grounding.
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
