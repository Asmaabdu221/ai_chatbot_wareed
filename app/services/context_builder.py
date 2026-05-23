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
                      include_price: bool = False, extra: Optional[dict] = None) -> str:
        """Dispatch to the intent-specific builder. Returns '' when nothing to say."""
        if intent == QueryIntent.SYMPTOM_QUERY:
            return self._build_symptom_context(tests)
        if intent == QueryIntent.FASTING_PREP:
            return self._build_fasting_context(tests)
        if intent == QueryIntent.AVAILABILITY:
            return self._build_availability_context(tests)
        if intent == QueryIntent.AMBIGUOUS:
            return self._build_disambiguation_context(tests, extra)
        if intent == QueryIntent.PACKAGE_INQUIRY:
            return self._build_package_context(tests)
        # TEST_LOOKUP / GENERAL
        return self._build_test_context(tests, include_price)

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

    def _build_package_context(self, tests: list[dict]) -> str:
        pkgs = []
        for t in tests[:6]:
            names = str(t.get(K_PKG_NAMES, "")).strip()
            if names and not names.startswith("NEEDS"):
                pkgs.append(f"- {self._name(t)} ضمن الباقات: {names}")
        if not pkgs:
            return "تتوفر لدى مختبر وريد باقات صحية متنوعة؛ يسعدنا مساعدتك في اختيار الأنسب."
        return "باقات ذات صلة:\n" + "\n".join(pkgs)
