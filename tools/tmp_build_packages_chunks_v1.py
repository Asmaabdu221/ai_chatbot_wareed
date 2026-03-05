import json
import re
from pathlib import Path
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

in_path = Path("app/data/runtime/rag/packages_clean_v3.jsonl")
out_path = Path("app/data/runtime/rag/packages_chunks_v1.jsonl")

sentence_split_re = re.compile(r"(?<=[\.\!\?؟])\s+")
space_re = re.compile(r"\s+")


def clean_space(text: str) -> str:
    return space_re.sub(" ", text).strip()


def split_sentences(text: str):
    text = clean_space(text)
    if not text:
        return []
    sents = [s.strip() for s in sentence_split_re.split(text) if s.strip()]
    return sents if sents else [text]


def summary_1_2_sentences(description: str, max_chars: int = 250) -> str:
    desc = clean_space(description)
    if not desc:
        return ""
    snippet = desc[:max_chars]
    if len(desc) > max_chars and not desc[max_chars : max_chars + 1].isspace():
        last_space = snippet.rfind(" ")
        if last_space > 0:
            snippet = snippet[:last_space]
    sents = split_sentences(snippet)
    return " ".join(sents[:2]).strip() if sents else snippet


def dedup_tags(tags, extra):
    out, seen = [], set()
    for t in list(tags or []) + list(extra or []):
        if not isinstance(t, str):
            continue
        v = t.strip()
        if not v:
            continue
        k = v.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(v)
    return out


def chunk_detail(
    description: str,
    package_name: str,
    main_category: str,
    price_raw: str,
    target_min=450,
    target_max=650,
    overlap_words=75,
):
    prefix = f"PACKAGE: {package_name} | CATEGORY: {main_category} | PRICE: {price_raw}"
    words = clean_space(description).split()
    if not words:
        return []

    sents = split_sentences(description)
    sent_word_lens = [len(s.split()) for s in sents]
    boundaries = []
    acc = 0
    for wlen in sent_word_lens:
        acc += wlen
        boundaries.append(acc)

    chunks = []
    n = len(words)
    start = 0
    loop_guard = 0

    while start < n:
        loop_guard += 1
        if loop_guard > 200:
            break

        min_end = min(n, start + target_min)
        max_end = min(n, start + target_max)

        if min_end >= n:
            end = n
        else:
            candidates = [b for b in boundaries if min_end <= b <= max_end]
            end = candidates[-1] if candidates else max_end

        if end <= start:
            end = min(n, start + target_max)
            if end <= start:
                break

        body = " ".join(words[start:end]).strip()
        chunks.append(f"{prefix}\n{body}" if body else prefix)

        if end >= n:
            break

        next_start = end - overlap_words
        if next_start <= start:
            next_start = end
        start = max(0, next_start)

    return chunks


def main():
    packages = []
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                packages.append(json.loads(line))

    chunks = []
    longest = []

    for pkg in packages:
        package_id = pkg["id"]
        name = pkg.get("package_name", "")
        cat = pkg.get("main_category", "")
        price_raw = pkg.get("price_raw", "")
        desc = pkg.get("description", "")
        included = pkg.get("included_count")

        longest.append((name, len(desc or "")))

        summary = summary_1_2_sentences(desc, 250)
        card_lines = [str(name), str(cat), str(price_raw)]
        if included is not None:
            card_lines.append(f"included_count: {included}")
        if summary:
            card_lines.append(summary)

        chunks.append(
            {
                "id": f"{package_id}__card__0",
                "source_type": "excel",
                "lang": "ar",
                "page_type": "package_chunk",
                "package_id": package_id,
                "chunk_type": "card",
                "chunk_index": 0,
                "main_category": cat,
                "package_name": name,
                "price_raw": price_raw,
                "price_number": pkg.get("price_number"),
                "currency": pkg.get("currency"),
                "included_count": included,
                "text": "\n".join(card_lines),
                "tags": dedup_tags(pkg.get("tags", []), ["chunk:card"]),
            }
        )

        for idx, txt in enumerate(chunk_detail(desc, name, cat, price_raw, 450, 650, 75)):
            chunks.append(
                {
                    "id": f"{package_id}__detail__{idx}",
                    "source_type": "excel",
                    "lang": "ar",
                    "page_type": "package_chunk",
                    "package_id": package_id,
                    "chunk_type": "detail",
                    "chunk_index": idx,
                    "main_category": cat,
                    "package_name": name,
                    "price_raw": price_raw,
                    "price_number": pkg.get("price_number"),
                    "currency": pkg.get("currency"),
                    "included_count": included,
                    "text": txt,
                    "tags": dedup_tags(pkg.get("tags", []), ["chunk:detail"]),
                }
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for ch in chunks:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")

    num_packages = len(packages)
    num_chunks = len(chunks)
    avg_chunks = (num_chunks / num_packages) if num_packages else 0.0
    longest_sorted = sorted(longest, key=lambda x: x[1], reverse=True)[:5]
    card_samples = [c for c in chunks if c["chunk_type"] == "card"][:2]
    detail_samples = [c for c in chunks if c["chunk_type"] == "detail"][:2]

    print(f"total_packages: {num_packages}")
    print(f"total_chunks_written: {num_chunks}")
    print(f"avg_chunks_per_package: {avg_chunks:.2f}")
    print("top_5_longest_descriptions:")
    for name, count in longest_sorted:
        print(f"- {name} | {count}")
    print("first_2_card_chunks:")
    for c in card_samples:
        txt = clean_space(c.get("text", ""))
        print(f"- {c['id']} | {txt[:180]}")
    print("first_2_detail_chunks:")
    for c in detail_samples:
        txt = clean_space(c.get("text", ""))
        print(f"- {c['id']} | {txt[:180]}")


if __name__ == "__main__":
    main()
