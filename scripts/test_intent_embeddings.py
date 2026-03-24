from __future__ import annotations

import json
import math
import sys
import urllib.error
import urllib.request
from typing import Any

OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODEL_NAME = "qwen3-embedding"

INTENT_SEEDS: dict[str, list[str]] = {
    "branch_general": [
        "وين فروعكم",
        "عندكم فروع",
        "أبي الفروع",
    ],
    "branch_city": [
        "أبي فروع الرياض",
        "فروع جدة",
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

TEST_QUERIES = [
    "وين فروعكم",
    "الرياض",
    "وين فروعكم بالرياض",
    "عندكم فرع بالعليا",
    "في النرجس",
    "2",
]


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
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc

    emb = data.get("embedding")
    if not isinstance(emb, list) or not emb:
        raise RuntimeError(f"Invalid embedding payload for text: {text}")
    return [float(x) for x in emb]


def _build_intent_centroids() -> dict[str, list[float]]:
    centroids: dict[str, list[float]] = {}
    for intent, examples in INTENT_SEEDS.items():
        vectors = [_embed_text(example) for example in examples]
        dim = len(vectors[0])
        avg = [0.0] * dim
        for vec in vectors:
            for i, v in enumerate(vec):
                avg[i] += v
        centroids[intent] = [v / len(vectors) for v in avg]
    return centroids


def _predict_intent(query: str, centroids: dict[str, list[float]]) -> tuple[str, dict[str, float]]:
    q_vec = _embed_text(query)
    scores = {intent: _cosine_similarity(q_vec, c_vec) for intent, c_vec in centroids.items()}
    best_intent = max(scores.items(), key=lambda x: x[1])[0]
    return best_intent, scores


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print(f"Model: {MODEL_NAME}")
    print(f"Endpoint: {OLLAMA_URL}")
    print("-" * 72)

    try:
        centroids = _build_intent_centroids()
    except Exception as exc:
        print(f"Failed to build intent embeddings: {exc}")
        return 1

    for query in TEST_QUERIES:
        try:
            predicted, scores = _predict_intent(query, centroids)
        except Exception as exc:
            print(f"Query: {query}")
            print(f"Prediction error: {exc}")
            print("-" * 72)
            continue

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        print(f"Query: {query}")
        print(f"Predicted intent: {predicted}")
        print("Similarity scores:")
        for intent, score in ranked:
            print(f"  - {intent}: {score:.4f}")
        print("-" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
