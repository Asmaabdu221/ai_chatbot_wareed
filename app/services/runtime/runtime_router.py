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
from app.services.runtime.packages_business_engine import handle_packages_business_query
from app.services.runtime.packages_resolver import resolve_packages_query
from app.services.runtime.results_engine import interpret_result_query
from app.services.runtime.results_query_detector import looks_like_result_query
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
    return any(h in n for h in hints)


def _looks_like_package_query(text: str) -> bool:
    n = normalize_arabic(text)
    if not n:
        return False
    if _looks_like_branch_query(n):
        return False

    # Strong package signals first.
    if any(token in n for token in ("باقه", "باقات", "package")):
        return True
    if any(token in n for token in ("well dna", "nifty", "genetic package", "genetic_test")):
        return True

    # Category/product phrasing (deterministic, conservative).
    has_test_word = any(token in n for token in ("تحليل", "تحاليل"))
    has_package_category = any(token in n for token in ("جيني", "جينية", "رمضان", "ذاتية", "self collection"))
    has_price_word = any(token in n for token in ("كم سعر", "بكم", "سعر"))
    if has_test_word and has_package_category:
        return True
    if has_price_word and ("باقه" in n or "package" in n):
        return True
    return False


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
    return any(token in n for token in hints)


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
    return any(normalize_arabic(token) in n for token in hints)


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
        packages_business_result = handle_packages_business_query(
            package_query,
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
                    "selection_number": selection_number,
                    "matched_package_id": _safe_str((top_package or {}).get("id")),
                    "matched_package_name": _safe_str((top_package or {}).get("package_name")),
                },
            }
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

    if system_rebuild_mode:
        return {
            "reply": format_runtime_answer(get_rebuild_mode_message()),
            "route": "rebuild_mode",
            "source": "runtime_fallback",
            "matched": False,
            "meta": {
                "mode": "system_rebuild",
            },
        }

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
                return selection_result

        if looks_like_result_query(text) and not is_branch_like and not is_package_like and not is_symptoms_like:
            result_answer = _safe_str(interpret_result_query(text))
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
                    return {
                        "reply": format_runtime_answer(_safe_str(branches_result.get("answer"))),
                        "route": _safe_str(branches_result.get("route")) or "branches",
                        "source": "branches",
                        "matched": True,
                        "meta": dict(branches_result.get("meta") or {}),
                    }
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

            if is_package_like and ENABLE_PACKAGES_RUNTIME_AFTER_BRANCHES:
                packages_business_result = handle_packages_business_query(
                    text,
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
                    return {
                        "reply": format_runtime_answer(_safe_str(packages_result.get("answer"))),
                        "route": _safe_str(packages_result.get("route")) or "packages",
                        "source": "packages",
                        "matched": True,
                        "meta": dict(packages_result.get("meta") or {}),
                    }

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
                    return {
                        "reply": format_runtime_answer(_safe_str(tests_business_result.get("answer"))),
                        "route": _safe_str(tests_business_result.get("route")) or "tests_business",
                        "source": "tests_business",
                        "matched": True,
                        "meta": _tests_business_meta(tests_business_result.get("meta") or {}),
                    }

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
                    return {
                        "reply": format_runtime_answer(_safe_str(tests_result.get("answer"))),
                        "route": _safe_str(tests_result.get("route")) or "tests",
                        "source": "tests",
                        "matched": True,
                        "meta": _tests_meta(tests_result.get("meta") or {}),
                    }

            logger.debug(
                "domains pre-faq guard no match | q=%s | numeric=%s | branch_like=%s | package_like=%s | tests_like=%s | route=domains_pre_faq_no_match",
                text,
                is_numeric,
                is_branch_like,
                is_package_like,
                is_tests_like,
            )
            # Do not let FAQ hijack numeric/branch/location/package/tests queries.
            return {
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
            }

        if is_symptoms_like:
            symptoms_result = handle_symptoms_query(text)
            if symptoms_result:
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
                return {
                    "reply": format_runtime_answer(_safe_str(branches_result.get("answer"))),
                    "route": _safe_str(branches_result.get("route")) or "branches",
                    "source": "branches",
                    "matched": True,
                    "meta": meta,
                }

            if is_package_like and ENABLE_PACKAGES_RUNTIME_AFTER_BRANCHES:
                packages_business_result = handle_packages_business_query(
                    text,
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
                packages_result = resolve_packages_query(text, conversation_id=conversation_id)
                if bool(packages_result.get("matched")):
                    logger.debug(
                        "packages route matched after faq/branches no match | q=%s | route=%s",
                        text,
                        _safe_str(packages_result.get("route")),
                    )
                    return {
                        "reply": format_runtime_answer(_safe_str(packages_result.get("answer"))),
                        "route": _safe_str(packages_result.get("route")) or "packages",
                        "source": "packages",
                        "matched": True,
                        "meta": dict(packages_result.get("meta") or {}),
                    }
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
                    return {
                        "reply": format_runtime_answer(_safe_str(tests_business_result.get("answer"))),
                        "route": _safe_str(tests_business_result.get("route")) or "tests_business",
                        "source": "tests_business",
                        "matched": True,
                        "meta": _tests_business_meta(tests_business_result.get("meta") or {}),
                    }

                tests_result = resolve_tests_query(text, conversation_id=conversation_id)
                if bool(tests_result.get("matched")):
                    logger.debug(
                        "tests route matched after faq/branches/packages no match | q=%s | route=%s",
                        text,
                        _safe_str(tests_result.get("route")),
                    )
                    return {
                        "reply": format_runtime_answer(_safe_str(tests_result.get("answer"))),
                        "route": _safe_str(tests_result.get("route")) or "tests",
                        "source": "tests",
                        "matched": True,
                        "meta": _tests_meta(tests_result.get("meta") or {}),
                    }
        return {
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
        }

    return {
        "reply": format_runtime_answer(get_out_of_scope_message()),
        "route": "no_runtime_mode",
        "source": "runtime_fallback",
        "matched": False,
        "meta": {
            "mode": "no_runtime_mode",
        },
    }


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

