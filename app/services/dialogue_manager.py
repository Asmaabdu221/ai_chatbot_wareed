"""
Dialogue Manager — Phase 1 (MVP).

What this does
--------------
1. Tracks which test entity is active in the conversation (after a matched
   runtime_router response).
2. Detects short follow-up messages that have no domain keywords and rewrites
   them to include the active entity name so the runtime router can resolve them.

Scope (Phase 1)
---------------
- Test domain only.  Branch / package rewrites deferred to Phase 2.
- /api/chat endpoint only.
- Purely additive — does NOT modify any existing routing logic.

Integration points in chat.py
------------------------------
  BEFORE route_runtime_message():
      state = dm.load_state(conversation_id)
      rewritten = dm.resolve_followup(request.message, state)
      # pass rewritten to route_runtime_message

  AFTER route_runtime_message() returns matched=True:
      dm.update_after_response(conversation_id, runtime_result)
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from app.services.dialogue_state import get_dialogue_state, set_dialogue_state

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Arabic normalizer — soft-import so the module loads even in isolation.
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    try:
        from app.services.runtime.text_normalizer import normalize_for_match
        return normalize_for_match(text)
    except Exception:
        return text.strip()


def _norm_for_match(text: str) -> str:
    """Normalize text and strip punctuation for stable short-followup matching."""
    n = _norm(text)
    if not n:
        return ""
    n = re.sub(r"[؟?\.,!،:;\"'`()\[\]{}\-_/\\]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _basic_match_key(text: str) -> str:
    v = str(text or "").strip().lower()
    v = re.sub(r"[؟?\.,!،:;\"'`()\[\]{}\-_/\\]+", " ", v)
    return re.sub(r"\s+", " ", v).strip()


# ---------------------------------------------------------------------------
# Numeric guard — "1", "2", "١" etc. must NEVER be rewritten.
# These are branch / test selection inputs handled by selection_state.
# ---------------------------------------------------------------------------
_NUMERIC_RE = re.compile(r"^[٠-٩\d]{1,2}$")


# ---------------------------------------------------------------------------
# Domain-switch blockers.
# If the user message contains any of these the conversation has moved to a
# new topic — do NOT rewrite as a follow-up on the active test.
# ---------------------------------------------------------------------------
_DOMAIN_BLOCKERS: tuple[str, ...] = (
    "فرع", "فروع", "فروعكم",
    "موقع", "عنوان", "عنوانكم",
    "باقة", "باقه", "باقات", "package",
    "مرحبا", "اهلا", "أهلا", "السلام",
)


# ---------------------------------------------------------------------------
# Follow-up phrase catalogue.
#
# Each entry: (tuple_of_Arabic_phrases, rewrite_template)
# {name} is substituted with active_entity_name at call time.
# Phrases are matched after Arabic normalisation (same normalizer the router
# uses), so diacritic / alef variants are handled transparently.
# ---------------------------------------------------------------------------
_CATALOGUE: list[tuple[tuple[str, ...], str]] = [
    # ---- Usage / purpose ----
    (
        (
            "لماذا يستخدم", "ليش يستخدم",
            "ايش استخدامه", "وش استخدامه",
            "يستخدم لايش", "يستخدم لوش",
            "متى يستخدم", "متى يطلب",
        ),
        "لماذا يستخدم تحليل {name}",
    ),
    # ---- Benefit / what it measures ----
    (
        (
            "فائدته", "ايش فائدته", "وش فائدته", "ما فائدته",
            "فائدة", "ايش فائدة", "وش فائدة",
            "يفيد في ايش", "يفيد في وش",
            "ايش يفحص", "وش يفحص", "ما يفحص",
            "يفحص ايش", "يفحص وش",
            "ايش يقيس", "وش يقيس",
        ),
        "ما فائدة تحليل {name}",
    ),
    # ---- Fasting ----
    (
        (
            "صيام",
            "يحتاج صيام", "هل يحتاج صيام",
            "لازم صيام", "هل لازم صيام",
            "يبيله صيام", "هل يبيله صيام",
            "كم ساعة الصيام", "كم ساعه الصيام",
            "صيام ولا لا",
        ),
        "هل تحليل {name} يحتاج صيام",
    ),
    # ---- Price ----
    (
        (
            "سعره", "سعرها",
            "كم سعره", "كم سعرها",
            "بكم", "كم تكلف", "كم تكلفه", "تكلف كم",
            "السعر", "سعر",
        ),
        "كم سعر تحليل {name}",
    ),
    # ---- Sample type ----
    (
        (
            "نوع العينة", "نوع عينة",
            "العينة", "نوع السمبل", "نوع الفحص",
        ),
        "نوع عينة تحليل {name}",
    ),
    # ---- Preparation ----
    (
        (
            "التحضير", "تحضير",
            "استعداد", "كيف أستعد", "كيف استعد",
            "وش لازم", "ايش لازم",
            "قبل التحليل", "قبل الفحص",
            "ايش اسوي", "وش اسوي", "كيف اتحضر",
        ),
        "تحضير تحليل {name}",
    ),
    # ---- Elaboration / definition ----
    (
        (
            "اشرح", "اشرح أكثر", "اشرح اكثر",
            "وضح", "وضح أكثر",
            "فصّل", "فصل",
            "تفاصيل", "التفاصيل",
            "ايش هو", "وش هو", "ما هو", "ما هي",
            "يعني ايش", "يعني وش",
            "تعريف",
        ),
        "اشرح تحليل {name}",
    ),
    # ---- Normal range ----
    (
        (
            "المعدل الطبيعي", "معدل طبيعي",
            "المدى الطبيعي", "النطاق الطبيعي",
            "القيمة الطبيعية",
        ),
        "المعدل الطبيعي لتحليل {name}",
    ),
    # ---- Complementary tests ----
    (
        (
            "التحاليل المكملة", "التحاليل المصاحبة",
            "مكملة", "مكمل",
        ),
        "التحاليل المكملة لتحليل {name}",
    ),
]

_PACKAGE_CATALOGUE: list[tuple[tuple[str, ...], str]] = [
    (("وش تشمل", "ايش تشمل", "ماذا تشمل"), "ماذا تشمل باقة {name}"),
    (("كم سعرها", "سعرها", "كم السعر", "السعر"), "كم سعر باقة {name}"),
    (("مناسبة لمين", "مناسبه لمين", "تناسب مين", "لمن تناسب"), "لمن تناسب باقة {name}"),
]

_BRANCH_CATALOGUE: list[tuple[tuple[str, ...], str]] = [
    (("ارسل اللوكيشن", "أرسل اللوكيشن", "وين موقعه", "وين موقعها"), "موقع فرع {name}"),
    (("متى يفتح", "متى يفتح الفرع", "دوام الفرع"), "دوام فرع {name}"),
    (("رقم الفرع",), "رقم فرع {name}"),
]

_SYMPTOM_FOLLOWUP_CATALOGUE: list[tuple[tuple[str, ...], str]] = [
    (("ايش التحاليل", "وش التحاليل", "ايش تنصح", "وش تنصح", "طيب ايش اسوي"), "اقترح تحاليل مناسبة للأعراض: {symptoms}"),
]

_RESULT_FOLLOWUP_CATALOGUE: list[tuple[tuple[str, ...], str]] = [
    (("هل هذا طبيعي",), "هل نتيجة {test} {value} طبيعية؟"),
    (("هل هذا منخفض",), "هل نتيجة {test} {value} منخفضة؟"),
    (("هل هذا مرتفع",), "هل نتيجة {test} {value} مرتفعة؟"),
    (("ماذا يعني",), "ماذا تعني نتيجة {test} {value}؟"),
]


def _build_lookup() -> dict[str, str]:
    """Return {normalised_phrase: template} from the catalogue."""
    result: dict[str, str] = {}
    for phrases, template in _CATALOGUE:
        for phrase in phrases:
            key = _norm(phrase)
            if key:
                result[key] = template
    return result


# Built once at module import time.
_LOOKUP: dict[str, str] = _build_lookup()
_PACKAGE_LOOKUP: dict[str, str] = {
    _norm(p): t for phrases, t in _PACKAGE_CATALOGUE for p in phrases if _norm(p)
}
_BRANCH_LOOKUP: dict[str, str] = {
    _norm(p): t for phrases, t in _BRANCH_CATALOGUE for p in phrases if _norm(p)
}
_SYMPTOM_LOOKUP: dict[str, str] = {
    _norm(p): t for phrases, t in _SYMPTOM_FOLLOWUP_CATALOGUE for p in phrases if _norm(p)
}
_RESULT_LOOKUP: dict[str, str] = {
    _norm(p): t for phrases, t in _RESULT_FOLLOWUP_CATALOGUE for p in phrases if _norm(p)
}
_RESULT_CONTEXT_KEYS = {"هل هذا طبيعي", "هل هذا منخفض", "هل هذا مرتفع", "ماذا يعني"}
_SYMPTOM_CONTEXT_KEYS = {"ايش التحاليل", "وش التحاليل", "ايش تنصح", "وش تنصح", "طيب ايش اسوي"}

# A message longer than this many words is likely a full new question, not a
# short follow-up, so we skip rewriting.
_MAX_FOLLOWUP_WORDS = 6
_SHORT_FOLLOWUP_MAX_WORDS = 3

_SYMPTOM_CONTEXT_STOPWORDS = {
    _norm(v)
    for v in (
        "عندي", "عند", "في", "من", "مع", "عن", "ايش", "وش", "طيب", "اللي", "تنصح", "اسوي",
        "تحليل", "تحاليل", "فحص", "نتيجة",
    )
}


def _is_clearly_new_question(text_norm: str) -> bool:
    words = [w for w in text_norm.split() if w]
    if len(words) > _MAX_FOLLOWUP_WORDS:
        return True
    starters = ("ابغى", "ابي", "أبغى", "أبي", "اريد", "أريد", "عندي", "عندنا")
    return len(words) >= 4 and any(s in text_norm for s in starters)


def _detect_short_followup_intent_for_test(text_norm: str) -> str | None:
    """
    Generic short follow-up intent detection for test domain.
    Returns: one of price|preparation|sample|general_info or None.
    """
    tokens = [t for t in text_norm.split() if t]
    if not tokens or len(tokens) > _SHORT_FOLLOWUP_MAX_WORDS:
        return None

    price_terms = {"بكم", "كم", "السعر", "سعر", "كم سعر"}
    prep_terms = {"صيام", "تحضير", "يحتاج صيام", "كيف التحضير"}
    sample_terms = {"العينة", "العينه", "نوع العينة", "نوع العينه"}
    info_terms = {"اشرح", "وش هو", "ما هو", "ماهو"}

    padded = f" {text_norm} "
    if any((term == text_norm) or (f" {term} " in padded) for term in price_terms):
        return "price"
    if any((term == text_norm) or (f" {term} " in padded) for term in prep_terms):
        return "preparation"
    if any((term == text_norm) or (f" {term} " in padded) for term in sample_terms):
        return "sample"
    if any((term == text_norm) or (f" {term} " in padded) for term in info_terms):
        return "general_info"
    return None


def _extract_symptom_keywords(text: str) -> list[str]:
    text_norm = _norm(text)
    if not text_norm:
        return []
    out: list[str] = []
    for token in [t.strip() for t in re.split(r"[,\s،]+", text_norm) if t.strip()]:
        if len(token) <= 1 or token in _SYMPTOM_CONTEXT_STOPWORDS:
            continue
        if token not in out:
            out.append(token)
    return out


def _extract_result_value(text: str) -> str | None:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text or "")
    return m.group(0) if m else None


def _extract_result_test_name(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    # e.g. "Vitamin D نتيجتي 10"
    m = re.search(r"^(.*?)\s+(?:نتيجتي|نتيجة|النتيجة)\b", raw, flags=re.IGNORECASE)
    if m:
        name = m.group(1).strip(" -:،,.؟?")
        return name or None
    # e.g. "نتيجة Vitamin D 10"
    m = re.search(r"(?:نتيجتي|نتيجة|النتيجة)\s+([A-Za-z0-9\u0600-\u06FF\-\s]{2,})", raw, flags=re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        candidate = re.sub(r"\s+[-+]?\d+(?:\.\d+)?\s*$", "", candidate).strip(" -:،,.؟?")
        return candidate or None
    return None


# ---------------------------------------------------------------------------
# DialogueManager
# ---------------------------------------------------------------------------

class DialogueManager:
    """Phase 1 minimal Dialogue Manager for /api/chat."""

    # ------------------------------------------------------------------
    def load_state(self, conversation_id: str | UUID) -> dict[str, Any]:
        return get_dialogue_state(conversation_id)

    # ------------------------------------------------------------------
    def save_state(
        self,
        conversation_id: str | UUID,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        return set_dialogue_state(conversation_id, state)

    # ------------------------------------------------------------------
    def update_after_response(
        self,
        conversation_id: str | UUID,
        runtime_result: dict[str, Any],
        user_text: str = "",
    ) -> None:
        """
        Called after runtime_router returns matched=True.

        Extracts domain + entity name from the result and persists them so
        the next turn can use them for follow-up rewriting.

        No-op when:
        - runtime_result is not a dict, or matched is False.
        - Source is not a recognised domain (tests / branches / packages).
        - Entity name cannot be extracted from meta.
        """
        if not isinstance(runtime_result, dict):
            return
        if not bool(runtime_result.get("matched")):
            return

        source = str(runtime_result.get("source") or "").strip().lower()
        meta = dict(runtime_result.get("meta") or {})

        domain = "none"
        entity_name: str | None = None
        entity_from_result = str(runtime_result.get("entity_name") or "").strip()
        active_symptoms: list[str] = []
        active_result_test_name: str | None = None
        active_result_value: str | None = None

        if source in {"tests", "tests_business"}:
            raw = entity_from_result or str(meta.get("matched_test_name") or "").strip()
            if raw:
                domain = "test"
                entity_name = raw

        elif source == "branches":
            raw = entity_from_result or str(meta.get("branch_name") or "").strip()
            if raw:
                domain = "branch"
                entity_name = raw

        elif source in {"packages", "packages_business"}:
            raw = entity_from_result or str(meta.get("matched_package_name") or "").strip()
            if raw:
                domain = "package"
                entity_name = raw

        elif source in {"symptoms", "symptoms_engine"}:
            raw_symptoms = meta.get("symptoms")
            if isinstance(raw_symptoms, list):
                active_symptoms = [str(v).strip() for v in raw_symptoms if str(v).strip()]
            elif isinstance(raw_symptoms, str) and raw_symptoms.strip():
                active_symptoms = [raw_symptoms.strip()]
            if not active_symptoms:
                active_symptoms = _extract_symptom_keywords(user_text)
            if active_symptoms:
                domain = "symptom"
                entity_name = ", ".join(active_symptoms)

        elif source in {"results", "results_engine"}:
            active_result_test_name = (
                entity_from_result
                or str(meta.get("test_name") or "").strip()
                or str(meta.get("matched_test_name") or "").strip()
            )
            if not active_result_test_name:
                active_result_test_name = _extract_result_test_name(user_text)
            active_result_value = (
                str(meta.get("result_value") or "").strip()
                or str(meta.get("value") or "").strip()
                or str(meta.get("numeric_value") or "").strip()
            )
            if not active_result_value:
                active_result_value = _extract_result_value(user_text)
            if active_result_test_name and active_result_value:
                domain = "result"
                entity_name = active_result_test_name

        if domain == "none" or not entity_name:
            logger.info(
                "dialogue_manager | skipped | reason=state_update_no_entity | source=%s | conversation_id=%.8s",
                source,
                str(conversation_id),
            )
            return

        current = self.load_state(conversation_id)
        current["active_domain"] = domain
        current["active_entity_name"] = entity_name
        if domain == "package":
            current["active_package_name"] = entity_name
        if domain == "branch":
            current["active_branch_name"] = entity_name
        if domain == "symptom":
            current["active_symptoms"] = active_symptoms
        if domain == "result":
            current["active_result_test_name"] = active_result_test_name
            current["active_result_value"] = active_result_value
        self.save_state(conversation_id, current)

        logger.info(
            "dialogue_manager | state_updated | domain=%s | entity=%s | conversation_id=%.8s",
            domain,
            entity_name,
            str(conversation_id),
        )

    # ------------------------------------------------------------------
    def resolve_followup(
        self,
        user_text: str,
        state: dict[str, Any],
    ) -> str:
        """
        If the message is a short follow-up about the active test entity,
        return a rewritten query that includes the entity name.
        Returns the original text unchanged when any guard fails.

        Guards (all must pass for a rewrite to happen):
          1. active_domain == "test" and active_entity_name is set.
          2. Message is not a numeric input (1-2 digits) — selection guard.
          3. Message contains no domain-switch keywords.
          4. Message contains no explicit new entity reference ("تحليل X").
          5. Message is at most _MAX_FOLLOWUP_WORDS words long.
          6. Normalised message matches a phrase in _LOOKUP exactly.
        """
        text = (user_text or "").strip()
        if not text:
            return text

        if not isinstance(state, dict) or not state:
            logger.info("dialogue_manager | skipped | reason=no_state")
            return text

        active_domain = str(state.get("active_domain") or "none").strip()
        active_entity = str(state.get("active_entity_name") or "").strip()

        if active_domain not in {"test", "package", "branch", "symptom", "result"}:
            logger.info("dialogue_manager | skipped | reason=no_active_domain")
            return text
        if active_domain in {"test", "package", "branch"} and not active_entity:
            logger.info("dialogue_manager | skipped | reason=no_active_entity")
            return text

        # Guard 1 — numeric selection inputs must pass through untouched
        if _NUMERIC_RE.match(text):
            logger.info("dialogue_manager | skipped | reason=numeric_input")
            return text

        text_norm = _norm_for_match(text)

        # Guard 2 — domain-switch keywords present
        if self._has_domain_blocker(text_norm):
            logger.info("dialogue_manager | skipped | reason=domain_blocker")
            return text

        # Guard 3 — message already names a different entity explicitly
        if re.search(r"\u062a\u062d\u0644\u064a\u0644\s+\S", text_norm):
            logger.info("dialogue_manager | skipped | reason=explicit_entity")
            return text

        # Guard 4 — too long/new question to be a plain follow-up
        if _is_clearly_new_question(text_norm):
            logger.info("dialogue_manager | skipped | reason=new_or_long_question")
            return text

        # Generic short follow-up rewrite for active test context.
        if active_domain == "test":
            short_intent = _detect_short_followup_intent_for_test(text_norm)
            if short_intent:
                if short_intent == "price":
                    rewritten = f"كم سعر {active_entity}"
                elif short_intent == "preparation":
                    if "صيام" in text_norm:
                        rewritten = f"هل يحتاج {active_entity} صيام"
                    else:
                        rewritten = f"كيف التحضير ل {active_entity}"
                elif short_intent == "sample":
                    rewritten = f"ما نوع عينة {active_entity}"
                else:
                    rewritten = f"اشرح تحليل {active_entity}"

                logger.info(
                    "dialogue_manager | followup_detected"
                    " | active_domain=%s | original_text=%r | rewritten_text=%r | conversation_id=%.8s",
                    active_domain,
                    text,
                    rewritten,
                    str(state.get("conversation_id", ""))[:8],
                )
                return rewritten

        template: str | None = None
        entity_for_domain = active_entity
        if active_domain == "package":
            entity_for_domain = str(state.get("active_package_name") or "").strip()
            template = _PACKAGE_LOOKUP.get(text_norm)
        elif active_domain == "branch":
            entity_for_domain = str(state.get("active_branch_name") or "").strip()
            template = _BRANCH_LOOKUP.get(text_norm)
        elif active_domain == "symptom":
            symptoms = state.get("active_symptoms") or []
            if isinstance(symptoms, list):
                symptoms = [str(v).strip() for v in symptoms if str(v).strip()]
            else:
                symptoms = []
            template = _SYMPTOM_LOOKUP.get(text_norm)
            if template and symptoms:
                rewritten = template.replace("{symptoms}", "، ".join(symptoms))
                logger.info(
                    "dialogue_manager | followup_rewrite"
                    " | original=%r | rewritten=%r | entity=%s | conversation_id=%.8s",
                    text,
                    rewritten,
                    "، ".join(symptoms),
                    str(state.get("conversation_id", ""))[:8],
                )
                return rewritten
            logger.info("dialogue_manager | skipped | reason=missing_symptom_context")
            return text
        elif active_domain == "result":
            result_test = str(state.get("active_result_test_name") or "").strip()
            result_value = str(state.get("active_result_value") or "").strip()
            template = _RESULT_LOOKUP.get(text_norm)
            if not template:
                logger.info("dialogue_manager | skipped | reason=no_template_match")
                return text
            if not result_test or not result_value:
                logger.info("dialogue_manager | skipped | reason=missing_result_context")
                return text
            rewritten = template.replace("{test}", result_test).replace("{value}", result_value)
            logger.info(
                "dialogue_manager | followup_rewrite"
                " | original=%r | rewritten=%r | entity=%s | conversation_id=%.8s",
                text,
                rewritten,
                result_test,
                str(state.get("conversation_id", ""))[:8],
            )
            return rewritten
        else:
            template = _LOOKUP.get(text_norm)

        if not entity_for_domain:
            logger.info("dialogue_manager | skipped | reason=missing_domain_entity")
            return text
        if not template:
            logger.info("dialogue_manager | skipped | reason=no_template_match")
            return text

        rewritten = template.replace("{name}", entity_for_domain)
        logger.info(
            "dialogue_manager | followup_rewrite"
            " | original=%r | rewritten=%r | entity=%s | conversation_id=%.8s",
            text,
            rewritten,
            entity_for_domain,
            str(state.get("conversation_id", ""))[:8],
        )
        return rewritten

    # ------------------------------------------------------------------
    def get_missing_context_clarification(
        self,
        user_text: str,
        state: dict[str, Any] | None,
    ) -> str | None:
        """Return safe clarification when follow-up needs missing context."""
        text_norm = _norm_for_match(user_text)
        text_basic = _basic_match_key(user_text)
        active_domain = str((state or {}).get("active_domain") or "none").strip()
        if (text_norm in _RESULT_LOOKUP or text_basic in _RESULT_CONTEXT_KEYS) and active_domain != "result":
            return "اكتب اسم التحليل والنتيجة حتى أقدر أساعدك."
        if (text_norm in _SYMPTOM_LOOKUP or text_basic in _SYMPTOM_CONTEXT_KEYS) and active_domain != "symptom":
            return "ما هي الأعراض التي تعاني منها؟"
        return None

    # ------------------------------------------------------------------
    def should_block_non_deterministic_fallback(
        self,
        user_text: str,
        resolved_text: str,
        state: dict[str, Any] | None,
    ) -> bool:
        """
        Block cache/RAG/OpenAI for context-dependent follow-ups.
        If we rewrote based on state, this must stay deterministic.
        """
        if (resolved_text or "").strip() != (user_text or "").strip():
            return True
        text_norm = _norm_for_match(user_text)
        text_basic = _basic_match_key(user_text)
        active_domain = str((state or {}).get("active_domain") or "none").strip()
        if active_domain == "result" and (text_norm in _RESULT_LOOKUP or text_basic in _RESULT_CONTEXT_KEYS):
            return True
        if active_domain == "symptom" and (text_norm in _SYMPTOM_LOOKUP or text_basic in _SYMPTOM_CONTEXT_KEYS):
            return True
        if active_domain == "package" and text_norm in _PACKAGE_LOOKUP:
            return True
        if active_domain == "branch" and text_norm in _BRANCH_LOOKUP:
            return True
        if active_domain == "test" and text_norm in _LOOKUP:
            return True
        return False

    # ------------------------------------------------------------------
    @staticmethod
    def _has_domain_blocker(text_norm: str) -> bool:
        """Return True when text_norm contains any domain-switch keyword."""
        for blocker in _DOMAIN_BLOCKERS:
            b = _norm(blocker)
            if not b:
                continue
            # Whole-word / boundary match
            if text_norm == b or f" {b} " in f" {text_norm} ":
                return True
        return False


# ---------------------------------------------------------------------------
# Module-level singleton — import and call get_dialogue_manager() anywhere.
# ---------------------------------------------------------------------------

_singleton = DialogueManager()


def get_dialogue_manager() -> DialogueManager:
    """Return the shared DialogueManager instance."""
    return _singleton
