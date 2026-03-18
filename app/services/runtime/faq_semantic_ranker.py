"""Conversation-aware semantic FAQ ranking for FAQ-only runtime.

Acceptance criteria:
- Answers remain grounded in stored FAQ records only.
- Short contextual follow-ups are handled via recent conversation context.
- No branch-specific location query is answered through generic FAQ matching.
- No-match is preferred over wrong-match when confidence/margin is weak.
"""

from __future__ import annotations

from typing import Any

from app.services.runtime.faq_canonicalizer import FAQ_CANONICAL_RULES, is_branch_specific_query
from app.services.runtime.faq_matcher import score_faq_match
from app.services.runtime.text_normalizer import normalize_arabic, tokenize_arabic


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _build_faq_concept_map() -> dict[str, str]:
    """Map FAQ id -> concept from canonical rules."""
    out: dict[str, str] = {}
    for rule in FAQ_CANONICAL_RULES:
        faq_id = _safe_str(getattr(rule, "faq_id", ""))
        concept = _safe_str(getattr(rule, "concept", ""))
        if faq_id and concept:
            out[faq_id] = concept
    return out


FAQ_ID_TO_CONCEPT = _build_faq_concept_map()


def _is_dependent_followup(query: str) -> bool:
    """Detect short/dependent follow-up shape using generic structure rules."""
    n = normalize_arabic(query)
    if not n:
        return False

    tokens = tokenize_arabic(n, remove_stopwords=False)
    if len(tokens) <= 2:
        return True
    if len(tokens) <= 4 and tokens[0] in {"و", "طيب", "يعني"}:
        return True

    pronouns = {"هو", "هي", "هذا", "هذه", "ذاك", "ه", "ها"}
    if any(t in pronouns for t in tokens) and len(tokens) <= 6:
        return True

    dependent_heads = {"رمزه", "صيام", "مدته", "وينه", "استلمه", "سري", "آمن", "امن"}
    if any(t in dependent_heads for t in tokens) and len(tokens) <= 6:
        return True

    if n.startswith("و") and len(tokens) <= 6:
        return True

    return False


def _infer_topic_from_recent_messages(
    faq_records: list[dict[str, Any]],
    recent_runtime_messages: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Infer most recent active FAQ topic from recent conversation."""
    recent = _safe_list(recent_runtime_messages)
    if not faq_records or not recent:
        return {
            "faq_id": "",
            "concept": "",
            "entity": "",
            "confidence": 0.0,
            "source_text": "",
        }

    best: dict[str, Any] = {
        "faq_id": "",
        "concept": "",
        "entity": "",
        "confidence": 0.0,
        "source_text": "",
    }

    # Prefer latest user turns, then assistant turns.
    for preferred_role in ("user", "assistant"):
        for item in reversed(recent):
            if _safe_str(item.get("role")).lower() != preferred_role:
                continue
            content = _safe_str(item.get("content"))
            if not content:
                continue

            local_best_score = 0.0
            local_best_record: dict[str, Any] | None = None
            for record in faq_records:
                score = float(score_faq_match(content, record))
                if score > local_best_score:
                    local_best_score = score
                    local_best_record = record

            if not local_best_record or local_best_score < 0.66:
                continue

            faq_id = _safe_str(local_best_record.get("id"))
            concept = _safe_str(FAQ_ID_TO_CONCEPT.get(faq_id))
            best = {
                "faq_id": faq_id,
                "concept": concept,
                "entity": _safe_str(local_best_record.get("question")),
                "confidence": float(local_best_score),
                "source_text": content,
            }
            return best

    return best


def rank_faq_candidates(
    current_query: str,
    faq_records: list[dict[str, Any]],
    recent_runtime_messages: list[dict[str, Any]] | None = None,
    *,
    rewritten_query: str = "",
    resolved_query: str = "",
    intent_hint: str = "",
    followup_detected: bool = False,
) -> dict[str, Any]:
    """Rank FAQ records with semantic + conversation-aware scoring metadata."""
    query = _safe_str(current_query)
    if not query:
        return {"ranked": [], "meta": {"reason": "empty_query"}}

    # Preserve strict location safety.
    if is_branch_specific_query(query):
        return {
            "ranked": [],
            "meta": {
                "reason": "branch_specific_blocked",
                "is_followup": bool(followup_detected or _is_dependent_followup(query)),
                "inferred_topic": {},
            },
        }

    inferred = _infer_topic_from_recent_messages(faq_records, recent_runtime_messages)
    inferred_faq_id = _safe_str(inferred.get("faq_id"))
    inferred_concept = _safe_str(inferred.get("concept"))

    search_texts = []
    for text in (query, resolved_query, rewritten_query):
        clean = _safe_str(text)
        if clean and clean not in search_texts:
            search_texts.append(clean)

    if not search_texts:
        search_texts = [query]

    is_followup = bool(followup_detected or _is_dependent_followup(query))
    hint_concept = _safe_str(intent_hint)

    ranked: list[dict[str, Any]] = []
    for record in faq_records:
        faq_id = _safe_str(record.get("id"))
        if not faq_id:
            continue

        concept = _safe_str(FAQ_ID_TO_CONCEPT.get(faq_id))
        scores = [float(score_faq_match(text, record)) for text in search_texts]
        base_score = max(scores) if scores else 0.0
        if base_score <= 0.0:
            continue

        followup_boost = 0.0
        topic_boost = 0.0
        mismatch_penalty = 0.0

        if is_followup and inferred_faq_id and faq_id == inferred_faq_id:
            followup_boost += 0.10
        if inferred_concept and concept and inferred_concept == concept:
            topic_boost += 0.08
        if hint_concept and concept and hint_concept == concept:
            topic_boost += 0.06

        if inferred_faq_id and faq_id != inferred_faq_id and base_score < 0.82:
            mismatch_penalty += 0.05
        if inferred_concept and concept and inferred_concept != concept and base_score < 0.80:
            mismatch_penalty += 0.03

        final_score = max(0.0, min(1.0, base_score + followup_boost + topic_boost - mismatch_penalty))
        ranked.append(
            {
                "faq_id": faq_id,
                "record": record,
                "concept": concept,
                "base_score": float(base_score),
                "followup_boost": float(followup_boost),
                "topic_boost": float(topic_boost),
                "mismatch_penalty": float(mismatch_penalty),
                "score": float(final_score),
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)
    top_score = float(ranked[0]["score"]) if ranked else 0.0
    second_score = float(ranked[1]["score"]) if len(ranked) > 1 else 0.0
    margin = float(top_score - second_score)

    return {
        "ranked": ranked,
        "meta": {
            "is_followup": is_followup,
            "search_texts": search_texts,
            "inferred_topic": inferred,
            "top_score": top_score,
            "second_score": second_score,
            "margin": margin,
        },
    }


def select_best_ranked_candidate(
    ranked_result: dict[str, Any],
    *,
    min_score: float = 0.78,
    min_margin: float = 0.03,
) -> dict[str, Any] | None:
    """Select top ranked FAQ candidate if confidence and margin are healthy."""
    ranked = _safe_list((ranked_result or {}).get("ranked"))
    if not ranked:
        return None

    best = ranked[0]
    best_score = float(best.get("score") or 0.0)
    second_score = float(ranked[1].get("score") or 0.0) if len(ranked) > 1 else 0.0
    margin = float(best_score - second_score)

    if best_score < min_score:
        return None
    if len(ranked) > 1 and margin < min_margin:
        return None

    return {
        "score": best_score,
        "second_score": second_score,
        "margin": margin,
        "record": best.get("record") or {},
        "faq_id": _safe_str(best.get("faq_id")),
        "concept": _safe_str(best.get("concept")),
        "components": {
            "base_score": float(best.get("base_score") or 0.0),
            "followup_boost": float(best.get("followup_boost") or 0.0),
            "topic_boost": float(best.get("topic_boost") or 0.0),
            "mismatch_penalty": float(best.get("mismatch_penalty") or 0.0),
        },
    }


if __name__ == "__main__":
    from app.services.runtime.faq_loader import load_faq_records
    from app.services.runtime.faq_followup_rewriter import rewrite_faq_query

    faq_records = load_faq_records()

    scenarios = [
        ("وش الخدمات اللي عندكم", []),
        ("كيف اقدر ادفع", []),
        ("وين فروعكم", []),
        (
            "هل يحتاج صيام؟",
            [
                {"role": "user", "content": "ما هو رمز السكر التراكمي"},
                {"role": "assistant", "content": "رمز تحليل السكر التراكمي هو HbA1c"},
            ],
        ),
        (
            "ولكبار السن؟",
            [
                {"role": "user", "content": "هل التحاليل آمنة للأطفال؟"},
                {"role": "assistant", "content": "نعم، التحاليل آمنة للأطفال."},
            ],
        ),
        ("وين أقرب فرع بالرياض", []),
        ("يعني محد يقدر يشوفها؟", [{"role": "user", "content": "هل نتائج التحاليل سرية؟"}]),
    ]

    for query, history in scenarios:
        rewrite = rewrite_faq_query(query, recent_runtime_messages=history)
        ranked = rank_faq_candidates(
            query,
            faq_records,
            recent_runtime_messages=history,
            rewritten_query=rewrite.rewritten_query,
            resolved_query=rewrite.resolved_query,
            intent_hint=_safe_str(rewrite.intent_hint),
            followup_detected=bool(rewrite.used_followup),
        )
        picked = select_best_ranked_candidate(ranked, min_score=0.78, min_margin=0.03)

        print(f"QUERY: {query}")
        print(f"FOLLOWUP: {ranked.get('meta', {}).get('is_followup')}")
        print(f"INFERRED_TOPIC: {ranked.get('meta', {}).get('inferred_topic')}")
        print(f"TOP_SCORE: {ranked.get('meta', {}).get('top_score')}")
        print(f"SECOND_SCORE: {ranked.get('meta', {}).get('second_score')}")
        print(f"MARGIN: {ranked.get('meta', {}).get('margin')}")
        print(f"MATCHED_FAQ_ID: {(picked or {}).get('faq_id')}")
        print("-" * 64)
