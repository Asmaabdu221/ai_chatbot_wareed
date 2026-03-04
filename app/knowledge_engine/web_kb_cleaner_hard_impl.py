from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.paths import SOURCES_WEB_DIR

CTA_PATTERNS = [
    r"\u0627\u062d\u062c\u0632(?:\s+\u0627\u0644\u0622\u0646|\s+\u0627\u0644\u0627\u0646)?",
    r"\u0633\u064a\u062a\u0645\s+\u0627\u0644\u062a\u0648\u0627\u0635\u0644",
    r"\u062a\u0623\u0643\u064a\u062f\s+\u0627\u0644\u062d\u062c\u0632|\u0644\u062a\u0623\u0643\u064a\u062f\s+\u0627\u0644\u062d\u062c\u0632",
    r"\u0623\u0642\u0631\u0628\s+\u0641\u0631\u0639",
    r"\u0645\u062e\u062a\u0628\u0631\u0627\u062a\s+\u0648\u0631\u064a\u062f",
    r"\u0648\u0631\u064a\u062f\s+\u0627\u0644\u0637\u0628\u064a\u0629",
    r"\u0627\u0637\u0645\u0626\u0646",
    r"\u0631\u0627\u0642\u0628",
    r"\u0627\u0628\u062f\u0623\s+\u0631\u062d\u0644\u062a\u0643|\u0627\u0628\u062f\u0627\s+\u0631\u062d\u0644\u062a\u0643",
    r"\u0636\u0645\u0646\s+\u0628\u0627\u0642\u0627\u062a",
    r"\u062e\u062f\u0645\u0629\s+\u0633\u062d\u0628",
    r"\u0648\u0627\u062a\u0633\u0627\u0628|whatsapp",
    r"\u0645\u0646\s+\u0642\u0628\u0644\s+\u0648\u0631\u064a\u062f",
]

GENERIC_PATTERNS = [
    r"\u0644\u0645\u0627\u0630\u0627\s+\u062a\u062e\u062a\u0627\u0631",
    r"\u0645\u0646\s+\u0639\u0631\u0648\u0636\u0646\u0627",
    r"\u0627\u0628\u062f\u0623\s+\u0631\u062d\u0644\u062a\u0643|\u0627\u0628\u062f\u0627\s+\u0631\u062d\u0644\u062a\u0643",
]

TAG_STOPWORDS = {
    "\u0645\u062e\u062a\u0628\u0631\u0627\u062a",
    "\u0648\u0631\u064a\u062f",
    "\u0627\u0644\u0637\u0628\u064a\u0629",
    "\u062f\u0642\u0629",
    "\u0648\u0645\u0648\u062b\u0648\u0642\u064a\u0629",
    "\u0645\u0648\u062b\u0648\u0642\u064a\u0629",
    "\u062a\u062d\u0644\u064a\u0644",
    "\u0641\u062d\u0635",
}

MED_CODE_CANONICAL = {
    "hba1c": "HbA1c",
    "psa": "PSA",
    "tibc": "TIBC",
    "ldl": "LDL",
    "hdl": "HDL",
    "fsh": "FSH",
    "lh": "LH",
    "e2": "E2",
    "gfr": "GFR",
    "cbc": "CBC",
    "alt": "ALT",
    "ast": "AST",
    "crp": "CRP",
    "esr": "ESR",
    "tsh": "TSH",
    "t3": "T3",
    "t4": "T4",
    "igg": "IgG",
    "igm": "IgM",
    "pcr": "PCR",
    "hcv": "HCV",
    "hbv": "HBV",
    "hiv": "HIV",
    "amh": "AMH",
    "creatinine": "Creatinine",
    "calcium": "Calcium",
    "phosphorus": "Phosphorus",
}

DISEASE_TOKEN_BLOCKLIST = {"pcos", "scurvy"}
PREP_KEYWORDS = (
    "\u0635\u064a\u0627\u0645",
    "\u0642\u0628\u0644 \u0627\u0644\u0641\u062d\u0635",
    "\u0642\u0628\u0644 \u0627\u0644\u062a\u062d\u0644\u064a\u0644",
    "\u0627\u0644\u0623\u062f\u0648\u064a\u0629",
    "\u0627\u0644\u0627\u062f\u0648\u064a\u0629",
    "\u0627\u0644\u064a\u0648\u0645",
    "\u0627\u0644\u062f\u0648\u0631\u0629",
    "\u0633\u0627\u0639\u0629",
)
INDICATION_KEYWORDS = (
    "\u064a\u0637\u0644\u0628",
    "\u064a\u0633\u062a\u062e\u062f\u0645",
    "\u062a\u0634\u062e\u064a\u0635",
    "\u0645\u062a\u0627\u0628\u0639\u0629",
    "\u062a\u0642\u064a\u064a\u0645",
    "\u0642\u064a\u0627\u0633",
    "\u062f\u0648\u0627\u0639\u064a",
)
DEF_KEYWORDS = ("\u062a\u062d\u0644\u064a\u0644", "\u0641\u062d\u0635", "\u064a\u0642\u064a\u0633", "\u0647\u0631\u0645\u0648\u0646")


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = (
        text.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ئ", "ي")
        .replace("ؤ", "و")
        .replace("ة", "ه")
    )
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _stable_doc_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _normalize_punct_spacing(text: str) -> str:
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"\s+([.,;:!?؟،])", r"\1", t)
    t = re.sub(r"([.,;:!?؟،])(\S)", r"\1 \2", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!؟\n])\s+", text)
    return [_normalize_punct_spacing(p) for p in parts if _normalize_punct_spacing(p)]


def _dedupe_sentences(sentences: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in sentences:
        key = normalize_text(s)
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _remove_cta_and_noise(content: str) -> str:
    text = _normalize_punct_spacing(content)
    text = re.sub(r"(?:\+?\d[\d\-\s]{6,}\d)", " ", text)
    for pattern in CTA_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    kept: list[str] = []
    for s in _split_sentences(text):
        n = normalize_text(s)
        if any(re.search(p, n) for p in GENERIC_PATTERNS):
            continue
        if re.search(r"(\u0627\u062d\u062c\u0632|\u062a\u0648\u0627\u0635\u0644|\u0648\u0627\u062a\u0633\u0627\u0628|\u0641\u0631\u0639|\u0628\u0627\u0642\u0627\u062a|\u062e\u062f\u0645\u0629 \u0633\u062d\u0628|\u0648\u0631\u064a\u062f|\u0645\u0639\u0643)", n):
            continue
        kept.append(s)
    return _normalize_punct_spacing(" ".join(kept))


def _compose_short_medical_content(sentences: list[str], max_chars: int = 1200) -> str:
    defs: list[str] = []
    uses: list[str] = []
    prep: list[str] = []
    for s in sentences:
        n = normalize_text(s)
        if len(n) < 16:
            continue
        if len(defs) < 2 and any(k in n for k in DEF_KEYWORDS):
            defs.append(s)
            continue
        if any(k in n for k in PREP_KEYWORDS):
            if len(prep) < 3:
                prep.append(s)
            continue
        if any(k in n for k in INDICATION_KEYWORDS):
            if len(uses) < 5:
                uses.append(s)
            continue
        if len(uses) < 5:
            uses.append(s)
    ordered = defs[:2] + [f"- {x}" for x in uses[:5]] + [f"- {x}" for x in prep[:3]]
    text = _normalize_punct_spacing("\n".join(ordered)).strip()
    return text[:max_chars].rstrip()


def _summary_ar(content_clean: str, max_chars: int = 280) -> str:
    sents = [x.strip(" -") for x in _split_sentences(content_clean) if x.strip(" -")]
    if not sents:
        return ""
    out = sents[0]
    if len(out) < max_chars and len(sents) > 1:
        c = f"{out} {sents[1]}"
        if len(c) <= max_chars:
            out = c
    return out[:max_chars].strip()


def _clean_test_name(h1: str, title: str) -> str:
    value = (h1 or title or "").strip()
    value = re.sub(r"^\s*(?:\u062a\u062d\u0644\u064a\u0644|\u0641\u062d\u0635)\s+", "", value).strip()
    value = re.sub(r"\s*\|.*$", "", value).strip()
    return _normalize_punct_spacing(value)[:140]


def _reclassify_page_type(existing: str, title: str, h1: str) -> str:
    joined = normalize_text(f"{title} {h1}")
    if "\u062a\u062d\u0644\u064a\u0644" in joined or "\u0641\u062d\u0635" in joined:
        return "test_page"
    return existing or "web_page"


def _slug_tokens(url: str) -> list[str]:
    words = [w for w in re.split(r"[-_/]", urlparse(url).path.strip("/").lower()) if w]
    out: list[str] = []
    for w in words:
        key = re.sub(r"[^a-z0-9]", "", w)
        if key in MED_CODE_CANONICAL:
            out.append(MED_CODE_CANONICAL[key])
    if "hemoglobin" in words and "a1c" in words:
        out.append("HbA1c")
    return out


def _extract_parenthetical_tokens(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"\(([A-Za-z0-9\-\s]{2,20})\)", text or "")]


def _extract_upper_tokens(text: str) -> list[str]:
    return re.findall(r"\b[A-Z0-9]{2,8}\b", text or "")


def _canonical_lab_token(token: str) -> str:
    raw = re.sub(r"[^a-z0-9]", "", token.lower())
    if not raw or raw.isdigit() or raw in DISEASE_TOKEN_BLOCKLIST:
        return ""
    return MED_CODE_CANONICAL.get(raw, "")


def _extract_test_code_tokens(url: str, title: str, h1: str, content_clean: str) -> list[str]:
    candidates = _slug_tokens(url)
    candidates += _extract_parenthetical_tokens(f"{title} {h1} {content_clean}")
    candidates += _extract_upper_tokens(content_clean)
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        tok = _canonical_lab_token(c)
        if tok and tok.lower() not in seen:
            seen.add(tok.lower())
            out.append(tok)
            if len(out) >= 8:
                break
    return out


def _extract_disease_like_tokens(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in _extract_upper_tokens(text):
        k = t.lower()
        if k in DISEASE_TOKEN_BLOCKLIST and k not in seen:
            seen.add(k)
            out.append(t.upper())
    return out


def _extract_tags(test_name_ar: str, test_code_tokens: list[str], disease_tokens: list[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for token in test_code_tokens + disease_tokens:
        key = normalize_text(token)
        if key and key not in seen:
            seen.add(key)
            tags.append(token)
    for w in re.findall(r"[A-Za-z0-9\u0600-\u06FF]+", test_name_ar):
        key = normalize_text(w)
        if key and key not in seen and key not in TAG_STOPWORDS:
            seen.add(key)
            tags.append(w)
            if len(tags) >= 10:
                break
    return tags[:10]


def _chunk_text(text: str, target_max: int = 900, overlap: int = 80) -> list[str]:
    if not text.strip():
        return []
    sents = _split_sentences(text)
    chunks: list[str] = []
    current = ""
    for s in sents:
        cand = f"{current} {s}".strip() if current else s
        if len(cand) <= target_max:
            current = cand
            continue
        if current:
            chunks.append(current)
            tail = current[-overlap:] if len(current) > overlap else current
            current = f"{tail} {s}".strip()
        else:
            chunks.append(s[:target_max])
            current = ""
    if current:
        chunks.append(current)
    return [c[:900].strip() for c in chunks if c.strip()]


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def clean_site_knowledge_jsonl(input_path: Path, clean_out: Path, chunks_out: Path) -> dict:
    rows = _iter_jsonl(input_path)
    docs: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        if row.get("status_code") != 200 or row.get("error"):
            dropped += 1
            continue
        url = str(row.get("url", "") or "").strip()
        if not url:
            dropped += 1
            continue
        title = _normalize_punct_spacing(str(row.get("title", "") or ""))
        h1 = _normalize_punct_spacing(str(row.get("h1", "") or ""))
        page_type = _reclassify_page_type(str(row.get("page_type", "") or "").strip(), title, h1)
        content_clean = _compose_short_medical_content(
            _dedupe_sentences(_split_sentences(_remove_cta_and_noise(str(row.get("content", "") or "")))),
            max_chars=1200,
        )
        content_clean = _normalize_punct_spacing(content_clean)
        if len(content_clean) < 120:
            dropped += 1
            continue
        test_name_ar = _clean_test_name(h1, title)
        test_code_tokens = _extract_test_code_tokens(url, title, h1, content_clean)
        disease_tokens = _extract_disease_like_tokens(f"{title} {h1} {content_clean}")
        tags = _extract_tags(test_name_ar, test_code_tokens, disease_tokens)
        doc_id = _stable_doc_id(url)
        docs.append(
            {
                "id": doc_id,
                "source_type": "website",
                "url": url,
                "lang": str(row.get("lang", "") or "").strip(),
                "page_type": page_type,
                "title": title,
                "h1": h1,
                "test_name_ar": test_name_ar,
                "test_code_tokens": test_code_tokens,
                "content_clean": content_clean,
                "summary_ar": _summary_ar(content_clean, max_chars=280),
                "tags": tags,
            }
        )
        for i, txt in enumerate(_chunk_text(content_clean), start=1):
            chunks.append(
                {
                    "chunk_id": f"{doc_id}_{i:03d}",
                    "doc_id": doc_id,
                    "url": url,
                    "page_type": page_type,
                    "test_name_ar": test_name_ar,
                    "test_code_tokens": test_code_tokens,
                    "tags": tags,
                    "text": txt,
                }
            )
    clean_out.parent.mkdir(parents=True, exist_ok=True)
    chunks_out.parent.mkdir(parents=True, exist_ok=True)
    with clean_out.open("w", encoding="utf-8") as fh:
        for d in docs:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    with chunks_out.open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    return {"input_rows": len(rows), "kept_docs": len(docs), "dropped_docs": dropped, "chunk_rows": len(chunks)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Hard cleaner for website KB")
    parser.add_argument("--in", dest="input_path", type=Path, default=SOURCES_WEB_DIR / "site_knowledge.jsonl")
    parser.add_argument("--clean-out", dest="clean_out", type=Path, default=SOURCES_WEB_DIR / "site_knowledge_clean_hard.jsonl")
    parser.add_argument("--chunks-out", dest="chunks_out", type=Path, default=SOURCES_WEB_DIR / "site_knowledge_chunks_hard.jsonl")
    args = parser.parse_args()
    s = clean_site_knowledge_jsonl(args.input_path, args.clean_out, args.chunks_out)
    print(f"input_rows={s['input_rows']}, kept_docs={s['kept_docs']}, dropped_docs={s['dropped_docs']}, chunk_rows={s['chunk_rows']}")


if __name__ == "__main__":
    main()
