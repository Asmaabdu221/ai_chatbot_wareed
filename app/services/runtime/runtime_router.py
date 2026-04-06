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
from app.services.runtime.ollama_intent_classifier import classify_intent
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
    return _detector_pick("symptoms_like", n, scores, min_score=2.0, legacy_match=legacy)


def _format_symptoms_suggestions_reply(payload: dict[str, Any]) -> str:
    tests = [str(t).strip() for t in list(payload.get("tests") or []) if str(t).strip()]
    packages = [str(p).strip() for p in list(payload.get("packages") or []) if str(p).strip()]

    lines: list[str] = ["بناءً على الأعراض اللي ذكرتها، ممكن تعمل التحاليل التالية:", ""]
    if tests:
        for idx, test_name in enumerate(tests, start=1):
            lines.append(f"{idx}. {test_name}")
    else:
        lines.append("لا توجد تحاليل مقترحة حالياً في البيانات المتاحة.")

    if packages:
        lines.extend(["", "أو تقدر تختار باقة:"])
        for package_name in packages:
            lines.append(f"- {package_name}")
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

    memory = load_entity_memory(conversation_id)
    cls = classify_intent(raw_text, memory)
    print("AI classifier:", cls)

    intent = _safe_str((cls or {}).get("intent")).lower()
    try:
        confidence = float((cls or {}).get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    if confidence < 0.85:
        return None
    if intent not in {"test", "package", "branch", "faq", "symptoms", "results", "unknown"}:
        return None
    if _has_strong_keyword_conflict(raw_text, intent):
        return None
    if intent in {"faq", "symptoms", "results", "unknown"}:
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
        return _log_final_route_decision(
            result,
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
        # Strong branch guard before FAQ:
        # - numeric selection (1-2 digits) should be branch-first
        # - explicit branch/location/package/tests phrasing should bypass FAQ
        is_numeric = _is_numeric_selection_query(text)
        is_branch_like = _looks_like_branch_query(text)
        is_package_like = _looks_like_package_query(text)
        is_tests_like = _looks_like_tests_query(text)
        is_symptoms_like = _looks_like_symptoms_query(text)

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

        if is_numeric or is_branch_like or is_package_like or is_tests_like:
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
            if False:
                classifier_result = _try_ollama_classifier_fallback(
                    _safe_str(user_text),
                    conversation_id=conversation_id,
                )
                if classifier_result is not None:
                    return classifier_result
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
            if faq_fallback_result:
                logger.debug(
                    "domains pre-faq guard fallback faq matched | q=%s | selected_faq_id=%s | matched_text=%s | route=faq_only",
                    text,
                    _safe_str(faq_fallback_result.get("faq_id")),
                    _safe_str(faq_fallback_result.get("matched_text")),
                )
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

        if is_symptoms_like:
            symptoms_result = handle_symptoms_query(text)
            if symptoms_result:
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
        if False:
            classifier_result = _try_ollama_classifier_fallback(
                _safe_str(user_text),
                conversation_id=conversation_id,
            )
            if classifier_result is not None:
                return classifier_result
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

