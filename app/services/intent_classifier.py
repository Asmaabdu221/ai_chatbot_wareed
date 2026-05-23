"""
Intent classifier for the Lab RAG v2 pipeline.

Classifies an incoming query into one of a small set of intents using fast,
free keyword/pattern matching over normalized Arabic text. An optional LLM
fallback hook exists but is disabled by default (keyword-only) to avoid API
cost and latency.
"""

from __future__ import annotations

from enum import Enum

from app.utils.arabic_normalizer import normalize


class QueryIntent(Enum):
    """Supported query intents."""
    TEST_LOOKUP = "test_lookup"          # "كم سعر تحليل السكر"
    SYMPTOM_QUERY = "symptom_query"      # "عندي تعب وشحوب"
    FASTING_PREP = "fasting_prep"        # "هل لازم أصوم"
    AVAILABILITY = "availability"        # "هل هذا التحليل متوفر"
    PACKAGE_INQUIRY = "package_inquiry"  # "عندكم باقات"
    AMBIGUOUS = "ambiguous"              # "أريد تحليل حديد"
    GENERAL = "general"                  # greeting / other


class IntentClassifier:
    """Keyword-first intent classifier (LLM fallback optional)."""

    SYMPTOM_KEYWORDS = [
        "تعب", "خمول", "صداع", "الم", "ألم", "حمى", "غثيان", "شحوب", "دوخه",
        "دوخة", "ضعف", "عندي", "اشعر", "أشعر", "يؤلمني", "يالمني", "وجع",
        "ارهاق", "إرهاق", "تساقط", "نحافه", "سمنه", "خفقان",
    ]
    FASTING_KEYWORDS = ["صيام", "صوم", "اصوم", "أصوم", "افطر", "أفطر", "اكل", "أكل", "يشترط", "تحضير", "استعداد"]
    AVAILABILITY_KEYWORDS = ["متوفر", "متاح", "موجود", "عندكم", "عندك", "يتوفر", "هل يوجد", "تسوون", "تعملون", "تجرون"]
    PACKAGE_KEYWORDS = ["باقه", "باقة", "باقات", "عرض", "عروض", "بكج", "package", "حزمه", "حزمة"]
    # Stems that frequently map to several tests -> ambiguous, needs clarification.
    AMBIGUOUS_STEMS = ["حديد", "فيتامين", "الغده", "الغدة", "السكر", "هرمون", "iron", "vitamin", "thyroid"]
    GREETING_KEYWORDS = ["سلام", "مرحبا", "هلا", "اهلا", "أهلا", "صباح", "مساء", "hi", "hello", "شكرا"]

    def __init__(self, use_llm_fallback: bool = False) -> None:
        self.use_llm_fallback = use_llm_fallback

    @staticmethod
    def _has_any(text: str, keywords: list[str]) -> bool:
        return any(k in text for k in keywords)

    def classify(self, query: str) -> QueryIntent:
        """Classify a query into a :class:`QueryIntent`.

        Order matters: explicit signals (fasting/availability/package/symptom)
        are checked before the ambiguous-stem and generic fallbacks.
        """
        norm = normalize(query)
        if not norm:
            return QueryIntent.GENERAL

        # Greeting / smalltalk (only if short and no test signal)
        if self._has_any(norm, self.GREETING_KEYWORDS) and len(norm.split()) <= 3:
            return QueryIntent.GENERAL

        if self._has_any(norm, self.FASTING_KEYWORDS):
            return QueryIntent.FASTING_PREP
        if self._has_any(norm, self.PACKAGE_KEYWORDS):
            return QueryIntent.PACKAGE_INQUIRY
        if self._has_any(norm, self.AVAILABILITY_KEYWORDS):
            return QueryIntent.AVAILABILITY
        if self._has_any(norm, self.SYMPTOM_KEYWORDS):
            return QueryIntent.SYMPTOM_QUERY

        # Ambiguous stems with no disambiguating second token -> AMBIGUOUS
        if self._has_any(norm, self.AMBIGUOUS_STEMS):
            return QueryIntent.AMBIGUOUS

        if self.use_llm_fallback:
            llm = self._classify_with_llm(query)
            if llm is not None:
                return llm

        # Default: treat as a test lookup (the synonym layer will resolve or miss).
        return QueryIntent.TEST_LOOKUP

    def _classify_with_llm(self, query: str) -> QueryIntent | None:
        """Optional LLM fallback (disabled by default). Returns None on any issue."""
        try:
            from app.services.openai_service import openai_service  # lazy
            if getattr(openai_service, "client", None) is None:
                return None
            labels = ", ".join(i.value for i in QueryIntent)
            resp = openai_service.client.chat.completions.create(
                model=openai_service.model,
                messages=[
                    {"role": "system", "content": f"Classify the user query into exactly one label from: {labels}. Reply with the label only."},
                    {"role": "user", "content": query},
                ],
                max_tokens=8,
                temperature=0,
            )
            raw = (resp.choices[0].message.content or "").strip().lower()
            for i in QueryIntent:
                if i.value in raw:
                    return i
        except Exception:
            return None
        return None


_classifier: IntentClassifier | None = None


def get_intent_classifier() -> IntentClassifier:
    """Return the process-wide singleton classifier."""
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier()
    return _classifier
