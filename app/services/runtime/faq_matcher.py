"""Deterministic FAQ matching utilities for runtime FAQ layers."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic, tokenize_arabic


def overlap_score(a: str, b: str) -> float:
    """Compute token-overlap similarity between two texts."""
    tokens_a = set(tokenize_arabic(a))
    tokens_b = set(tokenize_arabic(b))
    if not tokens_a or not tokens_b:
        return 0.0

    inter = tokens_a & tokens_b
    denom = max(len(tokens_a), len(tokens_b))
    if denom <= 0:
        return 0.0
    return len(inter) / denom


def ratio_score(a: str, b: str) -> float:
    """Compute normalized sequence similarity ratio using difflib."""
    a_norm = normalize_arabic(a)
    b_norm = normalize_arabic(b)
    if not a_norm or not b_norm:
        return 0.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def score_faq_match(user_text: str, faq_record: dict[str, Any]) -> float:
    """Score one FAQ record against user text deterministically."""
    if not isinstance(faq_record, dict):
        return 0.0

    user_norm = normalize_arabic(user_text)
    if not user_norm:
        return 0.0

    faq_text = str(faq_record.get("q_norm") or faq_record.get("question") or "").strip()
    faq_norm = normalize_arabic(faq_text)
    if not faq_norm:
        return 0.0

    if user_norm == faq_norm:
        return 1.0

    base = (0.65 * overlap_score(user_norm, faq_norm)) + (0.35 * ratio_score(user_norm, faq_norm))
    if faq_norm in user_norm or user_norm in faq_norm:
        base += 0.08

    return max(0.0, min(1.0, float(base)))


def find_best_faq_match(
    user_text: str,
    faq_records: list[dict[str, Any]],
    min_score: float = 0.78,
    min_margin: float = 0.03,
) -> dict[str, Any] | None:
    """Return best FAQ match if score and ambiguity thresholds are satisfied."""
    if not isinstance(faq_records, list) or not faq_records:
        return None

    scored: list[tuple[float, dict[str, Any]]] = []
    for rec in faq_records:
        if not isinstance(rec, dict):
            continue
        scored.append((score_faq_match(user_text, rec), rec))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_record = scored[0]
    if best_score < min_score:
        return None

    second_score = scored[1][0] if len(scored) > 1 else 0.0
    margin = best_score - second_score
    if len(scored) > 1 and margin < min_margin:
        return None

    return {
        "score": float(best_score),
        "margin": float(margin),
        "record": best_record,
    }


if __name__ == "__main__":
    mock_records = [
        {
            "id": "faq::16",
            "question": "هل تحليل السكر التراكمي يحتاج صيام؟",
            "q_norm": "هل تحليل السكر التراكمي يحتاج صيام",
        },
        {
            "id": "faq::11",
            "question": "هل يوجد عروض أو تخفيضات حالياً؟",
            "q_norm": "هل يوجد عروض او تخفيضات حاليا",
        },
        {
            "id": "faq::13",
            "question": "هل نتائج التحاليل سرية؟",
            "q_norm": "هل نتائج التحاليل سريه",
        },
    ]

    sample_inputs = [
        "هل السكر التراكمي يحتاج صيام",
        "عندكم عروض حاليا",
        "هل احد يقدر يشوف نتيجتي",
    ]

    for user_input in sample_inputs:
        match = find_best_faq_match(user_input, mock_records, min_score=0.45, min_margin=0.02)
        print(f"Input: {user_input}")
        if not match:
            print("Matched FAQ ID: NONE")
            print("Score: 0.0000")
            print("Margin: 0.0000")
        else:
            rec = match.get("record") or {}
            print(f"Matched FAQ ID: {rec.get('id', '')}")
            print(f"Score: {match.get('score', 0.0):.4f}")
            print(f"Margin: {match.get('margin', 0.0):.4f}")
        print("-" * 40)

