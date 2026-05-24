"""
Scenario-aware context builder (Lab RAG v2).

Turns retrieved master rows into a compact, grounded Arabic context block
shaped by the query intent. Enforces two safety rules:
  * price is included ONLY when ``include_price=True`` (i.e. after phone capture);
  * clinical values flagged ``AI_GENERATED`` / ``NEEDS_REVIEW`` are never asserted
    as fact — a safe fallback is emitted instead.
"""

from __future__ import annotations

from typing import Optional

from app.services.intent_classifier import QueryIntent

SAFE_FALLBACK = "يُرجى التواصل مع فريق المختبر للتأكيد"
PRICE_PLACEHOLDERS = {"", "NEEDS_PRICE", "NEEDS_REVIEW", "nan"}

# master column keys
K_AR = "اسم التحليل بالعربية"
K_EN = "names"
K_BENEFIT = "فائدة التحليل"
K_PRICE = "السعر"
K_COMPLEMENT = "التحاليل المكملة"
K_FASTING = "fasting_required"
K_FASTING_H = "fasting_hours"
K_PREP = "التحضير قبل التحليل"
K_NOTES = "special_notes"
K_AVAIL = "is_available"
K_TAT = "TAT"
K_BESTFOR = "best_for"
K_COMPARE = "test_comparison"
K_PKG_ID = "package_id"
K_PKG_NAMES = "package_names"
K_SRC = "data_source"


class ContextBuilder:
    """Builds intent-specific grounded context strings."""

    def build_context(self, tests: list[dict], intent: QueryIntent,
                      include_price: bool = False, extra: Optional[dict] = None,
                      packages: Optional[list[dict]] = None,
                      upsell_packages: Optional[list[dict]] = None) -> str:
        """Dispatch to the intent-specific builder. Returns '' when nothing to say."""
        packages = packages or []
        upsell_packages = upsell_packages or []
        if intent == QueryIntent.PACKAGE_INQUIRY:
            return self._build_package_context(packages, include_price)
        if intent == QueryIntent.SYMPTOM_QUERY:
            base = self._build_symptom_context(tests)
        elif intent == QueryIntent.FASTING_PREP:
            base = self._build_fasting_context(tests)
        elif intent == QueryIntent.AVAILABILITY:
            base = self._build_availability_context(tests)
        elif intent == QueryIntent.AMBIGUOUS:
            base = self._build_disambiguation_context(tests, extra)
        else:  # TEST_LOOKUP / GENERAL
            base = self._build_test_context(tests, include_price)
        if upsell_packages:
            up = self._build_upsell_context(tests, upsell_packages, include_price)
            if up:
                base = (base + "\n\n" + up) if base else up
        return base

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _name(t: dict) -> str:
        ar = str(t.get(K_AR, "")).strip()
        en = str(t.get(K_EN, "")).strip()
        return f"{ar} ({en})" if en else ar

    @staticmethod
    def _safety_check(field_value: str, data_source: str) -> str:
        """Return a safe value for clinical fields, never asserting unverified data."""
        v = str(field_value).strip()
        if not v or v.startswith("NEEDS"):
            return SAFE_FALLBACK
        if "AI_GENERATED" in str(data_source):
            return f"{v} (بحاجة لتأكيد المختبر)"
        return v

    @classmethod
    def _price_line(cls, t: dict, include_price: bool) -> str:
        if not include_price:
            return "السعر: سيتواصل معك فريقنا لإعطائك السعر الدقيق"
        price = str(t.get(K_PRICE, "")).strip()
        if price in PRICE_PLACEHOLDERS:
            return "السعر: سيتواصل معك فريقنا لإعطائك السعر الدقيق"
        return f"السعر: {price} ريال"

    # ------------------------------------------------------------ builders
    def _build_test_context(self, tests: list[dict], include_price: bool) -> str:
        blocks = []
        for t in tests[:5]:
            lines = [f"- التحليل: {self._name(t)}"]
            if str(t.get(K_BENEFIT, "")).strip():
                lines.append(f"  الفائدة: {t[K_BENEFIT]}")
            comp = str(t.get(K_COMPLEMENT, "")).strip()
            if comp and not comp.startswith("NEEDS"):
                lines.append(f"  تحاليل مكملة مقترحة: {comp}")
            lines.append("  " + self._price_line(t, include_price))
            blocks.append("\n".join(lines))
        return "\n".join(blocks)

    def _build_symptom_context(self, tests: list[dict]) -> str:
        if not tests:
            return ""
        lines = ["تحاليل قد تكون مناسبة بناءً على الأعراض المذكورة (للتعريف فقط، دون تشخيص):"]
        for t in tests[:6]:
            b = str(t.get(K_BENEFIT, "")).strip()
            lines.append(f"- {self._name(t)}" + (f": {b}" if b else ""))
        lines.append("لإتمام الحجز أو معرفة التفاصيل، يمكن طلب رقم جوال العميل.")
        return "\n".join(lines)

    def _build_fasting_context(self, tests: list[dict]) -> str:
        blocks = []
        for t in tests[:4]:
            fasting = str(t.get(K_FASTING, "")).strip() or "غير محدد"
            hours = str(t.get(K_FASTING_H, "")).strip()
            prep = str(t.get(K_PREP, "")).strip()
            notes = str(t.get(K_NOTES, "")).strip()
            lines = [f"- التحليل: {self._name(t)}", f"  يتطلب صيام: {fasting}"]
            if hours and hours != "0":
                lines.append(f"  ساعات الصيام: {hours}")
            if prep and not prep.startswith("NEEDS"):
                lines.append(f"  التحضير: {prep}")
            if notes and not notes.startswith("NEEDS"):
                lines.append(f"  ملاحظات: {notes}")
            blocks.append("\n".join(lines))
        return "\n".join(blocks)

    def _build_availability_context(self, tests: list[dict]) -> str:
        blocks = []
        for t in tests[:5]:
            avail = str(t.get(K_AVAIL, "")).strip()
            avail = SAFE_FALLBACK if (not avail or avail.startswith("NEEDS")) else avail
            tat = str(t.get(K_TAT, "")).strip()
            line = f"- التحليل: {self._name(t)} | التوفر: {avail}"
            if tat and not tat.startswith("NEEDS"):
                line += f" | وقت الاستلام التقريبي: {tat}"
            blocks.append(line)
        return "\n".join(blocks)

    def _build_disambiguation_context(self, tests: list[dict], extra: Optional[dict]) -> str:
        lines = []
        if extra and extra.get("group"):
            lines.append(f"الاستفسار يحتمل أكثر من تحليل ضمن {extra['group']}.")
            if extra.get("decision_helper"):
                lines.append(f"سؤال توضيحي مقترح: {extra['decision_helper']}")
        lines.append("الخيارات المتاحة:")
        for t in tests[:6]:
            bf = str(t.get(K_BESTFOR, "")).strip()
            lines.append(f"- {self._name(t)}" + (f" — {bf}" if bf and not bf.startswith('NEEDS') else ""))
        return "\n".join(lines)

    @staticmethod
    def _pkg_name(p: dict) -> str:
        ar = str(p.get("package_name_ar", "")).strip()
        en = str(p.get("package_name_en", "")).strip()
        return f"{ar} ({en})" if en and not en.startswith("NEEDS") else ar

    def _pkg_price_line(self, p: dict, include_price: bool) -> str:
        if not include_price:
            return "السعر: سيتواصل معك فريقنا لإعطائك السعر الدقيق"
        price = str(p.get("price", "")).strip()
        if price in PRICE_PLACEHOLDERS:
            return "السعر: سيتواصل معك فريقنا لإعطائك السعر الدقيق"
        line = f"السعر: {price} ريال"
        disc = str(p.get("discount_vs_individual", "")).strip()
        if disc and not disc.startswith("NEEDS"):
            line += f" (توفير {disc} مقارنة بشرائها منفردة)"
        return line

    def _build_package_context(self, packages: list[dict], include_price: bool = False) -> str:
        if not packages:
            return "تتوفر لدى مختبر وريد باقات صحية متنوعة؛ يسعدنا مساعدتك في اختيار الأنسب. شاركنا ما تود فحصه."
        blocks = []
        for p in packages[:5]:
            lines = [f"- الباقة: {self._pkg_name(p)}"]
            tc = str(p.get("test_count", "")).strip()
            names = str(p.get("test_names_ar", "")).strip()
            if names and not names.startswith("NEEDS"):
                parts = [x.strip() for x in names.split("،") if x.strip()]
                shown = "، ".join(parts[:5])
                more = f" و{len(parts) - 5} تحليل آخر" if len(parts) > 5 else ""
                lines.append(f"  تشمل {tc or len(parts)} تحاليل: {shown}{more}")
            bf = str(p.get("best_for", "")).strip()
            if bf and not bf.startswith("NEEDS"):
                lines.append(f"  مناسبة لـ: {bf}")
            fr = str(p.get("fasting_required", "")).strip()
            if fr and not fr.startswith("NEEDS"):
                fh = str(p.get("fasting_hours", "")).strip()
                suffix = f" ({fh} ساعة)" if fh and fh not in ("0", "NEEDS_REVIEW") else ""
                lines.append(f"  الصيام: {fr}{suffix}")
            lines.append("  " + self._pkg_price_line(p, include_price))
            blocks.append("\n".join(lines))
        return "باقات ذات صلة:\n" + "\n".join(blocks)

    def _build_upsell_context(self, tests: list[dict], packages: list[dict],
                              include_price: bool = False) -> str:
        if not packages:
            return ""
        p = packages[0]
        line = f"ملاحظة: هذه التحاليل متوفرة ضمن «{self._pkg_name(p)}»"
        disc = str(p.get("discount_vs_individual", "")).strip()
        if disc and not disc.startswith("NEEDS"):
            line += f" بسعر أوفر (توفير {disc}) من شرائها منفردة"
        else:
            line += "، وقد تكون أوفر من شراء التحاليل منفردة"
        line += ". يمكن طلب رقم جوال العميل لإتمام الحجز."
        return line


# ---------------------------------------------------------------------------
# Grounding / hallucination guards
# ---------------------------------------------------------------------------

def is_context_sufficient(context: str) -> bool:
    """Return False when the retrieved context is empty or too thin to answer.

    Used by callers to decide whether to answer from the context or fall back
    to a safe "contact us" message instead of letting the model improvise.
    """
    if not context or len(context.strip()) < 50:
        return False
    if "NEEDS_REVIEW" in context and len(context) < 100:
        return False
    return True


def get_fallback_response(query_type: str = "general") -> str:
    """Safe, grounded fallback when no sufficient context is available."""
    return (
        "ما عندي معلومات كافية عن هذا الموضوع في قاعدة بياناتنا 🔍\n\n"
        "للمساعدة الكاملة، تواصل مع فريقنا:\n"
        "📞 8001221220 (مجاني)\n"
        "أو اكتب رقمك وسيتواصلون معك فوراً"
    )


def format_context_for_prompt(tests: list[dict], intent: QueryIntent) -> str:
    """Concise, intent-shaped context so the model gets structured input, not a wall
    of text (which makes it over-explain). Never includes price — price is disclosed
    only after phone capture, via build_context().
    """
    if not tests:
        return ""

    def _nm(t: dict) -> str:
        ar = str(t.get(K_AR, "")).strip()
        en = str(t.get(K_EN, "")).strip()
        return f"{ar} ({en})" if en and not en.startswith("NEEDS") else ar

    def _avail_ok(t: dict) -> bool:
        v = str(t.get(K_AVAIL, "")).strip().lower()
        return ("yes" in v) or ("متاح" in v)

    if intent == QueryIntent.FASTING_PREP:
        out = []
        for t in tests[:3]:
            fasting = str(t.get(K_FASTING, "")).strip() or "غير محدد"
            hours = str(t.get(K_FASTING_H, "")).strip()
            prep = str(t.get(K_PREP, "")).strip()
            line = f"- {_nm(t)}: صيام {fasting}"
            if hours and hours not in ("0", "NEEDS_REVIEW"):
                line += f" ({hours} ساعة)"
            if prep and not prep.startswith("NEEDS"):
                line += f" — {prep}"
            out.append(line)
        return "\n".join(out)

    if intent == QueryIntent.SYMPTOM_QUERY:
        out = ["تحاليل مقترحة (للتعريف فقط، دون تشخيص):"]
        for t in tests[:3]:
            b = str(t.get(K_BENEFIT, "")).strip()
            out.append(f"- {_nm(t)}" + (f": {b[:80]}" if b and not b.startswith("NEEDS") else ""))
        return "\n".join(out)

    if intent == QueryIntent.AVAILABILITY:
        out = []
        for t in tests[:3]:
            avail = "متاح" if _avail_ok(t) else (str(t.get(K_AVAIL, "")).strip() or "غير محدد")
            out.append(f"- {_nm(t)} | التوفر: {avail}")
        return "\n".join(out)

    # TEST_LOOKUP / GENERAL
    out = []
    for t in tests[:3]:
        line = f"- {_nm(t)}"
        if _avail_ok(t):
            line += " ✅"
        b = str(t.get(K_BENEFIT, "")).strip()
        if b and not b.startswith("NEEDS"):
            line += f": {b[:90]}"
        out.append(line)
    return "\n".join(out)
