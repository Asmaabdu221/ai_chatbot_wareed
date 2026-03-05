from __future__ import annotations

import argparse
import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.paths import SOURCES_WEB_DIR

CTA_PATTERNS = [
    r"\u0627\u062d\u062c\u0632(?:\s+\u0627\u0644\u0622\u0646|\s+\u0627\u0644\u0627\u0646)?",
    r"\u0633\u064a\u062a\u0645\s+\u0627\u0644\u062a\u0648\u0627\u0635\u0644",
    r"\u062a\u0623\u0643\u064a\u062f\s+\u0627\u0644\u062d\u062c\u0632|\u0644\u062a\u0623\u0643\u064a\u062f\s+\u0627\u0644\u062d\u062c\u0632",
    r"\u0623\u0642\u0631\u0628\s+\u0641\u0631\u0639",
    r"\u0645\u062e\u062a\u0628\u0631\u0627\u062a\s+\S*",
    r"\u0648\u0631\u064a\u062f(?:\s+\u0627\u0644\u0637\u0628\u064a\u0629)?",
    r"\u0641\u064a\s+\u0627\u0644\u0637\u0628\u064a\u0629",
    r"\u0627\u0637\u0645\u0626\u0646",
    r"\u0631\u0627\u0642\u0628",
    r"\u0627\u0628\u062f\u0623\s+\u0631\u062d\u0644\u062a\u0643|\u0627\u0628\u062f\u0627\s+\u0631\u062d\u0644\u062a\u0643",
    r"\u0636\u0645\u0646\s+\u0628\u0627\u0642\u0627\u062a",
    r"\u062e\u062f\u0645\u0629\s+\u0645\u0646\u0632\u0644\u064a\u0629",
    r"\u062e\u062f\u0645\u0629\s+\u0633\u062d\u0628",
    r"\u0648\u0627\u062a\u0633\u0627\u0628|whatsapp",
    r"\u0646\u062a\u0627\u0626\u062c\s+\u062f\u0642\u064a\u0642\u0629|\u0646\u062a\u0627\u0626\u062c\s+\u0633\u0631\u064a\u0639\u0629",
    r"\u062e\u0644\u0627\u0644\s*24|\u062e\u0644\u0627\u0644\s*48|48\s+\u0633\u0627\u0639\u0629",
    r"\u0646\u0636\u0645\u0646\s+\u0644\u0643",
    r"\u062a\u062d\u062a\s+\u0625\u0634\u0631\u0627\u0641",
    r"\u0645\u0639\u0643",
    r"\u0628\u0627\u0642\u0629\s+\u0627\u0644\u062a\u062d\u0627\u0644\u064a\u0644",
    r"\u0636\u0645\u0646\s+\u0628\u0627\u0642\u0629",
    r"\u0628\u0627\u0642\u0629\s+\u0627\u0644\u062a\u062d\u0627\u0644\u064a\u0644",
    r"\u0636\u0645\u0646\s+\u0628\u0627\u0642\u0629",
    r"\u062a\u0648\u0627\u0635\u0644",
    r"\u0644\u062a\u0623\u0643\u064a\u062f\s+\u0627\u0644\u062d\u062c\u0632",
    r"\u0627\u0644\u0637\u0628\u064a\u0629",
]
GENERIC_PATTERNS = [
    r"\u0644\u0645\u0627\u0630\u0627\s+\u062a\u062e\u062a\u0627\u0631",
    r"\u0645\u0646\s+\u0639\u0631\u0648\u0636\u0646\u0627",
    r"\u0627\u0628\u062f\u0623\s+\u0631\u062d\u0644\u062a\u0643|\u0627\u0628\u062f\u0627\s+\u0631\u062d\u0644\u062a\u0643",
]

LAB_TOKEN_CANONICAL = {
    "hba1c": "HbA1c",
    "cbc": "CBC",
    "psa": "PSA",
    "freepsa": "Free PSA",
    "ldl": "LDL",
    "hdl": "HDL",
    "rbs": "RBS",
    "fbs": "FBS",
    "ogtt": "OGTT",
    "homair": "HOMA-IR",
    "25ohd": "25(OH)D",
    "vitd": "Vit D",
    "ferritin": "Ferritin",
    "tsh": "TSH",
    "hcg": "hCG",
    "ca199": "CA 19-9",
    "afp": "AFP",
    "cea": "CEA",
    "gfr": "GFR",
    "creatinine": "Creatinine",
    "urea": "Urea",
    "tibc": "TIBC",
    "transferrin": "Transferrin",
    "fsh": "FSH",
    "lh": "LH",
    "e2": "E2",
    "pcr": "PCR",
    "crp": "CRP",
    "esr": "ESR",
    "phosphorus": "Phosphorus",
    "calcium": "Calcium",
}
DISEASE_TOKEN_BLOCKLIST = {"pcos", "scurvy", "bph"}
TAG_STOPWORDS = {
    "\u0645\u062e\u062a\u0628\u0631\u0627\u062a",
    "\u0648\u0631\u064a\u062f",
    "\u0627\u0644\u0637\u0628\u064a\u0629",
    "\u062f\u0642\u0629",
    "\u0648\u0645\u0648\u062b\u0648\u0642\u064a\u0629",
    "\u062a\u062d\u0644\u064a\u0644",
    "\u0641\u062d\u0635",
}
ARTIFACT = re.compile(r"(?:\u0644?\u0645\u0640?\s*\u0629)")
ARTIFACT_CONTEXT = (
    "\u0639\u0644\u0627\u062c",
    "\u0645\u0631\u0636\u0649",
    "\u062d\u0627\u0644\u0627\u062a",
    "\u0627\u0633\u062a\u062c\u0627\u0628\u0629",
    "\u0641\u0639\u0627\u0644\u064a\u0629",
    "\u0645\u0631\u0627\u0642\u0628\u0629",
)
DEF_WORDS = ("\u062a\u062d\u0644\u064a\u0644", "\u0641\u062d\u0635", "\u0627\u062e\u062a\u0628\u0627\u0631", "\u064a\u0642\u064a\u0633")
IND_WORDS = ("\u064a\u0637\u0644\u0628", "\u064a\u0633\u062a\u062e\u062f\u0645", "\u062a\u0634\u062e\u064a\u0635", "\u0645\u062a\u0627\u0628\u0639\u0629", "\u062a\u0642\u064a\u064a\u0645")
PREP_WORDS = ("\u0635\u064a\u0627\u0645", "\u0642\u0628\u0644 \u0627\u0644\u0641\u062d\u0635", "\u0642\u0628\u0644 \u0627\u0644\u062a\u062d\u0644\u064a\u0644", "\u0627\u0644\u0623\u062f\u0648\u064a\u0629", "\u0627\u0644\u064a\u0648\u0645")

POST_REPAIRS = {
    "\u0627\u0644\u0623\u0637\u0639": "\u0627\u0644\u0623\u0637\u0639\u0645\u0629",
    "\u0627\u0644\u0645\u0647": "\u0627\u0644\u0645\u0647\u0645",
    "\u0627\u0644\u0639\u0640\u0627": "\u0627\u0644\u0639\u0627\u0645\u0629",
    "\u0627\u0644\u0639 \u0627": "\u0627\u0644\u0639\u0627\u0645\u0629",
    "\u0645\u062a\u0642\u062f": "\u0645\u062a\u0642\u062f\u0645\u0629",
    "\u0645\u0642\u0627\u0648": "\u0645\u0642\u0627\u0648\u0645\u0629",
    "\u0642\u064a \u0639\u062f\u062f\u064a\u0629": "\u0642\u064a\u0645\u0629 \u0639\u062f\u062f\u064a\u0629",
}


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = (
        text.replace("\u0623", "\u0627")
        .replace("\u0625", "\u0627")
        .replace("\u0622", "\u0627")
        .replace("\u0649", "\u064a")
        .replace("\u0626", "\u064a")
        .replace("\u0624", "\u0648")
        .replace("\u0629", "\u0647")
    )
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _stable_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _normalize_punct(text: str) -> str:
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"\s+([.,;:!?؟،])", r"\1", t)
    t = re.sub(r"([.,;:!?؟،])(\S)", r"\1 \2", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t)
    t = t.replace("\u2022", "- ").replace("\u2013", "- ").replace("\u2014", "- ")
    t = re.sub(r"^\s*-\s*", "", t, flags=re.MULTILINE)
    return t.strip(" \n-،,;:.")


def _repair_artifacts(text: str) -> str:
    out = text
    while True:
        m = ARTIFACT.search(out)
        if not m:
            break
        window = normalize_text(out[max(0, m.start() - 30) : min(len(out), m.end() + 30)])
        repl = "\u0645\u062a\u0627\u0628\u0639\u0629" if any(k in window for k in ARTIFACT_CONTEXT) else " "
        out = out[: m.start()] + repl + out[m.end() :]
    return out


def _post_clean_repair(text: str) -> str:
    out = text
    for bad, good in POST_REPAIRS.items():
        out = out.replace(bad, good)
    out = re.sub(r"\b[اأإآبتثجحخدذرزسشصضطظعغفقكلمنهوي]{1,2}\b(?=\s*[،.;:\n]|$)", " ", out)
    out = re.sub(r"\s+([.,;:!?؟،])", r"\1", out)
    out = re.sub(r"([.,;:!?؟،]){2,}", r"\1", out)
    return _normalize_punct(out)


def _split_sentences(text: str) -> list[str]:
    normalized = _normalize_punct(text)
    normalized = re.sub(r"\n+", "\n", normalized)
    parts = re.split(r"(?<=[.!؟\n])\s+|\n", normalized)
    out: list[str] = []
    for p in parts:
        s = _normalize_punct(p)
        if s:
            out.append(s)
    return out


def _dedupe_sentences(sentences: list[str]) -> list[str]:
    seen: list[str] = []
    out: list[str] = []
    for s in sentences:
        fp = normalize_text(s)
        if not fp:
            continue
        if any(fp == x or (len(fp) > 24 and (fp in x or x in fp)) for x in seen):
            continue
        if any(SequenceMatcher(None, fp, x).ratio() >= 0.92 for x in seen):
            continue
        seen.append(fp)
        out.append(s)
    return out


def _clean_content(raw: str) -> str:
    t = _normalize_punct(raw)
    t = re.sub(r"(?:\+?\d[\d\-\s]{6,}\d)", " ", t)
    for pat in CTA_PATTERNS:
        t = re.sub(pat, " ", t, flags=re.IGNORECASE)
    t = _repair_artifacts(t)
    kept: list[str] = []
    for s in _split_sentences(t):
        n = normalize_text(s)
        if any(re.search(p, n) for p in GENERIC_PATTERNS):
            continue
        if re.search(r"(احجز|تواصل|واتساب|فرع|خدمة منزلية|خدمة سحب|وريد|مختبرات|نضمن|خلال 24|48 ساعة|معك)", n):
            continue
        kept.append(s)
    ded = _dedupe_sentences(kept)
    defs = [s for s in ded if any(k in normalize_text(s) for k in DEF_WORDS)][:2]
    uses = [s for s in ded if any(k in normalize_text(s) for k in IND_WORDS)][:4]
    prep = [s for s in ded if any(k in normalize_text(s) for k in PREP_WORDS)][:2]
    content = defs + [f"- {x}" for x in uses + prep]
    unique_lines: list[str] = []
    seen_lines: set[str] = set()
    for line in content:
        key = normalize_text(re.sub(r"^\s*-\s*", "", line))
        if not key or key in seen_lines:
            continue
        seen_lines.add(key)
        unique_lines.append(line)
    text = _normalize_punct("\n".join(unique_lines))
    if len(text) > 900:
        text = text[:900].rstrip()
    text = _post_clean_repair(text)
    return text if len(text) >= 120 else ""


def _sanitize_text_field(text: str) -> str:
    out = _normalize_punct(text)
    for pat in CTA_PATTERNS:
        out = re.sub(pat, " ", out, flags=re.IGNORECASE)
    out = _repair_artifacts(out)
    out = re.sub(r"\b\u0627\u0644\u0637\u0628\u064a\u0629\b", " ", out)
    return _post_clean_repair(out)


def _strip_banned_global(text: str) -> str:
    out = str(text or "")
    out = re.sub(r"\b\u0627\u0644\u0637\u0628\u064a\u0629\b", " ", out)
    for pat in CTA_PATTERNS:
        out = re.sub(pat, " ", out, flags=re.IGNORECASE)
    return _post_clean_repair(out)


def _summary(text: str) -> str:
    sents = [s.strip(" -") for s in _split_sentences(text) if s.strip(" -")]
    if not sents:
        return ""
    s = sents[0]
    if len(s) < 220 and len(sents) > 1:
        s2 = f"{s} {sents[1]}"
        if len(s2) <= 220:
            s = s2
    return s[:220]


def _page_type(existing: str, title: str, h1: str, content: str) -> str:
    joined = normalize_text(f"{title} {h1} {content}")
    if any(w in joined for w in ("\u062a\u062d\u0644\u064a\u0644", "\u0641\u062d\u0635", "\u0627\u062e\u062a\u0628\u0627\u0631")):
        return "test_page"
    return "general_page"


def _extract_codes(url: str, title: str, h1: str, content: str) -> list[str]:
    cands: list[str] = []
    words = [w for w in re.split(r"[-_/]", urlparse(url).path.strip("/").lower()) if w]
    if "hemoglobin" in words and "a1c" in words:
        cands.append("HbA1c")
    if "free" in words and "psa" in words:
        cands.append("Free PSA")
    for w in words:
        key = re.sub(r"[^a-z0-9]", "", w)
        if key in LAB_TOKEN_CANONICAL:
            cands.append(LAB_TOKEN_CANONICAL[key])
    for src in [title, h1]:
        for m in re.finditer(r"\(([A-Za-z0-9\-\s]{2,24})\)", src or ""):
            cands.append(m.group(1).strip())
        cands.extend(re.findall(r"\b[A-Z][A-Z0-9\-]{1,10}\b", src or ""))
    # From body only when explicit code-like context appears
    for line in _split_sentences(content):
        if re.search(r"(?:\u0631\u0645\u0632|code|\u0627\u062e\u062a\u0635\u0627\u0631|\()", line, flags=re.IGNORECASE):
            for m in re.finditer(r"\(([A-Za-z0-9\-\s]{2,24})\)", line):
                cands.append(m.group(1).strip())
            cands.extend(re.findall(r"\b[A-Z][A-Z0-9\-]{1,10}\b", line))
    out: list[str] = []
    seen: set[str] = set()
    for c in cands:
        key = re.sub(r"[^a-z0-9]", "", c.lower())
        if key in DISEASE_TOKEN_BLOCKLIST:
            continue
        canon = LAB_TOKEN_CANONICAL.get(key)
        if not canon:
            continue
        if canon.lower() in seen:
            continue
        seen.add(canon.lower())
        out.append(canon)
        if len(out) >= 12:
            break
    return out


def _extract_disease_tags(text: str) -> list[str]:
    out: list[str] = []
    for token in re.findall(r"\b[A-Z][A-Z0-9\-]{1,10}\b", text or ""):
        key = re.sub(r"[^a-z0-9]", "", token.lower())
        if key in DISEASE_TOKEN_BLOCKLIST and token not in out:
            out.append(token.upper())
    return out


def _tags(test_name: str, codes: list[str], disease_tags: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in codes + disease_tags:
        k = normalize_text(t)
        if k and k not in seen:
            seen.add(k)
            out.append(t)
    for w in re.findall(r"[A-Za-z0-9\u0600-\u06FF]+", test_name):
        k = normalize_text(w)
        if not k or k in TAG_STOPWORDS or k in seen or k == "\u0627\u0644\u0637\u0628\u064a\u0629":
            continue
        out.append(w)
        seen.add(k)
        if len(out) >= 10:
            break
    return out[:10]


def _chunk(text: str, target_max: int = 900, overlap: int = 80) -> list[str]:
    sents = _split_sentences(text)
    if not sents:
        return []
    chunks: list[str] = []
    cur = ""
    for s in sents:
        cand = f"{cur} {s}".strip() if cur else s
        if len(cand) <= target_max:
            cur = cand
            continue
        if cur:
            chunks.append(cur)
            cur = f"{cur[-overlap:]} {s}".strip()
        else:
            chunks.append(s[:target_max])
            cur = ""
    if cur:
        chunks.append(cur)
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
        raw_title = str(row.get("title", "") or "")
        raw_h1 = str(row.get("h1", "") or "")
        raw_content = str(row.get("content", "") or "")
        title = _sanitize_text_field(raw_title)
        h1 = _sanitize_text_field(raw_h1)
        content_clean = _clean_content(raw_content)
        if not content_clean:
            dropped += 1
            continue
        test_name = _normalize_punct(
            re.sub(r"^\s*(?:\u062a\u062d\u0644\u064a\u0644|\u0641\u062d\u0635|\u0627\u062e\u062a\u0628\u0627\u0631)\s+", "", (h1 or title or "").strip())
        )
        test_name = _post_clean_repair(re.sub(r"\b\u0627\u0644\u0637\u0628\u064a\u0629\b", " ", test_name))
        codes = _extract_codes(url, raw_title, raw_h1, raw_content)
        disease = _extract_disease_tags(f"{title} {h1} {content_clean}")
        page_type = _page_type(str(row.get("page_type", "") or "").strip(), title, h1, content_clean)
        doc_id = _stable_id(url)
        title = _strip_banned_global(title)
        h1 = _strip_banned_global(h1)
        test_name = _strip_banned_global(test_name)
        content_clean = _strip_banned_global(content_clean)
        if not content_clean or len(content_clean) < 120:
            dropped += 1
            continue
        summary = _strip_banned_global(_summary(content_clean))
        tags = [_strip_banned_global(t) for t in _tags(test_name, codes, disease)]
        tags = [t for t in tags if t]
        docs.append(
            {
                "id": doc_id,
                "source_type": "website",
                "url": url,
                "lang": str(row.get("lang", "") or "").strip(),
                "page_type": page_type,
                "title": title,
                "h1": h1,
                "test_name_ar": test_name[:140],
                "test_code_tokens": codes,
                "content_clean": content_clean,
                "summary_ar": summary,
                "tags": tags,
            }
        )
        for i, txt in enumerate(_chunk(content_clean), start=1):
            chunks.append(
                {
                    "chunk_id": f"{doc_id}_{i:03d}",
                    "doc_id": doc_id,
                    "url": url,
                    "page_type": page_type,
                    "test_name_ar": test_name[:140],
                    "test_code_tokens": codes,
                    "tags": tags,
                    "text": _strip_banned_global(txt),
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
