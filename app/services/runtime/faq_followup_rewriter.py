"""Deterministic follow-up resolution and canonical FAQ query rewriting."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.runtime.text_normalizer import normalize_arabic


@dataclass(frozen=True)
class FAQRewriteResult:
    """Structured output for follow-up-aware FAQ query rewriting."""

    original_query: str
    resolved_query: str
    rewritten_query: str
    intent_hint: str | None
    confidence: float
    used_followup: bool
    followup_source_text: str
    notes: list[str] = field(default_factory=list)


_FOLLOWUP_MARKERS = (
    "هو",
    "هي",
    "هذا",
    "هذه",
    "ذاك",
    "طيب",
    "ويحتاج",
    "يحتاج صيام",
    "كم سعره",
    "وينه",
    "ما رمزه",
    "كم يطلع",
)

_BRANCH_CITY_HINTS = (
    "بالرياض",
    "في الرياض",
    "بالجده",
    "في جده",
    "بالدمام",
    "في الدمام",
    "بمكه",
    "في مكه",
    "بالخبر",
    "في الخبر",
)


def _safe_str(value: object) -> str:
    return str(value or "").strip()


def _is_followup_query(user_text: str) -> bool:
    """Return True when query likely depends on prior turn context."""
    n = normalize_arabic(user_text)
    if not n:
        return False

    tokens = [t for t in n.split(" ") if t]
    if len(tokens) <= 2:
        return True
    if len(tokens) <= 4 and any(marker in n for marker in _FOLLOWUP_MARKERS):
        return True
    if any(marker in n for marker in ("هل هو", "هل هذا", "ما رمزه", "كيف طريقته", "كم سعره", "وينه")):
        return True
    return False


def _normalize_short_followup(user_text: str) -> str:
    """Apply small deterministic cleanup for short follow-up phrasing."""
    n = normalize_arabic(user_text)
    if not n:
        return ""
    n = n.replace("ويحتاج", "يحتاج").replace("هو ", "").replace("هي ", "")
    n = " ".join(part for part in n.split(" ") if part)
    return n.strip()


def _resolve_followup_entity(
    user_text: str,
    last_user_text: str,
    last_assistant_text: str,
    last_resolved_intent: str,
    last_resolved_entity: str,
) -> tuple[str, bool, str, list[str], float]:
    """Resolve follow-up shorthand into a fuller query using prior entity/intent."""
    notes: list[str] = []
    original = _safe_str(user_text)
    cleaned = _normalize_short_followup(original) or normalize_arabic(original)
    entity = normalize_arabic(last_resolved_entity)
    intent = _safe_str(last_resolved_intent)
    followup_source = _safe_str(last_resolved_entity) or _safe_str(last_user_text) or _safe_str(last_assistant_text)

    if not _is_followup_query(original):
        return original, False, followup_source, notes, 0.66

    if entity:
        if "رمز" in cleaned or "كود" in cleaned:
            notes.append("followup_entity_code")
            return f"ما هو رمز {entity}", True, followup_source, notes, 0.93
        if "صيام" in cleaned or "يحتاج" in cleaned:
            notes.append("followup_entity_fasting")
            return f"هل {entity} يحتاج صيام او لا", True, followup_source, notes, 0.92
        if "سعر" in cleaned:
            notes.append("followup_entity_price_wording")
            return f"كم سعر {entity}", True, followup_source, notes, 0.84
        if ("وين" in cleaned or "اين" in cleaned) and ("فرع" in entity or "فروع" in entity):
            city_hint = ""
            for city in _BRANCH_CITY_HINTS:
                if normalize_arabic(city) in cleaned:
                    city_hint = normalize_arabic(city)
                    break
            notes.append("followup_entity_branch_location")
            if city_hint:
                return f"وين اقرب فرع {city_hint}", True, followup_source, notes, 0.90
            return "اين تتواجد فروع مختبرات وريد", True, followup_source, notes, 0.86
        if "امن" in cleaned or "امنه" in cleaned:
            notes.append("followup_entity_safety")
            return f"هل {entity} امن", True, followup_source, notes, 0.82

        notes.append("followup_entity_attached")
        return f"{cleaned} {entity}".strip(), True, followup_source, notes, 0.75

    if intent:
        if intent in {"hba1c_fasting", "thyroid_fasting", "fasting_general"} and (
            "صيام" in cleaned or "يحتاج" in cleaned
        ):
            notes.append("followup_intent_fasting")
            return "هل التحليل يحتاج صيام", True, followup_source, notes, 0.72
        if intent == "hba1c_code" and ("رمز" in cleaned or "كود" in cleaned):
            notes.append("followup_intent_code")
            return "ما هو رمز تحليل السكر التراكمي", True, followup_source, notes, 0.74

    notes.append("followup_unclear")
    return original, False, followup_source, notes, 0.45


def _rewrite_to_canonical(resolved_query: str) -> tuple[str, str | None, float, list[str]]:
    """Rewrite query into closest FAQ-style canonical wording."""
    n = normalize_arabic(resolved_query)
    notes: list[str] = []
    if not n:
        return "", None, 0.0, notes

    if "خدمات" in n or ("مختبر" in n and "وريد" in n and "ما" in n):
        return "ما هي الخدمات التي يقدمها مختبر وريد", "services_overview", 0.95, ["canonical_services"]
    if ("سحب" in n and ("المنزل" in n or "البيت" in n)) or "الزيارات المنزليه" in n:
        return "هل يوفر مختبر وريد خدمة الزيارات المنزلية", "home_visit", 0.94, ["canonical_home_visit"]
    if ("متى" in n or "كم" in n) and ("نتيجه" in n or "النتائج" in n):
        return "كم تستغرق نتائج التحاليل للظهور", "results_turnaround", 0.90, ["canonical_results_turnaround"]
    if "طرق" in n and "الدفع" in n or ("ادفع" in n and "كيف" in n):
        return "ما هي طرق الدفع المتاحة", "payment_methods", 0.95, ["canonical_payment_methods"]
    if ("فروع" in n or "فرع" in n) and any(x in n for x in ("اقرب", "عنوان", "لوكيشن", "بال", "في ")):
        return resolved_query, "branches_locations", 0.80, ["branch_specific_preserved"]
    if "فروع" in n or "فروعكم" in n:
        return "اين تتواجد فروع مختبرات وريد", "branches_locations", 0.93, ["canonical_branches"]
    if "عروض" in n or "تخفيض" in n or "خصومات" in n:
        if "قديم" in n or "قديمة" in n:
            return "كيف اعرف اذا العرض القديم باقي", "old_offer_validity", 0.90, ["canonical_old_offer_validity"]
        return "هل توجد عروض او تخفيضات حاليا", "current_offers", 0.92, ["canonical_current_offers"]
    if ("امن" in n or "امنه" in n or "خطوره" in n) and ("اطفال" in n or "كبار السن" in n):
        return "هل التحاليل امنه للاطفال وكبار السن", "safety_children_elderly", 0.93, ["canonical_safety"]
    if "خصوص" in n and ("نتائج" in n or "تحليل" in n):
        if "حساس" in n:
            return "كيف اضمن خصوصيه التحاليل الحساسه", "sensitive_tests_privacy", 0.93, ["canonical_sensitive_privacy"]
        return "هل نتائج التحاليل سريه", "results_privacy", 0.90, ["canonical_results_privacy"]
    if ("سكر" in n and "تراكمي" in n) and ("صيام" in n or "يحتاج" in n):
        return "هل تحليل السكر التراكمي يحتاج صيام", "hba1c_fasting", 0.96, ["canonical_hba1c_fasting"]
    if ("سكر" in n and "تراكمي" in n) and ("رمز" in n or "كود" in n):
        return "ما هو رمز تحليل السكر التراكمي", "hba1c_code", 0.96, ["canonical_hba1c_code"]
    if ("غده" in n or "thyroid" in n or "tsh" in n) and ("صيام" in n or "يحتاج" in n):
        return "هل تحليل الغدة الدرقية يحتاج صيام", "thyroid_fasting", 0.95, ["canonical_thyroid_fasting"]
    if "صيام" in n and ("تحليل" in n or "تحاليل" in n):
        return "ما هي التحاليل التي تحتاج الي صيام", "fasting_general", 0.87, ["canonical_fasting_general"]
    if ("النتائج" in n or "نتيجه" in n) and ("الكترون" in n or "واتساب" in n or "ايميل" in n):
        return "هل يتم ارسال نتائج التحاليل الكترونيا", "electronic_results", 0.88, ["canonical_electronic_results"]

    notes.append("canonical_uncertain_passthrough")
    return resolved_query, None, 0.58, notes


def _guess_intent_hint(rewritten_query: str, fallback_hint: str | None) -> str | None:
    """Infer intent hint from rewritten query when not already known."""
    if fallback_hint:
        return fallback_hint
    n = normalize_arabic(rewritten_query)
    if not n:
        return None
    if "طرق الدفع" in n or ("الدفع" in n and "ما هي" in n):
        return "payment_methods"
    if "السكر التراكمي" in n and "صيام" in n:
        return "hba1c_fasting"
    if "رمز تحليل السكر التراكمي" in n:
        return "hba1c_code"
    if "الغدة الدرقية" in n and "صيام" in n:
        return "thyroid_fasting"
    if "فروع" in n:
        return "branches_locations"
    if "خصوص" in n and "حساس" in n:
        return "sensitive_tests_privacy"
    if "نتائج التحاليل سريه" in n:
        return "results_privacy"
    return None


def rewrite_faq_query(
    user_text: str,
    last_user_text: str = "",
    last_assistant_text: str = "",
    last_resolved_intent: str = "",
    last_resolved_entity: str = "",
) -> FAQRewriteResult:
    """Resolve follow-up ambiguity and rewrite to FAQ-style canonical query."""
    original = _safe_str(user_text)
    resolved, used_followup, source_text, notes, followup_conf = _resolve_followup_entity(
        original,
        last_user_text,
        last_assistant_text,
        last_resolved_intent,
        last_resolved_entity,
    )
    rewritten, hint, rewrite_conf, rewrite_notes = _rewrite_to_canonical(resolved or original)
    notes.extend(rewrite_notes)

    intent_hint = _guess_intent_hint(rewritten, hint)
    confidence = max(0.0, min(1.0, max(followup_conf, rewrite_conf)))

    if not rewritten:
        rewritten = resolved or original
        confidence = min(confidence, 0.45)

    return FAQRewriteResult(
        original_query=original,
        resolved_query=resolved or original,
        rewritten_query=rewritten,
        intent_hint=intent_hint,
        confidence=confidence,
        used_followup=used_followup,
        followup_source_text=_safe_str(source_text),
        notes=notes,
    )


if __name__ == "__main__":
    scenarios = [
        {
            "user_text": "هل هو يحتاج صيام او لا",
            "last_resolved_entity": "السكر التراكمي",
        },
        {
            "user_text": "ما رمزه",
            "last_resolved_entity": "السكر التراكمي",
        },
        {
            "user_text": "كيف اقدر ادفع",
        },
        {
            "user_text": "وين فروعكم",
        },
        {
            "user_text": "وين اقرب واحد بالرياض",
            "last_resolved_entity": "فروع مختبر وريد",
        },
        {
            "user_text": "هل امن للاطفال",
        },
        {
            "user_text": "هل فيه خصوصية",
        },
    ]

    for case in scenarios:
        result = rewrite_faq_query(**case)
        print(f"INPUT      : {case.get('user_text')}")
        print(f"RESOLVED   : {result.resolved_query}")
        print(f"REWRITTEN  : {result.rewritten_query}")
        print(f"INTENT     : {result.intent_hint}")
        print(f"CONFIDENCE : {result.confidence:.2f}")
        print(f"FOLLOWUP   : {result.used_followup}")
        print(f"SOURCE     : {result.followup_source_text}")
        print(f"NOTES      : {result.notes}")
        print("-" * 56)
