"""
Build Style System
==================
Builds a style dataset from messaging transcripts and precomputes embeddings.

Usage:
  python -m app.data.build_style_system --input "C:\\path\\to\\messaging_transcripts.csv"
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from app.core.config import settings
from app.services.embeddings_service import get_embeddings

logger = logging.getLogger(__name__)

DEFAULT_MAX_MESSAGE_CHARS = 700
STYLE_PAIRS_PATH = Path(__file__).resolve().parent / "style_pairs.jsonl"
STYLE_EMBEDDINGS_PATH = Path(__file__).resolve().parent / "style_embeddings.json"

ARABIC_NORMALIZE_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
    }
)

BANNED_ESCALATION_PHRASES = (
    "سوف نتواصل",
    "سنقوم بالتواصل",
    "سيتم التواصل",
    "راح نتواصل",
    "someone will reach out",
    "we will contact you",
    "we'll contact you",
    "we will forward",
    "سنحول طلبك",
    "راح نحول طلبك",
)


@dataclass
class MessageRow:
    conversation_id: str
    timestamp: str
    sender_type: str
    message_text: str


def _parse_timestamp(value: str) -> datetime:
    if not value:
        return datetime.min
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(v)
    except Exception:
        return datetime.min


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_arabic(text: str) -> str:
    text = text.translate(ARABIC_NORMALIZE_MAP)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    return text


def _redact_pii(text: str) -> str:
    text = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "[EMAIL]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?<!\w)(?:\+?\d[\d\-\s()]{7,}\d)(?!\w)",
        "[PHONE]",
        text,
    )
    text = re.sub(r"\b\d{7,}\b", "[ID]", text)
    return text


def _trim_emojis(text: str, max_emojis: int = 2) -> str:
    emoji_pattern = re.compile(
        "["  # broad unicode emoji blocks
        "\U0001F300-\U0001FAFF"
        "\U00002700-\U000027BF"
        "\U0001F1E6-\U0001F1FF"
        "]",
        flags=re.UNICODE,
    )
    keep = max_emojis
    out: List[str] = []
    for ch in text:
        if emoji_pattern.match(ch):
            if keep > 0:
                out.append(ch)
                keep -= 1
            continue
        out.append(ch)
    return "".join(out)


def _clean_message(text: str, max_chars: int) -> str:
    if not text:
        return ""
    value = _normalize_whitespace(text)
    value = _normalize_arabic(value)
    value = _redact_pii(value)
    value = _trim_emojis(value, max_emojis=2)
    value = _normalize_whitespace(value)
    if len(value) > max_chars:
        value = value[:max_chars].rstrip()
    return value


def _read_rows(csv_path: Path) -> Tuple[List[MessageRow], int]:
    rows: List[MessageRow] = []
    raw_messages = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for rec in reader:
            raw_messages += 1
            rows.append(
                MessageRow(
                    conversation_id=(rec.get("conversationId") or "").strip(),
                    timestamp=(rec.get("timestamp") or "").strip(),
                    sender_type=(rec.get("senderType") or "").strip().lower(),
                    message_text=(rec.get("messageText") or "").strip(),
                )
            )
    return rows, raw_messages


def _extract_pairs(rows: Iterable[MessageRow], max_chars: int) -> Tuple[List[Dict[str, str]], int]:
    grouped: Dict[str, List[MessageRow]] = defaultdict(list)
    for row in rows:
        if not row.conversation_id:
            continue
        grouped[row.conversation_id].append(row)

    pairs: List[Dict[str, str]] = []
    skipped = 0

    for conv_id, conv_rows in grouped.items():
        conv_rows.sort(key=lambda x: _parse_timestamp(x.timestamp))
        waiting_customers: deque[str] = deque()

        for row in conv_rows:
            if row.sender_type not in {"customer", "agent"}:
                continue
            cleaned = _clean_message(row.message_text, max_chars=max_chars)
            if not cleaned:
                skipped += 1
                continue

            if row.sender_type == "customer":
                waiting_customers.append(cleaned)
                continue

            # row.sender_type == "agent"
            if not waiting_customers:
                skipped += 1
                continue

            customer_text = waiting_customers.popleft()
            lower_agent = cleaned.lower()
            if any(phrase in lower_agent for phrase in BANNED_ESCALATION_PHRASES):
                skipped += 1
                continue

            pairs.append(
                {
                    "conversation_id": conv_id,
                    "customer": customer_text,
                    "agent": cleaned,
                }
            )

        skipped += len(waiting_customers)

    return pairs, skipped


def _write_jsonl(path: Path, pairs: List[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for pair in pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")


def _build_embeddings_payload(pairs: List[Dict[str, str]]) -> Dict[str, object]:
    docs = [f"Customer: {p['customer']}\nAgent: {p['agent']}" for p in pairs]
    vectors = get_embeddings(docs, batch_size=max(1, len(docs))) if docs else []
    if len(vectors) != len(pairs):
        logger.warning(
            "Embeddings count mismatch (expected=%s, got=%s). Filling missing with empty vectors.",
            len(pairs),
            len(vectors),
        )
        if len(vectors) < len(pairs):
            vectors.extend([[] for _ in range(len(pairs) - len(vectors))])
        else:
            vectors = vectors[: len(pairs)]

    return {
        "version": 1,
        "embedding_model": settings.OPENAI_EMBEDDING_MODEL,
        "count": len(pairs),
        "pairs": pairs,
        "pair_embeddings": vectors,
    }


def build_style_system(
    input_path: str,
    output_pairs_path: Optional[str] = None,
    output_embeddings_path: Optional[str] = None,
    max_message_chars: int = DEFAULT_MAX_MESSAGE_CHARS,
) -> Dict[str, int]:
    csv_path = Path(input_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {csv_path}")

    pairs_path = Path(output_pairs_path) if output_pairs_path else STYLE_PAIRS_PATH
    embeddings_path = Path(output_embeddings_path) if output_embeddings_path else STYLE_EMBEDDINGS_PATH

    rows, total_raw = _read_rows(csv_path)
    pairs, skipped = _extract_pairs(rows, max_chars=max_message_chars)

    _write_jsonl(pairs_path, pairs)
    payload = _build_embeddings_payload(pairs)
    with embeddings_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    stats = {
        "total_raw_messages": total_raw,
        "valid_style_pairs": len(pairs),
        "rejected_or_skipped_pairs": skipped,
    }
    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build style pairs and embeddings from transcripts CSV.")
    parser.add_argument("--input", required=True, help="Path to messaging_transcripts.csv")
    parser.add_argument("--output-pairs", default=str(STYLE_PAIRS_PATH), help="Output path for style_pairs.jsonl")
    parser.add_argument("--output-embeddings", default=str(STYLE_EMBEDDINGS_PATH), help="Output path for style_embeddings.json")
    parser.add_argument("--max-message-chars", type=int, default=DEFAULT_MAX_MESSAGE_CHARS, help="Max chars per message after cleaning")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _parse_args()
    stats = build_style_system(
        input_path=args.input,
        output_pairs_path=args.output_pairs,
        output_embeddings_path=args.output_embeddings,
        max_message_chars=args.max_message_chars,
    )

    logger.info("Style system build completed.")
    logger.info("Total raw messages: %s", stats["total_raw_messages"])
    logger.info("Valid style pairs extracted: %s", stats["valid_style_pairs"])
    logger.info("Rejected/skipped pairs: %s", stats["rejected_or_skipped_pairs"])
    logger.info("Output pairs: %s", args.output_pairs)
    logger.info("Output embeddings: %s", args.output_embeddings)


if __name__ == "__main__":
    main()
