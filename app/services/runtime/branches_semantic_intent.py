"""Semantic branch-intent helper using local Ollama embeddings.

This module is routing-assist only. Final answers must still come from the
deterministic branches resolver and dataset-backed logic.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Any

OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODEL_NAME = "qwen3-embedding"

BRANCH_INTENT_SEEDS: dict[str, list[str]] = {
    "branch_general": [
        "وين فروعكم",
        "عندكم فروع",
        "أبي الفروع",
    ],
    "branch_city": [
        "الرياض",
        "أبي فروع الرياض",
        "وين فروعكم بالرياض",
    ],
    "branch_district": [
        "في حي النرجس",
        "أنا في العليا",
        "أبي فرع في الحمدانية",
    ],
    "branch_specific": [
        "فرع النرجس",
        "موقع فرع العليا",
        "عندكم فرع بالعليا",
    ],
    "branch_selection": [
        "1",
        "2",
        "اختار رقم 3",
    ],
}

SUPPORTED_BRANCH_INTENTS = set(BRANCH_INTENT_SEEDS.keys())
MIN_CONFIDENCE_SCORE = 0.82
MIN_CONFIDENCE_MARGIN = 0.03


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _is_numeric_selection_query(text: str) -> bool:
    value = _safe_str(text).translate(
        str.maketrans({"٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9"})
    )
    return bool(value) and value.isdigit() and len(value) <= 2


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embed_text(text: str) -> list[float]:
    payload = json.dumps({"model": MODEL_NAME, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    emb = data.get("embedding")
    if not isinstance(emb, list) or not emb:
        raise RuntimeError("Invalid embeddings response from Ollama")
    return [float(x) for x in emb]


@lru_cache(maxsize=1)
def _intent_centroids() -> dict[str, list[float]]:
    centroids: dict[str, list[float]] = {}
    for intent, examples in BRANCH_INTENT_SEEDS.items():
        vectors = [_embed_text(example) for example in examples]
        dim = len(vectors[0])
        avg = [0.0] * dim
        for vec in vectors:
            for i, v in enumerate(vec):
                avg[i] += v
        centroids[intent] = [v / len(vectors) for v in avg]
    return centroids


def detect_branch_semantic_intent(query: str) -> dict[str, Any]:
    """Detect branch intent semantically; never raises.

    Returns structured metadata:
    - intent
    - score
    - margin
    - scores
    - available
    - error
    """
    text = _safe_str(query)
    if not text:
        return {
            "intent": "",
            "score": 0.0,
            "margin": 0.0,
            "scores": {},
            "available": True,
            "error": "",
        }

    if _is_numeric_selection_query(text):
        return {
            "intent": "branch_selection",
            "score": 0.99,
            "margin": 0.99,
            "scores": {"branch_selection": 0.99},
            "available": True,
            "error": "",
        }

    try:
        centroids = _intent_centroids()
        q_vec = _embed_text(text)
        scores = {intent: _cosine_similarity(q_vec, c_vec) for intent, c_vec in centroids.items()}
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_intent, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = top_score - second_score
        return {
            "intent": top_intent,
            "score": float(top_score),
            "margin": float(margin),
            "scores": {k: float(v) for k, v in scores.items()},
            "available": True,
            "error": "",
        }
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "intent": "",
            "score": 0.0,
            "margin": 0.0,
            "scores": {},
            "available": False,
            "error": _safe_str(exc),
        }


def is_confident_branch_intent(result: dict[str, Any]) -> bool:
    """Return True when semantic detection is confident enough to assist routing."""
    intent = _safe_str(result.get("intent"))
    score = float(result.get("score") or 0.0)
    margin = float(result.get("margin") or 0.0)
    available = bool(result.get("available"))
    return (
        available
        and intent in SUPPORTED_BRANCH_INTENTS
        and score >= MIN_CONFIDENCE_SCORE
        and margin >= MIN_CONFIDENCE_MARGIN
    )


if __name__ == "__main__":
    try:
        import sys

        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    samples = [
        "الرياض",
        "وين فروعكم بالرياض",
        "فرع النرجس",
        "في النرجس",
        "2",
    ]
    for sample in samples:
        result = detect_branch_semantic_intent(sample)
        print(f"Q: {sample}")
        print(
            "intent={intent} score={score:.4f} margin={margin:.4f} available={available}".format(
                intent=_safe_str(result.get("intent")),
                score=float(result.get("score") or 0.0),
                margin=float(result.get("margin") or 0.0),
                available=bool(result.get("available")),
            )
        )
        print(f"confident={is_confident_branch_intent(result)}")
        print("-" * 72)
