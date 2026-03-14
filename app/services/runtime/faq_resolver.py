"""Runtime FAQ resolver using canonicalization, loading, and deterministic matching."""

from __future__ import annotations

from typing import Any

from app.services.runtime.faq_canonicalizer import canonicalize_faq_query
from app.services.runtime.faq_loader import load_faq_records
from app.services.runtime.faq_matcher import find_best_faq_match


def resolve_faq(user_text: str) -> dict[str, Any] | None:
    """Resolve user text to a confident FAQ match, or return None."""
    canon = canonicalize_faq_query(user_text)
    search_texts = list(canon.get("candidate_texts") or [])
    if not search_texts:
        search_texts = [str(user_text or "")]

    faq_records = load_faq_records()
    if not faq_records:
        return None

    best: dict[str, Any] | None = None
    best_score = -1.0
    best_search_text = ""

    for search_text in search_texts:
        match = find_best_faq_match(
            str(search_text or ""),
            faq_records,
            min_score=0.78,
            min_margin=0.03,
        )
        if not match:
            continue

        score = float(match.get("score") or 0.0)
        if score > best_score:
            best_score = score
            best = match
            best_search_text = str(search_text or "")

    if not best:
        return None

    record = best.get("record") or {}
    return {
        "faq_id": str(record.get("id") or "").strip(),
        "question": str(record.get("question") or "").strip(),
        "answer": str(record.get("answer") or "").strip(),
        "score": float(best.get("score") or 0.0),
        "margin": float(best.get("margin") or 0.0),
        "matched_text": str(best_search_text or "").strip(),
        "concepts": list(canon.get("concepts") or []),
        "source": "faq",
    }


def resolve_faq_answer(user_text: str) -> str | None:
    """Resolve user text and return only FAQ answer text when matched."""
    result = resolve_faq(user_text)
    if not result:
        return None
    answer = str(result.get("answer") or "").strip()
    return answer or None


if __name__ == "__main__":
    samples = [
        "وش الخدمات اللي عندكم",
        "عندكم سحب من البيت",
        "متى تطلع نتيجتي",
        "هل التراكمي يحتاج صيام",
        "فيه عروض الحين",
        "هل احد يقدر يشوف نتيجتي",
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
        else:
            print(f"MATCHED FAQ ID: {result.get('faq_id', '')}")
            print(f"QUESTION: {result.get('question', '')}")
            print(f"ANSWER: {result.get('answer', '')}")
            print(f"SCORE: {result.get('score', 0.0)}")
            print(f"MARGIN: {result.get('margin', 0.0)}")
            print(f"MATCHED TEXT: {result.get('matched_text', '')}")
        print("-" * 48)
