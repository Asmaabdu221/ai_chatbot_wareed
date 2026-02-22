"""
Fallback response helpers for non-LLM flows.
"""

import re


def sanitize_for_ui(text: str) -> str:
    clean = (text or "").strip()
    if not clean:
        return clean
    clean = clean.replace("**", "")
    clean = re.sub(r"\s+\n", "\n", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


def compose_context_fallback(
    question: str,
    intent: str,
    slots: dict,
    knowledge_context: str | None,
) -> str:
    context = sanitize_for_ui(knowledge_context or "")
    if context:
        lines = [f"بناءً على المعلومات المتوفرة عندنا عن سؤالك: {question}"]
        lines.extend([ln for ln in context.splitlines() if ln.strip()][:8])
        lines.append("")
        lines.append("إذا تبغى/تبغين تفاصيل أدق على حالة معينة، اكتب/ي اسم التحليل أو أرفق/ي التقرير بوضوح.")
        return sanitize_for_ui("\n".join(lines))

    if intent in {"branches_locations", "working_hours", "contact_support", "home_visit"}:
        return "حالياً ما عندنا تفاصيل كافية عن الفرع المطلوب. تقدر/تقدرين تتواصل معنا على 800-122-1220 ونخدمك فوراً."
    if intent in {"pricing_inquiry", "packages_inquiry", "offers_discounts"}:
        return "للاستفسار عن الأسعار والباقات الحالية تقدر/تقدرين تتواصل معنا على 800-122-1220."
    if slots.get("analysis_name"):
        return f"حالياً ما عندنا تفاصيل كافية عن تحليل {slots['analysis_name']}، تقدر/تقدرين تتواصل معنا على 800-122-1220."
    return "ممكن توضح/توضحين سؤالك أكثر؟ وإذا تحب/تحبين تقدر/تقدرين تتواصل معنا مباشرة على 800-122-1220."
