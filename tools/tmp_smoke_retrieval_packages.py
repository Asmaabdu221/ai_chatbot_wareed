import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def score(query: str, row: dict) -> float:
    qn = normalize(query)
    text = normalize(row.get("text", ""))
    name = normalize(row.get("package_name", ""))
    tags = normalize(" ".join(row.get("tags", [])))
    sc = 0.0

    for phrase, weight in [
        ("نهار رمضان", 9),
        ("ليالي رمضان", 9),
        ("السكر والدهون", 12),
        ("رمضان", 2),
        ("سعر", 2),
        ("تشمل", 2),
    ]:
        if phrase in qn and phrase in name:
            sc += weight
        if phrase in qn and phrase in text:
            sc += weight / 2

    for tok in [t for t in re.split(r"\s+", qn) if len(t) > 1]:
        if tok in name:
            sc += 4
        if tok in tags:
            sc += 2
        if tok in text:
            sc += 1

    if row.get("chunk_type") == "card":
        sc += 0.2
    return sc


def main() -> None:
    path = Path("app/data/runtime/rag/packages_chunks.jsonl")
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    queries = [
        "كم سعر باقة نهار رمضان الشاملة؟",
        "ايش تشمل باقة ليالي رمضان؟",
        "ابغى فحوصات للسكر والدهون في رمضان",
    ]

    for q in queries:
        ranked = sorted(rows, key=lambda r: score(q, r), reverse=True)
        print(f"QUERY: {q}")
        for r in ranked[:3]:
            txt = normalize(r.get("text", ""))
            print(f"- {r['id']} | {txt[:120]}")


if __name__ == "__main__":
    main()
