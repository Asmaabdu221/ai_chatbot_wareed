"""Central runtime router for staged assistant rollout.

Current stage:
- Rebuild mode
- FAQ-only mode

Future stages:
- prices
- branches
- packages
- tests
- site fallback
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from app.services.runtime.branches_resolver import resolve_branches_query
from app.services.runtime.entity_memory import load_entity_memory
from app.services.runtime.branches_semantic_intent import (
    detect_branch_semantic_intent,
    is_confident_branch_intent,
)
from app.services.runtime.faq_resolver import resolve_faq
from app.services.runtime.ollama_intent_classifier import (
    classify_intent_label,
    format_final_response_with_ollama,
)
from app.services.runtime.packages_business_engine import handle_packages_business_query
from app.services.runtime.packages_resolver import resolve_packages_query
from app.services.runtime.results_engine import interpret_result_query
from app.services.runtime.results_query_detector import analyze_result_query, looks_like_result_query
from app.services.runtime.response_formatter import format_runtime_answer
from app.services.runtime.selection_state import load_selection_state
from app.services.runtime.runtime_fallbacks import (
    get_faq_no_match_message,
    get_out_of_scope_message,
    get_rebuild_mode_message,
)
from app.services.runtime.symptoms_engine import handle_symptoms_query
from app.services.runtime.tests_business_engine import resolve_tests_business_query
from app.services.runtime.tests_disambiguation import resolve_tests_disambiguation_selection
from app.services.runtime.tests_resolver import resolve_tests_query
from app.services.runtime.text_normalizer import normalize_arabic

logger = logging.getLogger(__name__)
ENABLE_BRANCHES_RUNTIME_AFTER_FAQ = True
ENABLE_PACKAGES_RUNTIME_AFTER_BRANCHES = True
ENABLE_TESTS_RUNTIME_AFTER_PACKAGES = True
_BUSINESS_TEST_QUERY_TYPES = {
    "test_price_query",
    "test_fasting_query",
    "test_preparation_query",
    "test_symptoms_query",
    "test_complementary_query",
    "test_alternative_query",
    "test_sample_type_query",
}


def _safe_str(value: Any) -> str:
    """Convert any value to a safely stripped string."""
    return str(value or "").strip()


def _ensure_package_label(label: str) -> str:
    value = _safe_str(label)
    if not value:
        return ""
    n = normalize_arabic(value)
    if "باقه" in n or "باقة" in value:
        return value
    return f"باقة {value}"


def _resolve_reference_rewrite(
    text: str,
    *,
    conversation_id: UUID | None,
) -> str | None:
    if conversation_id is None:
        return None

    query = _safe_str(text)
    query_norm = normalize_arabic(query)
    if not query_norm:
        return None

    memory = load_entity_memory(conversation_id)
    last_intent = _safe_str(memory.get("last_intent"))
    last_intent_has_entity = bool(memory.get("last_intent_has_entity"))
    last_test = _safe_str((memory.get("last_test") or {}).get("label"))
    last_package = _safe_str((memory.get("last_package") or {}).get("label"))
    last_branch = _safe_str((memory.get("last_branch") or {}).get("label"))

    price_refs = tuple(
        normalize_arabic(v)
        for v in (
            "سعرها",
            "سعره",
            "كم سعرها",
            "كم سعره",
            "بكم",
            "كم تكلف",
            "كم تكلفه",
            "تكلف كم",
        )
    )
    package_include_refs = tuple(
        normalize_arabic(v)
        for v in (
            "وش تشمل",
            "ايش تشمل",
            "ماذا تشمل",
            "وش فيها",
            "ايش فيها",
            "تشمل ايش",
            "فيها ايش",
        )
    )
    branch_location_refs = tuple(
        normalize_arabic(v)
        for v in (
            "وينه",
            "وينها",
            "موقعه",
            "موقعها",
            "وين موقعه",
            "وين موقعها",
            "وين الموقع",
        )
    )
    test_fasting_refs = tuple(
        normalize_arabic(v)
        for v in (
            "هل يحتاج صيام",
            "يحتاج صيام",
            "هل لازم صيام",
            "لازم صيام",
            "هل يبيله صيام",
            "يبيله صيام",
            "يحتاج صيام ولا لا",
            "صيام ولا لا",
        )
    )

    if not last_intent or not last_intent_has_entity:
        return None

    if query_norm in price_refs:
        if last_intent == "package" and last_package:
            return f"كم سعر {_ensure_package_label(last_package)}"
        if last_intent == "test" and last_test:
            return f"كم سعر تحليل {last_test}"
        return None

    if query_norm in package_include_refs:
        if last_intent == "package" and last_package:
            return f"ماذا تشمل {_ensure_package_label(last_package)}"
        return None

    if query_norm in branch_location_refs:
        if last_intent == "branch" and last_branch:
            return f"ما موقع {last_branch}"
        return None

    if query_norm in test_fasting_refs:
        if last_intent == "test" and last_test:
            return f"هل {last_test} يحتاج صيام"
        return None

    return None


def _is_numeric_selection_query(text: str) -> bool:
    value = _safe_str(text).translate(
        str.maketrans({"٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9"})
    )
    return bool(re.fullmatch(r"\d{1,2}", value))


_CONTEXT_DETAIL_FOLLOWUPS = (
    "نعم",
    "ايوا",
    "ايوه",
    "طيب",
    "تمام",
    "اوكي",
    "كمل",
    "ok",
    "اشرح",
    "شرح",
    "وضح",
    "فصّل",
    "فصل",
    "التفاصيل",
    "تفاصيل",
    "وش فيها",
    "ايش فيها",
    "وش تشمل",
    "ايش تشمل",
)
_CONTEXT_PRICE_FOLLOWUPS = (
    "السعر",
    "سعر",
    "بكم",
    "كم سعرها",
    "كم سعره",
)
_CONTEXT_BRANCH_FOLLOWUPS = (
    "وينه",
    "وين موقعه",
    "الموقع",
    "لوكيشن",
    "location",
    "الرياض",
    "جده",
    "جدة",
    "مكه",
    "مكة",
    "الشرقيه",
    "الشرقية",
    "شمال الرياض",
    "شرق الرياض",
    "غرب الرياض",
    "جنوب الرياض",
)

_EXPLICIT_BRANCH_ACTION_ANCHORS = (
    "اقرب فرع",
    "الاقرب فرع",
    "وين الفرع",
    "وين اقرب فرع",
    "موقع الفرع",
    "عنوان الفرع",
    "لوكيشن",
    "location",
)
_LOCATION_MODIFIER_HINTS = (
    "في الرياض",
    "بالرياض",
    "في جده",
    "بجده",
    "في جدة",
    "بجدة",
    "في مكة",
    "بمكة",
    "في مكه",
    "بمكه",
    "في المدينة",
    "بالمدينة",
    "شمال الرياض",
    "شرق الرياض",
    "غرب الرياض",
    "جنوب الرياض",
)
_MIXED_TEST_CUES = (
    "تحليل",
    "تحاليل",
    "فحص",
    "اختبار",
    "tsh",
    "hba1c",
    "vitamin",
    "vit d",
    "cbc",
    "ferritin",
    "حديد",
    "فيتامين",
)
_MIXED_PACKAGE_CUES = (
    "باقه",
    "باقة",
    "باقات",
    "package",
    "افضل باقه",
    "أفضل باقة",
)


_GREETING_KEYWORDS = (
    "\u0645\u0631\u062d\u0628\u0627",
    "\u0627\u0647\u0644\u0627",
    "\u0623\u0647\u0644\u0627",
    "\u0627\u0644\u0633\u0644\u0627\u0645 \u0639\u0644\u064a\u0643\u0645",
    "\u0633\u0644\u0627\u0645 \u0639\u0644\u064a\u0643\u0645",
    "hi",
    "hello",
    "hey",
)
_GENERAL_CONVERSATION_KEYWORDS = (
    "\u0634\u0643\u0631\u0627",
    "\u064a\u0639\u0637\u064a\u0643 \u0627\u0644\u0639\u0627\u0641\u064a\u0629",
    "\u062a\u0645\u0627\u0645",
    "\u0627\u0648\u0643\u064a",
    "\u0627\u0648\u0643\u064a\u0647",
    "\u0627\u0648\u0643",
    "ok",
    "thanks",
    "thank you",
    "\u0645\u0627 \u0641\u0647\u0645\u062a",
    "\u0645\u0648 \u0641\u0627\u0647\u0645",
    "\u0645\u0634 \u0641\u0627\u0647\u0645",
    "\u063a\u064a\u0631 \u0648\u0627\u0636\u062d",
)
_GENERAL_LAYER_DOMAIN_BLOCKERS = (
    "\u0641\u0631\u0639",
    "\u0641\u0631\u0648\u0639",
    "\u0645\u0648\u0642\u0639",
    "\u062d\u064a",
    "\u0628\u0627\u0642\u0647",
    "\u0628\u0627\u0642\u0629",
    "\u0628\u0627\u0642\u0627\u062a",
    "package",
    "\u062a\u062d\u0644\u064a\u0644",
    "\u062a\u062d\u0627\u0644\u064a\u0644",
    "\u0641\u062d\u0635",
    "\u0627\u062e\u062a\u0628\u0627\u0631",
    "hba1c",
    "tsh",
    "cbc",
    "ferritin",
    "\u0627\u0639\u0631\u0627\u0636",
    "\u0623\u0639\u0631\u0627\u0636",
    "\u0646\u062a\u064a\u062c\u0629",
    "\u0646\u062a\u064a\u062c\u062a\u064a",
    "\u0646\u062a\u0627\u0626\u062c",
    "\u0646\u062a\u0627\u064a\u062c",
)


def _has_any_domain_blocker(text: str) -> bool:
    q = normalize_arabic(_safe_str(text)).lower()
    if not q:
        return False
    for blocker in _GENERAL_LAYER_DOMAIN_BLOCKERS:
        b = normalize_arabic(_safe_str(blocker)).lower()
        if not b:
            continue
        if q == b or _contains_boundary_phrase(q, b) or b in q:
            return True
    return False


def _is_short_general_layer_candidate(text: str) -> bool:
    q = normalize_arabic(_safe_str(text)).lower()
    if not q:
        return False
    tokens = [w for w in q.split() if w]
    if not (1 <= len(tokens) <= 3):
        return False
    return not _has_any_domain_blocker(q)


def _is_greeting_query(text: str) -> bool:
    if not _is_short_general_layer_candidate(text):
        return False
    q = normalize_arabic(_safe_str(text)).lower()
    for keyword in _GREETING_KEYWORDS:
        k = normalize_arabic(_safe_str(keyword)).lower()
        if not k:
            continue
        if q == k or _contains_boundary_phrase(q, k):
            return True
    return False


def _is_general_conversation_query(text: str) -> bool:
    if not _is_short_general_layer_candidate(text):
        return False
    q = normalize_arabic(_safe_str(text)).lower()
    for keyword in _GENERAL_CONVERSATION_KEYWORDS:
        k = normalize_arabic(_safe_str(keyword)).lower()
        if not k:
            continue
        if q == k or _contains_boundary_phrase(q, k):
            return True
    return False


def _is_context_followup_query(text: str, triggers: tuple[str, ...]) -> bool:
    q = normalize_arabic(_safe_str(text))
    if not q:
        return False
    words = [w for w in q.split() if w]
    if not (1 <= len(words) <= 4):
        return False
    normalized_triggers = [normalize_arabic(v) for v in triggers if normalize_arabic(v)]
    legacy = any(q == t or t in q for t in normalized_triggers if t)
    scores = _detector_score(
        q,
        hints=tuple(normalized_triggers),
        strong_keywords=tuple(normalized_triggers),
        ambiguity_terms=("ايش", "وش", "نعم", "ok"),
    )
    return _detector_pick(
        "context_followup",
        q,
        scores,
        min_score=1.75,
        legacy_match=legacy,
    )


def _has_explicit_branch_action_anchor(text: str) -> bool:
    n = normalize_arabic(_safe_str(text))
    if not n:
        return False
    return any(_contains_boundary_phrase(n, normalize_arabic(anchor)) for anchor in _EXPLICIT_BRANCH_ACTION_ANCHORS)


def _has_location_modifier(text: str) -> bool:
    n = normalize_arabic(_safe_str(text))
    if not n:
        return False
    if any(_contains_boundary_phrase(n, normalize_arabic(h)) for h in _LOCATION_MODIFIER_HINTS):
        return True
    # Conservative single-token city forms.
    return n in {"الرياض", "جده", "جدة", "مكة", "مكه", "المدينة"}


def _has_test_intent_cues(text: str) -> bool:
    n = normalize_arabic(_safe_str(text))
    if not n:
        return False
    return any(_contains_boundary_phrase(n, normalize_arabic(c)) or normalize_arabic(c) in n for c in _MIXED_TEST_CUES)


def _has_package_intent_cues(text: str) -> bool:
    n = normalize_arabic(_safe_str(text))
    if not n:
        return False
    return any(_contains_boundary_phrase(n, normalize_arabic(c)) or normalize_arabic(c) in n for c in _MIXED_PACKAGE_CUES)


def _is_short_branch_locality_followup(
    text: str,
    *,
    is_tests_like: bool,
    is_package_like: bool,
    is_results_like: bool,
) -> bool:
    q = normalize_arabic(_safe_str(text))
    if not q:
        return False
    if is_tests_like or is_package_like or is_results_like:
        return False
    words = [w for w in q.split() if w]
    if not (1 <= len(words) <= 3):
        return False
    # Keep heuristic conservative: only Arabic locality-style short follow-ups.
    if re.search(r"[a-zA-Z0-9]", q):
        return False
    blocked_tokens = {
        "نعم", "ايوا", "ايوه", "تمام", "اوكي", "ok",
        "وش", "ايش", "ما", "متى", "كيف", "ليه",
        "سعر", "كم", "تحليل", "باقة", "نتيجة",
    }
    if any(token in blocked_tokens for token in words):
        return False
    return True


def _parse_numeric_selection(text: str) -> int | None:
    value = _safe_str(text).translate(
        str.maketrans({"٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9"})
    )
    if not re.fullmatch(r"\d{1,2}", value):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _detector_tokens(text: str) -> list[str]:
    n = normalize_arabic(_safe_str(text))
    if not n:
        return []
    return [t for t in re.split(r"\s+", n) if t]


def _contains_boundary_phrase(text_norm: str, phrase_norm: str) -> bool:
    if not text_norm or not phrase_norm:
        return False
    if text_norm == phrase_norm:
        return True
    return f" {phrase_norm} " in f" {text_norm} "


def _detector_score(
    text_norm: str,
    *,
    hints: tuple[str, ...],
    strong_keywords: tuple[str, ...] = (),
    blockers: tuple[str, ...] = (),
    ambiguity_terms: tuple[str, ...] = (),
) -> dict[str, float]:
    tokens = _detector_tokens(text_norm)
    token_set = set(tokens)
    score = 0.0
    exact_hits = 0.0
    boundary_hits = 0.0
    overlap_hits = 0.0
    strong_hits = 0.0
    blocker_hits = 0.0
    ambiguity_hits = 0.0

    for hint in hints:
        h = normalize_arabic(_safe_str(hint))
        if not h:
            continue
        if text_norm == h:
            score += 3.0
            exact_hits += 1.0
        elif _contains_boundary_phrase(text_norm, h):
            score += 2.0
            boundary_hits += 1.0
        elif h in text_norm:
            score += 1.0

        hint_tokens = [t for t in re.split(r"\s+", h) if t]
        if hint_tokens:
            overlap = len(token_set & set(hint_tokens))
            if overlap == len(hint_tokens):
                score += 1.0
                overlap_hits += 1.0
            elif overlap > 0 and len(hint_tokens) > 1:
                score += 0.5
                overlap_hits += 0.5

    for keyword in strong_keywords:
        k = normalize_arabic(_safe_str(keyword))
        if not k:
            continue
        if _contains_boundary_phrase(text_norm, k) or k in token_set:
            score += 1.25
            strong_hits += 1.0

    for blocker in blockers:
        b = normalize_arabic(_safe_str(blocker))
        if not b:
            continue
        if _contains_boundary_phrase(text_norm, b) or b in text_norm:
            score -= 1.75
            blocker_hits += 1.0

    if len(tokens) <= 2 and ambiguity_terms:
        if all(t in ambiguity_terms for t in tokens):
            score -= 1.25
            ambiguity_hits += 1.0

    return {
        "score": score,
        "exact": exact_hits,
        "boundary": boundary_hits,
        "overlap": overlap_hits,
        "strong": strong_hits,
        "blockers": blocker_hits,
        "ambiguity_penalty": ambiguity_hits,
    }


def _detector_pick(
    detector_name: str,
    query_norm: str,
    scores: dict[str, float],
    *,
    min_score: float,
    legacy_match: bool,
) -> bool:
    score = float(scores.get("score", 0.0))
    fallback_reason = ""
    if score >= min_score:
        result = True
    else:
        result = legacy_match
        fallback_reason = "weak_or_ambiguous_score_legacy_substring"
    logger.debug(
        "runtime_router.detector name=%s query=%r score=%.3f scores=%s result=%s fallback_reason=%s",
        detector_name,
        query_norm,
        score,
        scores,
        result,
        fallback_reason,
    )
    return result


def _looks_like_branch_query(text: str) -> bool:
    n = normalize_arabic(text)
    if not n:
        return False
    hints = (
        "فرع",
        "فروع",
        "موقع",
        "حي",
        "اقرب",
        "العنوان",
        "في الرياض",
        "بالرياض",
        "في جدة",
        "بجدة",
        "في مكة",
        "بمكة",
        "في مكه",
        "بمكه",
    )
    legacy = any(h in n for h in hints)
    blockers = (
        "باقه",
        "باقات",
        "package",
        "well dna",
        "nifty",
        "genetic package",
        "genetic_test",
        "تحليل",
        "تحاليل",
        "فحص",
        "اختبار",
        "hba1c",
        "tsh",
        "nipt",
    )
    scores = _detector_score(
        n,
        hints=hints,
        strong_keywords=("فرع", "فروع", "موقع", "العنوان", "location"),
        blockers=blockers,
        ambiguity_terms=("فرع", "موقع", "حي"),
    )
    score = float(scores.get("score", 0.0))
    if score >= 2.25:
        logger.debug(
            "runtime_router.detector name=%s query=%r score=%.3f scores=%s result=%s fallback_reason=%s",
            "branch_like",
            n,
            score,
            scores,
            True,
            "",
        )
        return True

    blockers_seen = [b for b in blockers if b and (_contains_boundary_phrase(n, b) or b in n)]
    has_strong_anchor = bool(
        float(scores.get("strong", 0.0)) > 0.0
        or float(scores.get("boundary", 0.0)) > 0.0
        or float(scores.get("exact", 0.0)) > 0.0
    )
    allow_legacy_fallback = bool(legacy and has_strong_anchor and not blockers_seen)

    logger.debug(
        "runtime_router.branch_detector weak-score fallback | query=%r | score=%.3f | legacy=%s | anchor_hit=%s | blockers_seen=%s | fallback_allowed=%s",
        n,
        score,
        legacy,
        has_strong_anchor,
        blockers_seen,
        allow_legacy_fallback,
    )
    logger.debug(
        "runtime_router.detector name=%s query=%r score=%.3f scores=%s result=%s fallback_reason=%s",
        "branch_like",
        n,
        score,
        scores,
        allow_legacy_fallback,
        "weak_score_legacy_allowed" if allow_legacy_fallback else "weak_score_legacy_blocked",
    )
    return allow_legacy_fallback


def _looks_like_package_query(text: str) -> bool:
    n = normalize_arabic(text)
    if not n:
        return False
    if _looks_like_branch_query(n):
        return False

    strong_tokens = ("باقه", "باقات", "package")
    genetic_tokens = ("well dna", "nifty", "genetic package", "genetic_test")
    package_category_tokens = ("جيني", "جينية", "رمضان", "ذاتية", "self collection")
    test_tokens = ("تحليل", "تحاليل")
    price_tokens = ("كم سعر", "بكم", "سعر")

    has_test_word = any(token in n for token in test_tokens)
    has_package_category = any(token in n for token in package_category_tokens)
    has_price_word = any(token in n for token in price_tokens)

    legacy = False
    if any(token in n for token in strong_tokens):
        legacy = True
    if any(token in n for token in genetic_tokens):
        legacy = True
    if has_test_word and has_package_category:
        legacy = True
    if has_price_word and ("باقه" in n or "package" in n):
        legacy = True

    blockers = (
        "فرع",
        "فروع",
        "موقع",
        "العنوان",
        "وينه",
        "وين",
    )
    scores = _detector_score(
        n,
        hints=strong_tokens + genetic_tokens + package_category_tokens,
        strong_keywords=strong_tokens + genetic_tokens + ("جيني", "رمضان"),
        blockers=blockers,
        ambiguity_terms=("باقه", "package", "تحاليل"),
    )
    if has_test_word and has_package_category:
        scores["score"] = float(scores.get("score", 0.0)) + 1.0
    if has_price_word and ("باقه" in n or "package" in n):
        scores["score"] = float(scores.get("score", 0.0)) + 0.75

    return _detector_pick("package_like", n, scores, min_score=2.0, legacy_match=legacy)


def _looks_like_tests_query(text: str) -> bool:
    n = normalize_arabic(text)
    if not n:
        return False
    if _looks_like_branch_query(n) or _looks_like_package_query(n):
        return False
    hints = (
        "تحليل",
        "تحاليل",
        "فحص",
        "اختبار",
        "ana",
        "nipt",
        "hba1c",
        "tsh",
        "فيتامين",
        "حديد",
    )
    legacy = any(token in n for token in hints)
    blockers = (
        "فرع",
        "موقع",
        "العنوان",
        "باقه",
        "باقات",
        "package",
        "well dna",
        "nifty",
        "genetic package",
        "genetic_test",
    )
    scores = _detector_score(
        n,
        hints=hints,
        strong_keywords=("تحليل", "تحاليل", "فحص", "اختبار", "hba1c", "tsh", "nipt"),
        blockers=blockers,
        ambiguity_terms=("تحليل", "فحص", "اختبار"),
    )
    return _detector_pick("tests_like", n, scores, min_score=1.75, legacy_match=legacy)


def _looks_like_symptoms_query(text: str) -> bool:
    n = normalize_arabic(text)
    if not n:
        return False
    hints = (
        "اعراض",
        "أعراض",
        "اعاني",
        "أعاني",
        "عندي",
        "احس",
        "أحس",
        "تعب",
        "ارهاق",
        "إرهاق",
        "دوخه",
        "دوخة",
        "تساقط الشعر",
        "فقر دم",
        "نقص فيتامين",
    )
    norm_hints = tuple(normalize_arabic(token) for token in hints if normalize_arabic(token))
    legacy = any(token in n for token in norm_hints)
    blockers = (
        "فرع",
        "موقع",
        "باقه",
        "باقات",
        "package",
    )
    scores = _detector_score(
        n,
        hints=norm_hints,
        strong_keywords=("اعراض", "أعراض", "اعاني", "أعاني", "تعب", "ارهاق"),
        blockers=blockers,
        ambiguity_terms=("عندي", "احس", "أحس"),
    )
    decision = _detector_pick("symptoms_like", n, scores, min_score=2.0, legacy_match=legacy)
    tokens = [t for t in n.split() if t]
    generic_only_terms = {
        normalize_arabic("\u0639\u0646\u062f\u064a"),
        normalize_arabic("\u0627\u062d\u0633"),
        normalize_arabic("\u0623\u062d\u0633"),
        normalize_arabic("\u0627\u0639\u0631\u0627\u0636"),
        normalize_arabic("\u0623\u0639\u0631\u0627\u0636"),
        normalize_arabic("\u0627\u0639\u0627\u0646\u064a"),
        normalize_arabic("\u0623\u0639\u0627\u0646\u064a"),
    }
    strong_symptom_terms = tuple(
        normalize_arabic(v)
        for v in (
            "\u062a\u0639\u0628",
            "\u0627\u0631\u0647\u0627\u0642",
            "\u062f\u0648\u062e\u0629",
            "\u062a\u0633\u0627\u0642\u0637 \u0627\u0644\u0634\u0639\u0631",
            "\u0635\u062f\u0627\u0639",
            "\u062d\u0645\u0649",
            "\u062d\u0631\u0627\u0631\u0629",
            "\u0643\u062d\u0629",
            "\u0627\u0644\u062a\u0647\u0627\u0628 \u062d\u0644\u0642",
            "\u0627\u0644\u0645 \u0628\u0637\u0646",
            "\u0645\u063a\u0635",
            "\u063a\u062b\u064a\u0627\u0646",
            "\u062e\u0641\u0642\u0627\u0646",
            "\u0641\u0642\u0631 \u062f\u0645",
            "\u0646\u0642\u0635 \u0641\u064a\u062a\u0627\u0645\u064a\u0646",
            "\u062e\u0645\u0648\u0644",
            "\u0636\u0639\u0641 \u0639\u0627\u0645",
        )
        if normalize_arabic(v)
    )
    if tokens and all(t in generic_only_terms for t in tokens):
        logger.debug(
            "runtime_router.detector name=%s query=%r score=%.3f scores=%s result=%s fallback_reason=%s",
            "symptoms_like",
            n,
            float(scores.get("score", 0.0)),
            scores,
            False,
            "generic_first_person_without_symptom_anchor",
        )
        return False
    has_strong_anchor = any(_contains_boundary_phrase(n, term) or term in n for term in strong_symptom_terms)
    if decision and not has_strong_anchor and len(tokens) <= 3:
        logger.debug(
            "runtime_router.detector name=%s query=%r score=%.3f scores=%s result=%s fallback_reason=%s",
            "symptoms_like",
            n,
            float(scores.get("score", 0.0)),
            scores,
            False,
            "weak_symptom_signal_short_query",
        )
        return False
    return decision


def _format_symptoms_suggestions_reply(payload: dict[str, Any]) -> str:
    tests = [str(t).strip() for t in list(payload.get("tests") or []) if str(t).strip()][:3]
    packages = [str(p).strip() for p in list(payload.get("packages") or []) if str(p).strip()][:1]

    if not tests and not packages:
        return "وصف الأعراض بشكل أوضح، وأعطيك أفضل التحاليل المناسبة."

    lines: list[str] = []
    if tests:
        lines.append("بناءً على الأعراض اللي ذكرتها، أفضل 3 تحاليل تبدأ فيها هي:")
        lines.append("")
        for idx, test_name in enumerate(tests, start=1):
            lines.append(f"{idx}. {test_name}")
    else:
        lines.append("ما ظهر لي ترشيح واضح للتحاليل من الرسالة الحالية.")

    if packages:
        lines.append("")
        lines.append(f"وإذا حبيت، فيه باقة مناسبة: {packages[0]}")
    return "\n".join(lines)


def _tests_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(meta or {})
    payload.setdefault("query_type", "test_unknown")
    payload.setdefault("matched_test_id", "")
    payload.setdefault("matched_test_name", "")
    payload.setdefault("preparation_available", None)
    return payload


def _tests_business_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(meta or {})
    query_type = _safe_str(payload.get("query_type"))
    payload["business_query_type"] = query_type
    payload.setdefault("matched_test_id", "")
    payload.setdefault("matched_test_name", "")
    return payload


def _is_supported_tests_business_result(result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict):
        return False
    if not bool(result.get("matched")):
        return False
    meta = result.get("meta") or {}
    query_type = _safe_str(meta.get("query_type"))
    return query_type in _BUSINESS_TEST_QUERY_TYPES


def _build_tests_selection_query(query_type: str, selected_test: str) -> str:
    test_name = _safe_str(selected_test)
    qtype = _safe_str(query_type)
    if not test_name:
        return ""
    if qtype == "test_preparation_query":
        return f"قبل تحليل {test_name}"
    if qtype == "test_fasting_query":
        return f"صيام {test_name}"
    if qtype == "test_complementary_query":
        return f"التحاليل المكملة {test_name}"
    if qtype == "test_alternative_query":
        return f"بديل {test_name}"
    if qtype == "test_sample_type_query":
        return f"نوع عينة {test_name}"
    return test_name


def _resolve_numeric_selection_from_context(
    text: str,
    *,
    conversation_id: UUID | None,
) -> dict[str, Any] | None:
    selection_number = _parse_numeric_selection(text)
    if selection_number is None or selection_number < 1:
        return None

    state = load_selection_state(conversation_id)
    options = list(state.get("last_options") or [])
    selection_type = _safe_str(state.get("last_selection_type"))
    query_type = _safe_str(state.get("query_type"))
    if not options or not selection_type:
        return None

    if selection_number > len(options):
        return {
            "reply": format_runtime_answer(
                f"الاختيار غير صحيح. اختر رقمًا من 1 إلى {len(options)}."
            ),
            "route": "selection_out_of_range",
            "source": "selection_state",
            "matched": True,
            "meta": {
                "query_type": "numeric_selection",
                "selection_type": selection_type,
                "options_count": len(options),
                "selection_number": selection_number,
                "reason": "out_of_range",
            },
        }

    option = options[selection_number - 1] if isinstance(options[selection_number - 1], dict) else {}
    payload = option.get("selection_payload") if isinstance(option, dict) else {}
    label = _safe_str(option.get("label"))

    if selection_type == "branch":
        branches_result = resolve_branches_query(text, conversation_id=conversation_id)
        if bool(branches_result.get("matched")):
            return {
                "reply": format_runtime_answer(_safe_str(branches_result.get("answer"))),
                "route": _safe_str(branches_result.get("route")) or "branches",
                "source": "branches",
                "matched": True,
                "meta": dict(branches_result.get("meta") or {}),
            }
        return {
            "reply": format_runtime_answer("ما قدرت أحدد الفرع من الاختيار الحالي. حاول مرة ثانية."),
            "route": "selection_branch_no_match",
            "source": "selection_state",
            "matched": True,
            "meta": {
                "query_type": "numeric_selection",
                "selection_type": selection_type,
                "selection_number": selection_number,
                "reason": "branch_resolution_failed",
            },
        }

    if selection_type == "test":
        selected_test = _safe_str((payload or {}).get("selected_test")) or label
        selected_query = _build_tests_selection_query(query_type, selected_test)
        if selected_query:
            tests_business_selected = resolve_tests_business_query(
                selected_query,
                conversation_id=conversation_id,
            )
            if _is_supported_tests_business_result(tests_business_selected):
                return {
                    "reply": format_runtime_answer(_safe_str(tests_business_selected.get("answer"))),
                    "route": _safe_str(tests_business_selected.get("route")) or "tests_business",
                    "source": "tests_business",
                    "matched": True,
                    "meta": _tests_business_meta(tests_business_selected.get("meta") or {}),
                }
            tests_selected = resolve_tests_query(
                selected_query,
                conversation_id=conversation_id,
            )
            if bool(tests_selected.get("matched")):
                return {
                    "reply": format_runtime_answer(_safe_str(tests_selected.get("answer"))),
                    "route": _safe_str(tests_selected.get("route")) or "tests",
                    "source": "tests",
                    "matched": True,
                    "meta": _tests_meta(tests_selected.get("meta") or {}),
                }
        return {
            "reply": format_runtime_answer("ما قدرت أحدد التحليل من الاختيار الحالي. حاول مرة ثانية."),
            "route": "selection_test_no_match",
            "source": "selection_state",
            "matched": True,
            "meta": {
                "query_type": "numeric_selection",
                "selection_type": selection_type,
                "selection_number": selection_number,
                "reason": "test_resolution_failed",
            },
        }

    if selection_type == "package":
        package_name = _safe_str((payload or {}).get("package_name")) or label
        package_query = f"باقة {package_name}" if package_name else label
        packages_result = resolve_packages_query(
            package_query,
            conversation_id=conversation_id,
        )
        if bool(packages_result.get("matched")):
            return {
                "reply": format_runtime_answer(_safe_str(packages_result.get("answer"))),
                "route": _safe_str(packages_result.get("route")) or "packages",
                "source": "packages",
                "matched": True,
                "meta": dict(packages_result.get("meta") or {}),
            }
        return {
            "reply": format_runtime_answer("ما قدرت أحدد الباقة من الاختيار الحالي. حاول مرة ثانية."),
            "route": "selection_package_no_match",
            "source": "selection_state",
            "matched": True,
            "meta": {
                "query_type": "numeric_selection",
                "selection_type": selection_type,
                "selection_number": selection_number,
                "reason": "package_resolution_failed",
            },
        }

    return None


def _has_strong_keyword_conflict(user_text: str, intent: str) -> bool:
    text_norm = normalize_arabic(user_text)
    if not text_norm:
        return False
    has_test_signal = any(token in text_norm for token in ("تحليل", "تحاليل", "فحص", "اختبار"))
    has_package_signal = any(token in text_norm for token in ("باقه", "باقة", "باقات", "package"))
    has_branch_signal = any(token in text_norm for token in ("فرع", "فروع", "موقع", "حي", "العنوان"))
    if has_test_signal and intent != "test":
        return True
    if has_package_signal and intent != "package":
        return True
    if has_branch_signal and intent != "branch":
        return True
    return False


def _try_ollama_classifier_fallback(
    user_text: str,
    *,
    conversation_id: UUID | None,
) -> dict[str, Any] | None:
    raw_text = _safe_str(user_text)
    if not raw_text:
        return None

    intent = _safe_str(classify_intent_label(raw_text)).lower()
    logger.debug("ollama fallback used | query=%s | intent=%s", raw_text, intent)

    if intent not in {"test", "package", "branch", "faq", "symptoms", "results", "unknown"}:
        logger.debug("ollama fallback invalid_intent | intent=%s", intent)
        return None
    if intent == "unknown":
        logger.debug("ollama fallback unknown_intent | query=%s", raw_text)
        return None
    if intent in {"test", "package", "branch"} and _has_strong_keyword_conflict(raw_text, intent):
        logger.debug("ollama fallback blocked_by_keyword_conflict | intent=%s | query=%s", intent, raw_text)
        return None

    if intent == "test":
        tests_business_result = resolve_tests_business_query(
            raw_text,
            conversation_id=conversation_id,
        )
        if bool(tests_business_result.get("matched")):
            return {
                "reply": format_runtime_answer(_safe_str(tests_business_result.get("answer"))),
                "route": _safe_str(tests_business_result.get("route")) or "tests_business",
                "source": "tests_business",
                "matched": True,
                "meta": _tests_business_meta(tests_business_result.get("meta") or {}),
            }
        tests_result = resolve_tests_query(raw_text, conversation_id=conversation_id)
        if bool(tests_result.get("matched")):
            return {
                "reply": format_runtime_answer(_safe_str(tests_result.get("answer"))),
                "route": _safe_str(tests_result.get("route")) or "tests",
                "source": "tests",
                "matched": True,
                "meta": _tests_meta(tests_result.get("meta") or {}),
            }
        logger.debug("ollama fallback reroute_failed | intent=test")
        return None

    if intent == "package":
        packages_business_result = handle_packages_business_query(
            raw_text,
            conversation_id=conversation_id,
        )
        if bool(packages_business_result.get("matched")):
            top_package = (list(packages_business_result.get("results") or []) or [{}])[0]
            return {
                "reply": format_runtime_answer(_safe_str(packages_business_result.get("answer"))),
                "route": "packages_business",
                "source": "packages_business",
                "matched": True,
                "meta": {
                    "query_type": _safe_str(packages_business_result.get("query_type")),
                    "results_count": len(list(packages_business_result.get("results") or [])),
                    "matched_package_id": _safe_str((top_package or {}).get("id")),
                    "matched_package_name": _safe_str((top_package or {}).get("package_name")),
                },
            }
        packages_result = resolve_packages_query(raw_text, conversation_id=conversation_id)
        if bool(packages_result.get("matched")):
            return {
                "reply": format_runtime_answer(_safe_str(packages_result.get("answer"))),
                "route": _safe_str(packages_result.get("route")) or "packages",
                "source": "packages",
                "matched": True,
                "meta": dict(packages_result.get("meta") or {}),
            }
        logger.debug("ollama fallback reroute_failed | intent=package")
        return None

    if intent == "branch":
        branches_result = resolve_branches_query(raw_text, conversation_id=conversation_id)
        if bool(branches_result.get("matched")):
            return {
                "reply": format_runtime_answer(_safe_str(branches_result.get("answer"))),
                "route": _safe_str(branches_result.get("route")) or "branches",
                "source": "branches",
                "matched": True,
                "meta": dict(branches_result.get("meta") or {}),
            }
        logger.debug("ollama fallback reroute_failed | intent=branch")
        return None

    if intent == "faq":
        faq_result = resolve_faq(raw_text)
        if faq_result:
            return {
                "reply": format_runtime_answer(_safe_str(faq_result.get("answer"))),
                "route": "faq_only",
                "source": "faq",
                "matched": True,
                "meta": {
                    "faq_id": _safe_str(faq_result.get("faq_id")),
                    "question": _safe_str(faq_result.get("question")),
                    "score": float(faq_result.get("score") or 0.0),
                    "margin": float(faq_result.get("margin") or 0.0),
                    "matched_text": _safe_str(faq_result.get("matched_text")),
                    "concepts": list(faq_result.get("concepts") or []),
                },
            }
        logger.debug("ollama fallback reroute_failed | intent=faq")
        return None

    if intent == "symptoms":
        symptoms_result = handle_symptoms_query(raw_text)
        if symptoms_result:
            if _safe_str(symptoms_result.get("type")) == "symptom_clarification":
                return {
                    "reply": format_runtime_answer(
                        _safe_str(symptoms_result.get("answer"))
                        or "وصف العرض الرئيسي بشكل أوضح (مثل: صداع مستمر، حرارة مع كحة، ألم بطن مع غثيان)."
                    ),
                    "route": "symptoms_clarification",
                    "source": "symptoms_engine",
                    "matched": True,
                    "meta": {
                        "query_type": "symptoms_query",
                        "symptoms": list(symptoms_result.get("symptoms") or []),
                        "tests_count": 0,
                        "packages_count": 0,
                        "clarification_needed": True,
                    },
                }
            return {
                "reply": format_runtime_answer(_format_symptoms_suggestions_reply(symptoms_result)),
                "route": "symptoms_suggestions",
                "source": "symptoms_engine",
                "matched": True,
                "meta": {
                    "query_type": "symptoms_query",
                    "symptoms": list(symptoms_result.get("symptoms") or []),
                    "tests_count": len(list(symptoms_result.get("tests") or [])),
                    "packages_count": len(list(symptoms_result.get("packages") or [])),
                },
            }
        logger.debug("ollama fallback reroute_failed | intent=symptoms")
        return None

    if intent == "results":
        result_answer = _safe_str(interpret_result_query(raw_text))
        if result_answer:
            return {
                "reply": format_runtime_answer(result_answer),
                "route": "results_interpretation",
                "source": "results_engine",
                "matched": True,
                "meta": {
                    "query_type": "result_interpretation",
                },
            }
        logger.debug("ollama fallback reroute_failed | intent=results")
        return None

    return None


def _log_final_route_decision(
    result: dict[str, Any] | None,
    *,
    conversation_id: UUID | None,
    path_stage: str,
) -> dict[str, Any]:
    payload = dict(result or {})
    meta = payload.get("meta")
    meta_dict = meta if isinstance(meta, dict) else {}
    logger.debug(
        "runtime_router.final_decision | route=%s | source=%s | matched=%s | conversation_id=%s | path_stage=%s | query_type=%s",
        _safe_str(payload.get("route")),
        _safe_str(payload.get("source")),
        bool(payload.get("matched")),
        _safe_str(conversation_id),
        _safe_str(path_stage),
        _safe_str(meta_dict.get("query_type")),
    )
    return payload


def _should_apply_ollama_final_formatter(result: dict[str, Any]) -> bool:
    route = _safe_str(result.get("route")).lower()
    source = _safe_str(result.get("source")).lower()
    reply = _safe_str(result.get("reply"))
    matched = bool(result.get("matched"))
    if not matched or not reply:
        return False

    eligible_sources = {"packages", "packages_business", "tests", "tests_business", "symptoms_engine"}
    if source not in eligible_sources:
        return False

    # Keep short sensitive test-business answers exactly as deterministic output.
    blocked_exact_routes = {
        "tests_business_fasting",
        "tests_business_preparation",
        "tests_business_sample_type",
        "tests_business_price",
    }
    if route in blocked_exact_routes:
        return False

    blocked_route_tokens = ("no_match", "error", "rebuild", "fallback", "critical")
    if any(token in route for token in blocked_route_tokens):
        return False
    return True


def _apply_ollama_final_formatter_if_needed(result: dict[str, Any]) -> dict[str, Any]:
    payload = dict(result or {})
    if not _should_apply_ollama_final_formatter(payload):
        return payload

    raw_reply = _safe_str(payload.get("reply"))
    formatted_reply = _safe_str(format_final_response_with_ollama(raw_reply))
    if formatted_reply:
        payload["reply"] = formatted_reply
    return payload

def route_runtime_message(
    user_text: str,
    *,
    conversation_id: UUID | None = None,
    system_rebuild_mode: bool = False,
    faq_only_runtime_mode: bool = False,
    last_user_text: str = "",
    last_assistant_text: str = "",
    recent_runtime_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Route one runtime message according to the currently enabled stage.

    Returns a structured payload that always contains:
    - reply
    - route
    - source
    - matched
    - meta
    """
    text = _safe_str(user_text)
    rewritten = _resolve_reference_rewrite(text, conversation_id=conversation_id)
    if rewritten:
        text = rewritten
    def _final(result: dict[str, Any], path_stage: str) -> dict[str, Any]:
        final_result = _apply_ollama_final_formatter_if_needed(result)
        return _log_final_route_decision(
            final_result,
            conversation_id=conversation_id,
            path_stage=path_stage,
        )

    if system_rebuild_mode:
        return _final({
            "reply": format_runtime_answer(get_rebuild_mode_message()),
            "route": "rebuild_mode",
            "source": "runtime_fallback",
            "matched": False,
            "meta": {
                "mode": "system_rebuild",
            },
        }, "system_rebuild_mode")

    if faq_only_runtime_mode:
        if _is_greeting_query(text):
            logger.debug("runtime_router.general_layer matched | type=greeting | q=%s", text)
            return _final({
                "reply": format_runtime_answer(
                    "\u0645\u0631\u062d\u0628\u0627\u060c \u0645\u0639\u0643 \u0645\u0633\u0627\u0639\u062f \u0645\u062e\u062a\u0628\u0631 \u0648\u0631\u064a\u062f. \u062a\u0642\u062f\u0631 \u062a\u0633\u0623\u0644\u0646\u064a \u0639\u0646 \u062a\u062d\u0644\u064a\u0644\u060c \u0628\u0627\u0642\u0629\u060c \u0641\u0631\u0639\u060c \u0623\u0648 \u0646\u062a\u064a\u062c\u0629."
                ),
                "route": "greeting",
                "source": "runtime_fallback",
                "matched": True,
                "meta": {
                    "query_type": "greeting",
                    "mode": "faq_only",
                },
            }, "general_layer_greeting")

        if _is_general_conversation_query(text):
            logger.debug("runtime_router.general_layer matched | type=general_conversation | q=%s", text)
            return _final({
                "reply": format_runtime_answer(
                    "\u062a\u0645\u0627\u0645. \u0627\u0643\u062a\u0628 \u0637\u0644\u0628\u0643 \u0628\u0634\u0643\u0644 \u0645\u0628\u0627\u0634\u0631\u060c \u0645\u062b\u0644: \u062a\u062d\u0644\u064a\u0644\u060c \u0628\u0627\u0642\u0629\u060c \u0641\u0631\u0639\u060c \u0623\u0648 \u0646\u062a\u064a\u062c\u0629."
                ),
                "route": "general_conversation",
                "source": "runtime_fallback",
                "matched": True,
                "meta": {
                    "query_type": "general_conversation",
                    "mode": "faq_only",
                },
            }, "general_layer_conversation")

        # Strong branch guard before FAQ:
        # - numeric selection (1-2 digits) should be branch-first
        # - explicit branch/location/package/tests phrasing should bypass FAQ
        is_numeric = _is_numeric_selection_query(text)
        is_branch_like = _looks_like_branch_query(text)
        is_package_like = _looks_like_package_query(text)
        is_tests_like = _looks_like_tests_query(text)
        is_symptoms_like = _looks_like_symptoms_query(text)
        # Mixed-query arbitration:
        # location is a secondary modifier unless there is explicit branch-action intent.
        query_norm = normalize_arabic(text)
        explicit_branch_action = _has_explicit_branch_action_anchor(query_norm)
        has_location_modifier = _has_location_modifier(query_norm)
        mixed_test_cues = _has_test_intent_cues(query_norm)
        mixed_package_cues = _has_package_intent_cues(query_norm)
        mixed_result_signals = analyze_result_query(text)
        mixed_result_primary = bool(
            mixed_result_signals.get("strong_result_intent")
            and mixed_result_signals.get("has_number")
            and mixed_result_signals.get("has_test_like")
        )
        if (
            not is_numeric
            and is_branch_like
            and has_location_modifier
            and not explicit_branch_action
            and (mixed_test_cues or mixed_package_cues or mixed_result_primary)
        ):
            is_branch_like = False
            if mixed_test_cues:
                is_tests_like = True
            if mixed_package_cues:
                is_package_like = True
            logger.debug(
                "mixed_query arbitration applied | q=%s | location_secondary=true | explicit_branch_action=%s | promote_tests=%s | promote_packages=%s | result_primary=%s",
                text,
                explicit_branch_action,
                mixed_test_cues,
                mixed_package_cues,
                mixed_result_primary,
            )

        if is_numeric:
            selection_result = _resolve_numeric_selection_from_context(
                text,
                conversation_id=conversation_id,
            )
            if selection_result is not None:
                return _final(selection_result, "numeric_selection_context")

        if conversation_id is not None:
            memory = load_entity_memory(conversation_id)
            state = load_selection_state(conversation_id)
            last_intent = _safe_str(memory.get("last_intent"))
            last_test = _safe_str((memory.get("last_test") or {}).get("label"))
            last_package = _safe_str((memory.get("last_package") or {}).get("label"))
            last_branch = _safe_str((memory.get("last_branch") or {}).get("label"))
            has_branch_followup_anchor = _safe_str(state.get("last_selection_type")) == "branch"
            is_detail_followup = _is_context_followup_query(text, _CONTEXT_DETAIL_FOLLOWUPS)
            is_price_followup = _is_context_followup_query(text, _CONTEXT_PRICE_FOLLOWUPS)
            is_branch_followup = _is_context_followup_query(text, _CONTEXT_BRANCH_FOLLOWUPS)
            is_results_like_for_branch_context = looks_like_result_query(text)
            is_branch_locality_followup = _is_short_branch_locality_followup(
                text,
                is_tests_like=is_tests_like,
                is_package_like=is_package_like,
                is_results_like=is_results_like_for_branch_context,
            )

            # Context-first routing for short follow-ups (before fallback paths).
            if (
                last_intent == "package"
                and last_package
                and (is_detail_followup or is_price_followup)
                and not is_tests_like
                and not is_branch_like
            ):
                packages_result = resolve_packages_query(text, conversation_id=conversation_id)
                if bool(packages_result.get("matched")):
                    return _final({
                        "reply": format_runtime_answer(_safe_str(packages_result.get("answer"))),
                        "route": _safe_str(packages_result.get("route")) or "packages",
                        "source": "packages",
                        "matched": True,
                        "meta": dict(packages_result.get("meta") or {}),
                    }, "context_followup_package")
            if (
                last_intent == "test"
                and last_test
                and (is_detail_followup or is_price_followup)
                and not is_package_like
                and not is_branch_like
            ):
                tests_business_result = resolve_tests_business_query(
                    text,
                    conversation_id=conversation_id,
                )
                if _is_supported_tests_business_result(tests_business_result):
                    return _final({
                        "reply": format_runtime_answer(_safe_str(tests_business_result.get("answer"))),
                        "route": _safe_str(tests_business_result.get("route")) or "tests_business",
                        "source": "tests_business",
                        "matched": True,
                        "meta": _tests_business_meta(tests_business_result.get("meta") or {}),
                    }, "context_followup_tests_business")
                tests_result = resolve_tests_query(text, conversation_id=conversation_id)
                if bool(tests_result.get("matched")):
                    return _final({
                        "reply": format_runtime_answer(_safe_str(tests_result.get("answer"))),
                        "route": _safe_str(tests_result.get("route")) or "tests",
                        "source": "tests",
                        "matched": True,
                        "meta": _tests_meta(tests_result.get("meta") or {}),
                    }, "context_followup_tests")
            if (
                (last_intent == "branch" or has_branch_followup_anchor)
                and (last_branch or is_branch_locality_followup or has_branch_followup_anchor)
                and (is_branch_followup or is_branch_locality_followup)
                and not is_package_like
                and not is_tests_like
            ):
                logger.debug(
                    "branch context follow-up activation | q=%s | last_intent=%s | last_branch=%s | selection_anchor=%s | branch_followup=%s | locality_followup=%s",
                    text,
                    last_intent,
                    bool(last_branch),
                    has_branch_followup_anchor,
                    is_branch_followup,
                    is_branch_locality_followup,
                )
                branches_result = resolve_branches_query(text, conversation_id=conversation_id)
                if bool(branches_result.get("matched")):
                    return _final({
                        "reply": format_runtime_answer(_safe_str(branches_result.get("answer"))),
                        "route": _safe_str(branches_result.get("route")) or "branches",
                        "source": "branches",
                        "matched": True,
                        "meta": dict(branches_result.get("meta") or {}),
                    }, "context_followup_branch")

        result_analysis = analyze_result_query(text)
        result_detected = bool(result_analysis.get("decision"))
        strong_result_intent = bool(result_analysis.get("strong_result_intent"))
        has_result_number = bool(result_analysis.get("has_number"))
        has_result_test_token = bool(result_analysis.get("has_test_like"))
        force_results_route = bool(strong_result_intent and has_result_number and has_result_test_token)

        if result_detected:
            if is_tests_like and not force_results_route:
                logger.debug(
                    "results routing blocked by tests-like query | q=%s | result_detected=true | tests_like=true",
                    text,
                )
            elif not is_branch_like and not is_package_like and not is_symptoms_like:
                if is_tests_like and force_results_route:
                    logger.debug(
                        "results routing override applied | q=%s | strong_result_intent=%s | has_number=%s | has_test_token=%s | tests_like=%s",
                        text,
                        strong_result_intent,
                        has_result_number,
                        has_result_test_token,
                        is_tests_like,
                    )
                result_answer = _safe_str(interpret_result_query(text))
                if result_answer:
                    return _final({
                        "reply": format_runtime_answer(result_answer),
                        "route": "results_interpretation",
                        "source": "results_engine",
                        "matched": True,
                        "meta": {
                            "query_type": "result_interpretation",
                        },
                    }, "results_interpretation")

        prefilter_enter = bool(is_numeric or is_branch_like or is_package_like or is_tests_like)
        logger.debug(
            "domains prefilter entry check | q=%s | enter=%s | numeric=%s | branch_like=%s | package_like=%s | tests_like=%s",
            text,
            prefilter_enter,
            is_numeric,
            is_branch_like,
            is_package_like,
            is_tests_like,
        )
        if prefilter_enter:
            if is_numeric or is_branch_like:
                branches_result = resolve_branches_query(text, conversation_id=conversation_id)
                if bool(branches_result.get("matched")):
                    logger.debug(
                        "branches pre-faq guard matched | q=%s | numeric=%s | branch_like=%s | route=%s",
                        text,
                        is_numeric,
                        is_branch_like,
                        _safe_str(branches_result.get("route")),
                    )
                    logger.debug("domains prefilter early return | stage=branches_match")
                    return _final({
                        "reply": format_runtime_answer(_safe_str(branches_result.get("answer"))),
                        "route": _safe_str(branches_result.get("route")) or "branches",
                        "source": "branches",
                        "matched": True,
                        "meta": dict(branches_result.get("meta") or {}),
                    }, "domains_prefilter_branches")
                if is_numeric:
                    selected = resolve_tests_disambiguation_selection(text, conversation_id=conversation_id)
                    if selected:
                        selected_test = _safe_str(selected.get("selected_test"))
                        selected_query_type = _safe_str(selected.get("query_type"))
                        selected_query = _build_tests_selection_query(selected_query_type, selected_test)
                        if selected_query:
                            tests_business_selected = resolve_tests_business_query(
                                selected_query,
                                conversation_id=conversation_id,
                            )
                            if _is_supported_tests_business_result(tests_business_selected):
                                logger.debug("domains prefilter early return | stage=numeric_selection_tests_business")
                                return _final({
                                    "reply": format_runtime_answer(_safe_str(tests_business_selected.get("answer"))),
                                    "route": _safe_str(tests_business_selected.get("route")) or "tests_business",
                                    "source": "tests_business",
                                    "matched": True,
                                    "meta": _tests_business_meta(tests_business_selected.get("meta") or {}),
                                }, "numeric_selection_tests_business")
                            tests_selected = resolve_tests_query(
                                selected_query,
                                conversation_id=conversation_id,
                            )
                            if bool(tests_selected.get("matched")):
                                logger.debug("domains prefilter early return | stage=numeric_selection_tests")
                                return _final({
                                    "reply": format_runtime_answer(_safe_str(tests_selected.get("answer"))),
                                    "route": _safe_str(tests_selected.get("route")) or "tests",
                                    "source": "tests",
                                    "matched": True,
                                    "meta": _tests_meta(tests_selected.get("meta") or {}),
                                }, "numeric_selection_tests")

            if is_package_like and ENABLE_PACKAGES_RUNTIME_AFTER_BRANCHES:
                packages_result = resolve_packages_query(text, conversation_id=conversation_id)
                if bool(packages_result.get("matched")):
                    logger.debug(
                        "packages pre-faq guard matched | q=%s | numeric=%s | branch_like=%s | package_like=%s | tests_like=%s | route=%s",
                        text,
                        is_numeric,
                        is_branch_like,
                        is_package_like,
                        is_tests_like,
                        _safe_str(packages_result.get("route")),
                    )
                    logger.debug("domains prefilter early return | stage=packages_match")
                    return _final({
                        "reply": format_runtime_answer(_safe_str(packages_result.get("answer"))),
                        "route": _safe_str(packages_result.get("route")) or "packages",
                        "source": "packages",
                        "matched": True,
                        "meta": dict(packages_result.get("meta") or {}),
                    }, "domains_prefilter_packages")

            if is_tests_like and ENABLE_TESTS_RUNTIME_AFTER_PACKAGES:
                tests_business_result = resolve_tests_business_query(
                    text,
                    conversation_id=conversation_id,
                )
                if _is_supported_tests_business_result(tests_business_result):
                    logger.debug(
                        "tests business pre-faq guard matched | q=%s | numeric=%s | branch_like=%s | package_like=%s | tests_like=%s | route=%s",
                        text,
                        is_numeric,
                        is_branch_like,
                        is_package_like,
                        is_tests_like,
                        _safe_str(tests_business_result.get("route")),
                    )
                    logger.debug("domains prefilter early return | stage=tests_business_match")
                    return _final({
                        "reply": format_runtime_answer(_safe_str(tests_business_result.get("answer"))),
                        "route": _safe_str(tests_business_result.get("route")) or "tests_business",
                        "source": "tests_business",
                        "matched": True,
                        "meta": _tests_business_meta(tests_business_result.get("meta") or {}),
                    }, "domains_prefilter_tests_business")

                tests_result = resolve_tests_query(text, conversation_id=conversation_id)
                if bool(tests_result.get("matched")):
                    logger.debug(
                        "tests pre-faq guard matched | q=%s | numeric=%s | branch_like=%s | package_like=%s | tests_like=%s | route=%s",
                        text,
                        is_numeric,
                        is_branch_like,
                        is_package_like,
                        is_tests_like,
                        _safe_str(tests_result.get("route")),
                    )
                    logger.debug("domains prefilter early return | stage=tests_match")
                    return _final({
                        "reply": format_runtime_answer(_safe_str(tests_result.get("answer"))),
                        "route": _safe_str(tests_result.get("route")) or "tests",
                        "source": "tests",
                        "matched": True,
                        "meta": _tests_meta(tests_result.get("meta") or {}),
                    }, "domains_prefilter_tests")

            logger.debug(
                "domains pre-faq guard no match | q=%s | numeric=%s | branch_like=%s | package_like=%s | tests_like=%s | route=domains_pre_faq_no_match",
                text,
                is_numeric,
                is_branch_like,
                is_package_like,
                is_tests_like,
            )
            logger.debug(
                "domains pre-faq guard fallback faq attempt | q=%s | numeric=%s | branch_like=%s | package_like=%s | tests_like=%s",
                text,
                is_numeric,
                is_branch_like,
                is_package_like,
                is_tests_like,
            )
            faq_fallback_result = resolve_faq(
                text,
                last_user_text=last_user_text,
                last_assistant_text=last_assistant_text,
                recent_runtime_messages=recent_runtime_messages,
            )
            logger.debug(
                "domains prefilter faq fallback result | matched=%s",
                bool(faq_fallback_result),
            )
            if faq_fallback_result:
                logger.debug(
                    "domains pre-faq guard fallback faq matched | q=%s | selected_faq_id=%s | matched_text=%s | route=faq_only",
                    text,
                    _safe_str(faq_fallback_result.get("faq_id")),
                    _safe_str(faq_fallback_result.get("matched_text")),
                )
                logger.debug("domains prefilter early return | stage=faq_fallback_match")
                return _final({
                    "reply": format_runtime_answer(_safe_str(faq_fallback_result.get("answer"))),
                    "route": "faq_only",
                    "source": "faq",
                    "matched": True,
                    "meta": {
                        "faq_id": _safe_str(faq_fallback_result.get("faq_id")),
                        "question": _safe_str(faq_fallback_result.get("question")),
                        "score": float(faq_fallback_result.get("score") or 0.0),
                        "margin": float(faq_fallback_result.get("margin") or 0.0),
                        "matched_text": _safe_str(faq_fallback_result.get("matched_text")),
                        "concepts": list(faq_fallback_result.get("concepts") or []),
                    },
                }, "domains_prefilter_faq_fallback_match")
            logger.debug(
                "domains pre-faq guard fallback faq not matched | q=%s | route=faq_only_no_match_domains_prefilter",
                text,
            )
            logger.debug(
                "ollama fallback calling | stage=domains_prefilter_after_faq_no_match | q=%s",
                text,
            )
            classifier_result = _try_ollama_classifier_fallback(
                text,
                conversation_id=conversation_id,
            )
            if classifier_result is not None:
                logger.debug(
                    "ollama fallback reroute_succeeded | stage=domains_prefilter_after_faq_no_match | route=%s | source=%s",
                    _safe_str(classifier_result.get("route")),
                    _safe_str(classifier_result.get("source")),
                )
                return _final(classifier_result, "ollama_fallback_domains_prefilter_after_faq")
            logger.debug("ollama fallback reroute_failed | stage=domains_prefilter_after_faq_no_match")
            logger.debug("domains prefilter early return | stage=domains_prefilter_no_match")
            return _final({
                "reply": format_runtime_answer(get_faq_no_match_message()),
                "route": "faq_only_no_match_domains_prefilter",
                "source": "runtime_fallback",
                "matched": False,
                "meta": {
                    "mode": "faq_only",
                    "domains_prefilter": True,
                    "numeric_query": is_numeric,
                    "branch_like_query": is_branch_like,
                    "package_like_query": is_package_like,
                    "tests_like_query": is_tests_like,
                },
            }, "domains_prefilter_no_match")
        logger.debug(
            "domains prefilter skipped | q=%s | numeric=%s | branch_like=%s | package_like=%s | tests_like=%s",
            text,
            is_numeric,
            is_branch_like,
            is_package_like,
            is_tests_like,
        )

        if is_symptoms_like:
            symptoms_result = handle_symptoms_query(text)
            if symptoms_result:
                if _safe_str(symptoms_result.get("type")) == "symptom_clarification":
                    return _final({
                        "reply": format_runtime_answer(
                            _safe_str(symptoms_result.get("answer"))
                            or "\u0648\u0635\u0651\u0641 \u0627\u0644\u0639\u0631\u0636 \u0627\u0644\u0631\u0626\u064a\u0633\u064a \u0628\u0634\u0643\u0644 \u0623\u0648\u0636\u062d (\u0645\u062b\u0644: \u0635\u062f\u0627\u0639 \u0645\u0633\u062a\u0645\u0631\u060c \u062d\u0631\u0627\u0631\u0629 \u0645\u0639 \u0643\u062d\u0629\u060c \u0623\u0644\u0645 \u0628\u0637\u0646 \u0645\u0639 \u063a\u062b\u064a\u0627\u0646)."
                        ),
                        "route": "symptoms_clarification",
                        "source": "symptoms_engine",
                        "matched": True,
                        "meta": {
                            "query_type": "symptoms_query",
                            "symptoms": list(symptoms_result.get("symptoms") or []),
                            "tests_count": 0,
                            "packages_count": 0,
                            "clarification_needed": True,
                        },
                    }, "symptoms_clarification")
                return _final({
                    "reply": format_runtime_answer(_format_symptoms_suggestions_reply(symptoms_result)),
                    "route": "symptoms_suggestions",
                    "source": "symptoms_engine",
                    "matched": True,
                    "meta": {
                        "query_type": "symptoms_query",
                        "symptoms": list(symptoms_result.get("symptoms") or []),
                        "tests_count": len(list(symptoms_result.get("tests") or [])),
                        "packages_count": len(list(symptoms_result.get("packages") or [])),
                    },
                }, "symptoms_route")

        faq_result = resolve_faq(
            text,
            last_user_text=last_user_text,
            last_assistant_text=last_assistant_text,
            recent_runtime_messages=recent_runtime_messages,
        )
        if faq_result:
            logger.debug(
                "faq_only route matched | q=%s | selected_faq_id=%s | matched_text=%s | route=faq_only",
                text,
                _safe_str(faq_result.get("faq_id")),
                _safe_str(faq_result.get("matched_text")),
            )
            return _final({
                "reply": format_runtime_answer(_safe_str(faq_result.get("answer"))),
                "route": "faq_only",
                "source": "faq",
                "matched": True,
                "meta": {
                    "faq_id": _safe_str(faq_result.get("faq_id")),
                    "question": _safe_str(faq_result.get("question")),
                    "score": float(faq_result.get("score") or 0.0),
                    "margin": float(faq_result.get("margin") or 0.0),
                    "matched_text": _safe_str(faq_result.get("matched_text")),
                    "concepts": list(faq_result.get("concepts") or []),
                },
            }, "faq_direct_match")

        logger.debug(
            "faq_only no match | q=%s | route=faq_only_no_match",
            text,
        )
        semantic_intent = ""
        semantic_score = 0.0
        semantic_routing_used = False
        if ENABLE_BRANCHES_RUNTIME_AFTER_FAQ:
            logger.debug(
                "after_faq_no_match branch/package/tests block entry | q=%s | enabled=%s",
                text,
                ENABLE_BRANCHES_RUNTIME_AFTER_FAQ,
            )
            semantic_result = detect_branch_semantic_intent(text)
            semantic_intent = _safe_str(semantic_result.get("intent"))
            semantic_score = float(semantic_result.get("score") or 0.0)
            semantic_routing_used = is_confident_branch_intent(semantic_result)
            is_package_like = _looks_like_package_query(text)

            branches_result = resolve_branches_query(text, conversation_id=conversation_id)
            if bool(branches_result.get("matched")):
                logger.debug(
                    "branches route matched after faq no match | q=%s | route=%s | semantic_intent=%s | semantic_score=%.4f | semantic_routing_used=%s",
                    text,
                    _safe_str(branches_result.get("route")),
                    semantic_intent,
                    semantic_score,
                    semantic_routing_used,
                )
                meta = dict(branches_result.get("meta") or {})
                meta["semantic_intent"] = semantic_intent
                meta["semantic_score"] = semantic_score
                meta["semantic_routing_used"] = semantic_routing_used
                return _final({
                    "reply": format_runtime_answer(_safe_str(branches_result.get("answer"))),
                    "route": _safe_str(branches_result.get("route")) or "branches",
                    "source": "branches",
                    "matched": True,
                    "meta": meta,
                }, "after_faq_no_match_branches")
            logger.debug("after_faq_no_match no branch match | q=%s", text)

            if is_package_like and ENABLE_PACKAGES_RUNTIME_AFTER_BRANCHES:
                packages_result = resolve_packages_query(text, conversation_id=conversation_id)
                if bool(packages_result.get("matched")):
                    logger.debug(
                        "packages route matched after faq/branches no match | q=%s | route=%s",
                        text,
                        _safe_str(packages_result.get("route")),
                    )
                    return _final({
                        "reply": format_runtime_answer(_safe_str(packages_result.get("answer"))),
                        "route": _safe_str(packages_result.get("route")) or "packages",
                        "source": "packages",
                        "matched": True,
                        "meta": dict(packages_result.get("meta") or {}),
                    }, "after_faq_no_match_packages")
                logger.debug("after_faq_no_match no package match | q=%s", text)
            if ENABLE_TESTS_RUNTIME_AFTER_PACKAGES:
                tests_business_result = resolve_tests_business_query(
                    text,
                    conversation_id=conversation_id,
                )
                if _is_supported_tests_business_result(tests_business_result):
                    logger.debug(
                        "tests business route matched after faq/branches/packages no match | q=%s | route=%s",
                        text,
                        _safe_str(tests_business_result.get("route")),
                    )
                    return _final({
                        "reply": format_runtime_answer(_safe_str(tests_business_result.get("answer"))),
                        "route": _safe_str(tests_business_result.get("route")) or "tests_business",
                        "source": "tests_business",
                        "matched": True,
                        "meta": _tests_business_meta(tests_business_result.get("meta") or {}),
                    }, "after_faq_no_match_tests_business")

                tests_result = resolve_tests_query(text, conversation_id=conversation_id)
                if bool(tests_result.get("matched")):
                    logger.debug(
                        "tests route matched after faq/branches/packages no match | q=%s | route=%s",
                        text,
                        _safe_str(tests_result.get("route")),
                    )
                    return _final({
                        "reply": format_runtime_answer(_safe_str(tests_result.get("answer"))),
                        "route": _safe_str(tests_result.get("route")) or "tests",
                        "source": "tests",
                        "matched": True,
                        "meta": _tests_meta(tests_result.get("meta") or {}),
                    }, "after_faq_no_match_tests")
                logger.debug("after_faq_no_match no tests match | q=%s", text)
        classifier_result = _try_ollama_classifier_fallback(
            _safe_str(user_text),
            conversation_id=conversation_id,
        )
        if classifier_result is not None:
            logger.debug(
                "ollama fallback reroute_succeeded | stage=faq_only_final_no_match | route=%s | source=%s",
                _safe_str(classifier_result.get("route")),
                _safe_str(classifier_result.get("source")),
            )
            return _final(classifier_result, "ollama_fallback_faq_only_no_match")
        logger.debug("ollama fallback reroute_failed | stage=faq_only_final_no_match")
        return _final({
            "reply": format_runtime_answer(get_faq_no_match_message()),
            "route": "faq_only_no_match",
            "source": "runtime_fallback",
            "matched": False,
            "meta": {
                "mode": "faq_only",
                "semantic_intent": semantic_intent,
                "semantic_score": semantic_score,
                "semantic_routing_used": semantic_routing_used,
            },
        }, "faq_only_final_no_match")

    classifier_result = _try_ollama_classifier_fallback(
        _safe_str(user_text),
        conversation_id=conversation_id,
    )
    if classifier_result is not None:
        logger.debug(
            "ollama fallback reroute_succeeded | stage=no_runtime_mode | route=%s | source=%s",
            _safe_str(classifier_result.get("route")),
            _safe_str(classifier_result.get("source")),
        )
        return _final(classifier_result, "ollama_fallback_no_runtime_mode")
    logger.debug("ollama fallback reroute_failed | stage=no_runtime_mode")

    return _final({
        "reply": format_runtime_answer(get_out_of_scope_message()),
        "route": "no_runtime_mode",
        "source": "runtime_fallback",
        "matched": False,
        "meta": {
            "mode": "no_runtime_mode",
        },
    }, "no_runtime_mode")


def route_runtime_reply(
    user_text: str,
    *,
    conversation_id: UUID | None = None,
    system_rebuild_mode: bool = False,
    faq_only_runtime_mode: bool = False,
    last_user_text: str = "",
    last_assistant_text: str = "",
    recent_runtime_messages: list[dict[str, Any]] | None = None,
) -> str:
    """Return only the final reply text for the current runtime stage."""
    result = route_runtime_message(
        user_text,
        conversation_id=conversation_id,
        system_rebuild_mode=system_rebuild_mode,
        faq_only_runtime_mode=faq_only_runtime_mode,
        last_user_text=last_user_text,
        last_assistant_text=last_assistant_text,
        recent_runtime_messages=recent_runtime_messages,
    )
    return _safe_str(result.get("reply"))


if __name__ == "__main__":
    samples = [
        "وش الخدمات اللي عندكم",
        "عندكم سحب من البيت",
        "وين اقرب فرع بالرياض",
    ]

    print("=== FAQ ONLY MODE ===")
    for sample in samples:
        result = route_runtime_message(
            sample,
            system_rebuild_mode=False,
            faq_only_runtime_mode=True,
        )
        print(f"INPUT : {sample}")
        print(f"ROUTE : {result.get('route')}")
        print(f"SOURCE: {result.get('source')}")
        print(f"MATCH : {result.get('matched')}")
        print(f"REPLY : {result.get('reply')}")
        print(f"META  : {result.get('meta')}")
        print("-" * 80)

    print("=== REBUILD MODE ===")
    result = route_runtime_message(
        "مرحبا",
        system_rebuild_mode=True,
        faq_only_runtime_mode=False,
    )
    print(f"ROUTE : {result.get('route')}")
    print(f"REPLY : {result.get('reply')}")

