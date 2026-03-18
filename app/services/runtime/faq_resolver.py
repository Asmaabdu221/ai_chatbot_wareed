"""Runtime FAQ resolver using canonicalization, loading, and deterministic matching."""

from __future__ import annotations

import re
import logging
from typing import Any

from app.services.runtime.faq_canonicalizer import (
    is_branch_specific_query,
)
from app.services.runtime.faq_followup_rewriter import FAQRewriteResult, rewrite_faq_query
from app.services.runtime.faq_loader import load_faq_records
from app.services.runtime.faq_matcher import find_best_faq_match
from app.services.runtime.faq_semantic_ranker import (
    FAQ_ID_TO_CONCEPT,
    rank_faq_candidates,
    select_best_ranked_candidate,
)
from app.services.runtime.text_normalizer import normalize_arabic

logger = logging.getLogger(__name__)

_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "consultation_after_results": ("استشاره", "استشارة"),
    "home_visit": ("زياره", "زيارة", "منزلي", "منزليه", "منزليه"),
    "electronic_results": ("اونلاين", "الكترون", "واتساب", "ايميل", "ترسلون", "ارسال"),
    "results_turnaround": ("كم مدته", "كم ياخذ", "متي تطلع", "متى تطلع"),
    "payment_methods": ("دفع", "ادفع"),
    "results_privacy": ("سري", "سرية", "يشوفها", "يشوف", "محد"),
}

_INTENT_ANCHORS: dict[str, str] = {
    "consultation_after_results": "هل يوفر المختبر استشارة طبية بعد ظهور النتائج",
    "home_visit": "هل يوفر مختبر وريد خدمة الزيارات المنزلية",
    "electronic_results": "هل يتم ارسال نتائج التحاليل الكترونيا",
    "results_turnaround": "كم تستغرق نتائج التحاليل للظهور",
    "payment_methods": "ما هي طرق الدفع المتاحة",
    "results_privacy": "هل نتائج التحاليل سريه",
}


def _safe_str(value: Any) -> str:
    """Convert any value to a safely stripped string."""
    return str(value or "").strip()


def _escape_debug(value: Any) -> str:
    """Return unicode-escaped debug-safe text."""
    return _safe_str(value).encode("unicode_escape").decode()


def _is_privacy_style_question(user_text: str) -> bool:
    """Return True when the user question is phrased as privacy access by others."""
    user_norm = normalize_arabic(user_text)
    if not user_norm:
        return False

    triggers = (
        "هل احد",
        "هل أحد",
        "هل غيري",
        "هل احد يقدر",
        "هل احد يطلع",
        "هل احد يشوف",
        "هل غيري يقدر",
        "هل غيري يشوف",
        "هل غيري يطلع",
        "احد يقدر يشوف",
        "احد يطلع على نتيجتي",
        "غيري يقدر يشوف",
    )
    trigger_norms = [normalize_arabic(t) for t in triggers]

    return any(t and t in user_norm for t in trigger_norms)


def _strip_positive_opener(text: str) -> str:
    """Remove a leading positive opener such as نعم/أكيد/طبعاً."""
    value = _safe_str(text)
    if not value:
        return ""

    patterns = (
        r"^\s*نعم\s*[,،:\-]?\s*",
        r"^\s*أكيد\s*[,،:\-]?\s*",
        r"^\s*اكيد\s*[,،:\-]?\s*",
        r"^\s*طبعا\s*[,،:\-]?\s*",
        r"^\s*طبعاً\s*[,،:\-]?\s*",
    )

    for pattern in patterns:
        value = re.sub(pattern, "", value).strip()

    return value


def _refine_faq_answer_style(user_text: str, answer: str, concepts: list[str]) -> str:
    """Apply minimal wording refinement for privacy-style yes/no questions."""
    base = _safe_str(answer)
    if not base:
        return base

    concept_set = {_safe_str(c) for c in (concepts or [])}
    if not ({"results_privacy", "sensitive_tests_privacy"} & concept_set):
        return base

    if not _is_privacy_style_question(user_text):
        return base

    if base.startswith("لا"):
        return base

    body = _strip_positive_opener(base)
    if not body:
        return "لا"

    return f"لا، {body}"


def _build_resolution_context(
    user_text: str,
    last_user_text: str = "",
    last_assistant_text: str = "",
    recent_runtime_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build conversation-aware rewrite context for FAQ ranking."""
    rewrite = rewrite_faq_query(
        user_text=user_text,
        last_user_text=last_user_text,
        last_assistant_text=last_assistant_text,
        last_resolved_intent="",
        last_resolved_entity="",
        recent_runtime_messages=recent_runtime_messages,
    )
    detected_intent = _detect_anchor_intent(user_text)
    return {
        "normalized": normalize_arabic(user_text),
        # Canonicalizer can produce large candidate expansions for some colloquial
        # phrasings; keep resolver deterministic-first and lightweight here.
        "canon": {},
        "rewrite": rewrite,
        "detected_intent": detected_intent,
        "detected_anchor": _safe_str(_INTENT_ANCHORS.get(detected_intent)),
    }


def _detect_anchor_intent(user_text: str) -> str:
    """Detect strong query intent for deterministic FAQ anchoring."""
    n = normalize_arabic(user_text)
    if not n:
        return ""

    if any(k in n for k in _INTENT_KEYWORDS["consultation_after_results"]) and (
        "نتايج" in n or "نتائج" in n or "نتيجه" in n or "بعد" in n
    ):
        return "consultation_after_results"
    if any(k in n for k in _INTENT_KEYWORDS["home_visit"]):
        return "home_visit"
    if any(k in n for k in _INTENT_KEYWORDS["electronic_results"]):
        return "electronic_results"
    if any(k in n for k in _INTENT_KEYWORDS["results_turnaround"]):
        return "results_turnaround"
    if any(k in n for k in _INTENT_KEYWORDS["payment_methods"]):
        return "payment_methods"
    if any(k in n for k in _INTENT_KEYWORDS["results_privacy"]):
        return "results_privacy"
    return ""


def _unique_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _safe_str(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _build_deterministic_search_texts(
    raw_text: str,
    context: dict[str, Any],
) -> list[str]:
    """Build deterministic candidate texts for strong FAQ matching."""
    canon = context.get("canon") or {}
    rewrite: FAQRewriteResult = context["rewrite"]
    detected_intent = _safe_str(context.get("detected_intent"))
    detected_anchor = _safe_str(context.get("detected_anchor"))
    prefer_current_intent = _safe_str(getattr(rewrite, "intent_source", "")) == "current_query"

    ordered = [
        _safe_str(raw_text),
        _safe_str(context.get("normalized")),
        _safe_str(rewrite.resolved_query),
        _safe_str(rewrite.rewritten_query),
        _safe_str(rewrite.intent_hint).replace("_", " "),
    ]
    if prefer_current_intent:
        ordered = [
            _safe_str(rewrite.rewritten_query),
            _safe_str(rewrite.resolved_query),
            _safe_str(rewrite.intent_hint).replace("_", " "),
            _safe_str(raw_text),
            _safe_str(context.get("normalized")),
        ]
    if detected_anchor:
        ordered = [detected_anchor, detected_intent.replace("_", " ")] + ordered

    search_texts = _unique_keep_order(ordered + [_safe_str(v) for v in (canon.get("variants") or [])])

    for candidate in (canon.get("candidates") or []):
        if not isinstance(candidate, dict):
            continue
        if float(candidate.get("score") or 0.0) < 0.50:
            continue
        q = _safe_str(candidate.get("canonical_question"))
        if q:
            search_texts.append(q)

    norm = normalize_arabic(raw_text)
    if norm:
        # Deterministic anchor expansions for core standalone FAQ intents.
        if ("متي" in norm or "متى" in norm or "كم" in norm) and (
            "نتيجه" in norm or "نتيجه" in norm or "نتايج" in norm or "نتائج" in norm
        ):
            search_texts.append("كم تستغرق نتائج التحاليل للظهور")
        if "تراكمي" in norm and ("صيام" in norm or "يحتاج" in norm):
            search_texts.append("هل تحليل السكر التراكمي يحتاج صيام")
        if ("احد" in norm or "غيري" in norm or "محد" in norm) and (
            "يشوف" in norm or "يطلع" in norm or "نتيجه" in norm or "نتايج" in norm
        ):
            search_texts.append("هل نتائج التحاليل سريه")

    return _unique_keep_order(search_texts)


def _pick_deterministic_match(
    search_texts: list[str],
    faq_records: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    """Pick strongest deterministic FAQ match across candidate texts."""
    best: dict[str, Any] | None = None
    best_text = ""
    best_score = -1.0

    for text in search_texts:
        match = find_best_faq_match(
            text,
            faq_records,
            min_score=0.74,
            min_margin=0.02,
        )
        if not match:
            continue
        score = float(match.get("score") or 0.0)
        if score > best_score:
            best = match
            best_text = _safe_str(text)
            best_score = score
            if score >= 0.999:
                break

    return best, best_text


def _pick_intent_concept_match(
    detected_intent: str,
    search_texts: list[str],
    faq_records: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    """Prefer FAQs matching detected concept intent before global matching."""
    intent = _safe_str(detected_intent)
    if not intent:
        return None, ""

    concept_records = [
        record for record in faq_records if _safe_str(FAQ_ID_TO_CONCEPT.get(_safe_str(record.get("id")))) == intent
    ]
    if not concept_records:
        return None, ""

    best: dict[str, Any] | None = None
    best_text = ""
    best_score = -1.0
    for text in search_texts:
        match = find_best_faq_match(
            text,
            concept_records,
            min_score=0.40,
            min_margin=0.0,
        )
        if not match:
            continue
        score = float(match.get("score") or 0.0)
        if score > best_score:
            best = match
            best_text = _safe_str(text)
            best_score = score
    return best, best_text


def _resolve_concepts_for_match(
    faq_id: str,
    ranked_pick: dict[str, Any] | None,
    rewrite: FAQRewriteResult,
) -> list[str]:
    """Build concepts list from ranked concept and rewrite hint."""
    concepts: list[str] = []
    ranked_concept = _safe_str((ranked_pick or {}).get("concept"))
    if ranked_concept:
        concepts.append(ranked_concept)

    map_concept = _safe_str(FAQ_ID_TO_CONCEPT.get(faq_id))
    if map_concept and map_concept not in concepts:
        concepts.append(map_concept)

    rewrite_hint = _safe_str(rewrite.intent_hint)
    if rewrite_hint and rewrite_hint not in concepts:
        concepts.append(rewrite_hint)

    return concepts


def _should_block_branch_faq(raw_text: str, faq_id: str) -> bool:
    """Return True when generic branches FAQ must not answer a specific location query."""
    return faq_id == "faq::10" and is_branch_specific_query(raw_text)


def resolve_faq(
    user_text: str,
    last_user_text: str = "",
    last_assistant_text: str = "",
    recent_runtime_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Resolve user text to a confident FAQ match, or return None."""
    raw_text = _safe_str(user_text)
    if not raw_text:
        return None

    # Hard guard in FAQ-only phase:
    # branch/location-specific queries should not resolve to generic/unrelated FAQs.
    if is_branch_specific_query(raw_text):
        logger.debug(
            "faq_resolver no match branch specific | query=%s | normalized=%s | route=faq_only_no_match_branch_specific",
            _escape_debug(raw_text),
            _escape_debug(normalize_arabic(raw_text)),
        )
        return None

    context = _build_resolution_context(
        raw_text,
        last_user_text=last_user_text,
        last_assistant_text=last_assistant_text,
        recent_runtime_messages=recent_runtime_messages,
    )
    rewrite: FAQRewriteResult = context["rewrite"]
    detected_intent = _safe_str(context.get("detected_intent"))
    normalized = _safe_str(context.get("normalized"))

    faq_records = load_faq_records()
    if not faq_records:
        return None

    deterministic_search_texts = _build_deterministic_search_texts(raw_text, context)
    concept_best, concept_text = _pick_intent_concept_match(
        detected_intent,
        deterministic_search_texts,
        faq_records,
    )
    deterministic_best, deterministic_text = _pick_deterministic_match(
        deterministic_search_texts,
        faq_records,
    )
    if concept_best:
        deterministic_best = concept_best
        deterministic_text = concept_text or deterministic_text
    deterministic_match_found = bool(deterministic_best)
    deterministic_faq_id = _safe_str(
        ((deterministic_best or {}).get("record") or {}).get("id")
    )
    ranker_used = False
    ranker_top_faq_id = ""

    if deterministic_best:
        record = deterministic_best.get("record") or {}
        faq_id = _safe_str(record.get("id"))
        if _should_block_branch_faq(raw_text, faq_id):
            logger.debug(
                "faq_resolver blocked branch specific | query=%s | normalized=%s | deterministic_match_found=%s | deterministic_faq_id=%s | ranker_used=%s | ranker_top_faq_id=%s | final_route_decision=blocked_branch_specific",
                _escape_debug(raw_text),
                _escape_debug(normalized),
                deterministic_match_found,
                faq_id,
                ranker_used,
                ranker_top_faq_id,
            )
            return None

        concepts = _resolve_concepts_for_match(faq_id, None, rewrite)
        answer = _refine_faq_answer_style(
            user_text=raw_text,
            answer=_safe_str(record.get("answer")),
            concepts=concepts,
        )
        result = {
            "faq_id": faq_id,
            "question": _safe_str(record.get("question")),
            "answer": answer,
            "score": float(deterministic_best.get("score") or 0.0),
            "margin": float(deterministic_best.get("margin") or 0.0),
            "matched_text": _safe_str(deterministic_text),
            "concepts": concepts,
            "canonical_candidates": [
                _safe_str(x)
                for x in [raw_text, rewrite.resolved_query, rewrite.rewritten_query]
                if _safe_str(x)
            ],
            "matched_via": "faq_deterministic",
            "source": "faq",
        }
        logger.debug(
            "faq_resolver matched deterministic | query=%s | normalized=%s | detected_intent=%s | deterministic_match_found=%s | deterministic_faq_id=%s | ranker_used=%s | ranker_top_faq_id=%s | final_route_decision=matched_deterministic",
            _escape_debug(raw_text),
            _escape_debug(normalized),
            detected_intent,
            deterministic_match_found,
            faq_id,
            ranker_used,
            ranker_top_faq_id,
        )
        return result

    ranker_used = True
    ranked_result = rank_faq_candidates(
        current_query=raw_text,
        faq_records=faq_records,
        recent_runtime_messages=recent_runtime_messages,
        rewritten_query=rewrite.rewritten_query,
        resolved_query=rewrite.resolved_query,
        intent_hint=_safe_str(rewrite.intent_hint),
        followup_detected=bool(rewrite.used_followup),
    )
    ranked_meta = ranked_result.get("meta") or {}
    ranked_pick = select_best_ranked_candidate(
        ranked_result,
        min_score=0.72,
        min_margin=0.015,
    )
    ranker_top_faq_id = _safe_str(((ranked_pick or {}).get("record") or {}).get("id"))
    if not ranked_pick:
        logger.debug(
            "faq_resolver no match | query=%s | normalized=%s | detected_intent=%s | is_followup=%s | inferred_topic=%s | rewritten=%s | rewrite_intent=%s | top_faq_id=none | top_score=%.3f | second_score=%.3f | margin=%.3f | deterministic_match_found=%s | deterministic_faq_id=%s | ranker_used=%s | ranker_top_faq_id=%s | final_route_decision=no_match",
            _escape_debug(raw_text),
            _escape_debug(normalized),
            detected_intent,
            bool(ranked_meta.get("is_followup")),
            _escape_debug((ranked_meta.get("inferred_topic") or {}).get("concept")),
            _escape_debug(rewrite.rewritten_query),
            _escape_debug(rewrite.intent_hint),
            float(ranked_meta.get("top_score") or 0.0),
            float(ranked_meta.get("second_score") or 0.0),
            float(ranked_meta.get("margin") or 0.0),
            deterministic_match_found,
            deterministic_faq_id,
            ranker_used,
            ranker_top_faq_id,
        )
        return None

    record = ranked_pick.get("record") or {}
    faq_id = _safe_str(record.get("id"))
    concepts = _resolve_concepts_for_match(faq_id, ranked_pick, rewrite)

    # Guard: keep defensive check for generic branches FAQ too.
    if _should_block_branch_faq(raw_text, faq_id):
        logger.debug(
            "faq_resolver blocked branch specific | query=%s | normalized=%s | is_followup=%s | inferred_topic=%s | rewritten=%s | rewrite_intent=%s | top_faq_id=%s | top_score=%.3f | second_score=%.3f | margin=%.3f | deterministic_match_found=%s | deterministic_faq_id=%s | ranker_used=%s | ranker_top_faq_id=%s | final_route_decision=blocked_branch_specific",
            _escape_debug(raw_text),
            _escape_debug(normalized),
            bool(ranked_meta.get("is_followup")),
            _escape_debug((ranked_meta.get("inferred_topic") or {}).get("concept")),
            _escape_debug(rewrite.rewritten_query),
            _escape_debug(rewrite.intent_hint),
            faq_id,
            float(ranked_pick.get("score") or 0.0),
            float(ranked_pick.get("second_score") or 0.0),
            float(ranked_pick.get("margin") or 0.0),
            deterministic_match_found,
            deterministic_faq_id,
            ranker_used,
            ranker_top_faq_id,
        )
        return None

    answer = _refine_faq_answer_style(
        user_text=raw_text,
        answer=_safe_str(record.get("answer")),
        concepts=concepts,
    )

    result = {
        "faq_id": faq_id,
        "question": _safe_str(record.get("question")),
        "answer": answer,
        "score": float(ranked_pick.get("score") or 0.0),
        "margin": float(ranked_pick.get("margin") or 0.0),
        "matched_text": _safe_str(record.get("q_norm")) or _safe_str(record.get("question")),
        "concepts": concepts,
        "canonical_candidates": [
            _safe_str(x)
            for x in [raw_text, rewrite.resolved_query, rewrite.rewritten_query]
            if _safe_str(x)
        ],
        "matched_via": "faq_ranker_fallback",
        "source": "faq",
    }
    logger.debug(
        "faq_resolver matched ranker | query=%s | normalized=%s | detected_intent=%s | is_followup=%s | inferred_topic=%s | rewritten=%s | rewrite_intent=%s | top_faq_id=%s | top_score=%.3f | second_score=%.3f | margin=%.3f | deterministic_match_found=%s | deterministic_faq_id=%s | ranker_used=%s | ranker_top_faq_id=%s | final_route_decision=matched_ranker",
        _escape_debug(raw_text),
        _escape_debug(normalized),
        detected_intent,
        bool(ranked_meta.get("is_followup")),
        _escape_debug((ranked_meta.get("inferred_topic") or {}).get("concept")),
        _escape_debug(rewrite.rewritten_query),
        _escape_debug(rewrite.intent_hint),
        faq_id,
        float(ranked_pick.get("score") or 0.0),
        float(ranked_pick.get("second_score") or 0.0),
        float(ranked_pick.get("margin") or 0.0),
        deterministic_match_found,
        deterministic_faq_id,
        ranker_used,
        ranker_top_faq_id,
    )
    return result


def resolve_faq_answer(
    user_text: str,
    last_user_text: str = "",
    last_assistant_text: str = "",
    recent_runtime_messages: list[dict[str, Any]] | None = None,
) -> str | None:
    """Resolve user text and return only FAQ answer text when matched."""
    result = resolve_faq(
        user_text,
        last_user_text=last_user_text,
        last_assistant_text=last_assistant_text,
        recent_runtime_messages=recent_runtime_messages,
    )
    if not result:
        return None

    answer = _safe_str(result.get("answer"))
    return answer or None


if __name__ == "__main__":
    samples = [
        "وش الخدمات اللي عندكم",
        "عندكم سحب من البيت",
        "متى تطلع نتيجتي",
        "هل التراكمي يحتاج صيام",
        "فيه عروض الحين",
        "هل احد يقدر يشوف نتيجتي",
        "وين اقرب فرع بالرياض",
    ]

    for text in samples:
        result = resolve_faq(text)
        print(f"INPUT: {text}")
        if not result:
            print("MATCHED FAQ ID: NONE")
            print("QUESTION: NONE")
            print("ANSWER: NONE")
            print("SCORE: 0.0")
            print("MARGIN: 0.0")
            print("MATCHED TEXT: ")
            print("CONCEPTS: []")
        else:
            print(f"MATCHED FAQ ID: {result.get('faq_id', '')}")
            print(f"QUESTION: {result.get('question', '')}")
            print(f"ANSWER: {result.get('answer', '')}")
            print(f"SCORE: {result.get('score', 0.0)}")
            print(f"MARGIN: {result.get('margin', 0.0)}")
            print(f"MATCHED TEXT: {result.get('matched_text', '')}")
            print(f"CONCEPTS: {result.get('concepts', [])}")
        print("-" * 48)
