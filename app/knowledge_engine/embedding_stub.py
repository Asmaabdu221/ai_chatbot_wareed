from __future__ import annotations

import hashlib
import math

EMBED_DIM = 128


def embed(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Deterministic hash-based embedding for tests/stability (not production)."""
    src = (text or "").encode("utf-8")
    values: list[float] = []
    counter = 0
    while len(values) < dim:
        digest = hashlib.sha256(src + counter.to_bytes(4, "big")).digest()
        for i in range(0, len(digest), 4):
            chunk = digest[i : i + 4]
            if len(chunk) < 4:
                continue
            num = int.from_bytes(chunk, "big") / 4294967295.0
            values.append((num * 2.0) - 1.0)
            if len(values) >= dim:
                break
        counter += 1
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]

