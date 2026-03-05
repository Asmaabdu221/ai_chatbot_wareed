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

BANNED_PATTERNS = [
    r"\bالطبية\b",
    r"\bاحجز(?:\s+الآن|\s+الان)?\b",
    r"\bسيتم\s+التواصل\b",
    r"\b(?:ل)?تأكيد\s+الحجز\b",
    r"\b(?:ل)?تاكيد\s+الحجز\b",
    r"\bتواصل\b",
    r"\bأقرب\s+فرع\b",
    r"\bاقرب\s+فرع\b",
    r"\b(?:ال)?مختبرات\b",
    r"\bوريد\b",
    r"\bالوريد\b",
    r"\bوريد\s+الطبية\b",
    r"\bفي\s+الطبية\b",
    r"\bاطمئن\b",
    r"\b(?:و)?خدمة\s+منزلية\b",
    r"\b(?:و)?خدمة\s+سحب\b",
    r"\bواتساب\b",
    r"\b(?:و)?ضمن\s+باقة\b",
    r"\b(?:و)?ضمن\s+باقات\b",
    r"\bباقة\s+التحاليل\b",
    r"\bباقة\s+تحاليل\b",
    r"\bباقة\s+\S*التحاليل\b",
    r"\bابدأ\s+رحلتك\b",
    r"\bابدا\s+رحلتك\b",
    r"\bمعك\b",
    r"\bنضمن\s+لك\b",
    r"\bنتائج\s+دقيقة\b",
    r"\bنتائج\s+سريعة\b",
    r"\bالتحاليل\s+الشاملة\b",
    r"\bمن\s+قبل\b",
    r"\bعلى\s+صحة\s+قلبك\s+مع\b",
    r"\bخلال\s*24\b",
    r"\bخلال\s*48\b",
    r"\b48\s+ساعة\b",
]
GENERIC_HEADINGS = [r"^لماذا\s+تختار", r"^من\s+عروضنا", r"^ابدأ\s+رحلتك", r"^ابدا\s+رحلتك"]

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
    "calcium": "Calcium",
    "phosphorus": "Phosphorus",
}
DISEASE_TOKEN_BLOCKLIST = {"pcos", "scurvy", "bph"}
TAG_STOPWORDS = {"مختبرات", "وريد", "الطبية", "دقة", "وموثوقية", "تحليل", "فحص"}

POST_REPAIRS = [
    (r"\bالأطع\b", "الأطعمة"),
    (r"\bالمه\b", "المهم"),
    (r"\bالع[ـ\s]ا\b", "العامة"),
    (r"\bمتقد\b", "متقدمة"),
    (r"\bمقاو\b", "مقاومة"),
    (r"\bقي\s+عددية\b", "قيمة عددية"),
]
ARTIFACT_PATTERN = re.compile(r"(?:\bلم\s*ة\b|\bم\s*ة\b|\bمـ\s*ة\b)")
ARTIFACT_CONTEXT = ("علاج", "مرضى", "حالات", "استجابة", "فعالية", "مراقبة")

DEF_WORDS = ("تحليل", "فحص", "اختبار", "يقيس")
USES_WORDS = ("يطلب", "يستخدم", "تشخيص", "متابعة", "تقييم", "دواعي")
PREP_WORDS = ("صيام", "قبل الفحص", "قبل التحليل", "الأدوية", "اليوم", "التحضير")
NOTE_WORDS = ("ملاحظة", "تنبيه", "هام", "مهم")


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = (
        text.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ة", "ه")
    )
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _stable_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _normalize_punct(text: str) -> str:
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("•", "\n- ").replace("–", "\n- ").replace("—", "\n- ")
    t = re.sub(r"^\s*-\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*([،,.;:!?؟])\s*", r"\1 ", t)
    t = re.sub(r"\n{2,}", "\n", t)
    t = re.sub(r"\s+", " ", t)
    t = t.replace(" \n", "\n").replace("\n ", "\n")
    return t.strip(" \n-،,;:.")


def _strip_banned_global(text: str) -> str:
    out = str(text or "")
    out = re.sub(r"[\u0640\u064B-\u065F\u0670]", "", out)
    out = re.sub(r"(?:\+?\d[\d\-\s]{6,}\d)", " ", out)
    for pat in BANNED_PATTERNS:
        out = re.sub(pat, " ", out, flags=re.IGNORECASE)
    for literal in [
        "باقة التحاليل",
        "باقة تحاليل",
        "من قبل لتاكيد الحجز",
        "من قبل لتأكيد الحجز",
        "لتاكيد الحجز",
        "التحاليل الشاملة",
        "من من قبل",
        "على صحة قلبك مع",
    ]:
        out = out.replace(literal, " ")
    return _normalize_punct(out)


def _remove_repeated_phrases(text: str) -> str:
    tokens = str(text or "").split()
    if len(tokens) < 10:
        return str(text or "")
    changed = True
    while changed:
        changed = False
        for n in range(12, 3, -1):
            i = 0
            while i + (2 * n) <= len(tokens):
                if tokens[i : i + n] == tokens[i + n : i + (2 * n)]:
                    del tokens[i + n : i + (2 * n)]
                    changed = True
                else:
                    i += 1
    return " ".join(tokens)


def _repair_artifacts(text: str) -> str:
    out = text
    while True:
        m = ARTIFACT_PATTERN.search(out)
        if not m:
            break
        window = normalize_text(out[max(0, m.start() - 30) : min(len(out), m.end() + 30)])
        repl = "متابعة" if any(k in window for k in ARTIFACT_CONTEXT) else " "
        out = out[: m.start()] + repl + out[m.end() :]
    return out


def _post_clean_repair(text: str) -> str:
    out = str(text or "")
    for bad_re, good in POST_REPAIRS:
        out = re.sub(bad_re, good, out)
    # Fix common over-repair artifacts.
    out = out.replace("الأطعمةمة", "الأطعمة")
    out = out.replace("متقدمةم", "متقدمة")
    out = re.sub(r"\b[اأإآبتثجحخدذرزسشصضطظعغفقكلمنهوي]{1,2}\b(?=\s*[،.;:\n]|$)", " ", out)
    out = re.sub(r"\s+([،,.;:!?؟])", r"\1", out)
    out = re.sub(r"([،,.;:!?؟]){2,}", r"\1", out)
    return _normalize_punct(out)


def _split_sentences(text: str) -> list[str]:
    normalized = _normalize_punct(text)
    parts = re.split(r"(?<=[.!؟\n])\s+|\n", normalized)
    return [s for s in (_normalize_punct(p) for p in parts) if s]


def _dedupe_sentences(sentences: list[str]) -> list[str]:
    seen: list[str] = []
    out: list[str] = []
    for sentence in sentences:
        fp = normalize_text(sentence)
        if not fp:
            continue
        if any(fp == x or (len(fp) > 24 and (fp in x or x in fp)) for x in seen):
            continue
        if any(SequenceMatcher(None, fp, x).ratio() >= 0.92 for x in seen):
            continue
        seen.append(fp)
        out.append(sentence)
    return out


def _clean_content(raw: str) -> str:
    t = _normalize_punct(raw)
    t = _strip_banned_global(t)
    t = _repair_artifacts(t)
    base = []
    for s in _split_sentences(t):
        n = normalize_text(s)
        if not n:
            continue
        if any(re.search(p, n) for p in GENERIC_HEADINGS):
            continue
        base.append(s)
    deduped = _dedupe_sentences(base)
    defs = [s for s in deduped if any(k in normalize_text(s) for k in DEF_WORDS)][:2]
    uses = [s for s in deduped if any(k in normalize_text(s) for k in USES_WORDS)][:4]
    prep = [s for s in deduped if any(k in normalize_text(s) for k in PREP_WORDS)][:2]
    notes = [s for s in deduped if any(k in normalize_text(s) for k in NOTE_WORDS)][:1]
    selected = _dedupe_sentences(defs + uses + prep + notes) or deduped[:5]
    lines: list[str] = []
    seen: set[str] = set()
    for idx, line in enumerate(selected):
        clean = _normalize_punct(line)
        key = normalize_text(clean)
        if not key or key in seen:
            continue
        seen.add(key)
        lines.append(clean if idx < 2 else f"- {clean}")
    text = _normalize_punct("\n".join(lines))
    text = _post_clean_repair(text)
    text = _strip_banned_global(text)
    text = _remove_repeated_phrases(text)
    if len(text) > 900:
        text = _normalize_punct(text[:900].rstrip())
    return text if len(text) >= 120 else ""


def _summary(text: str) -> str:
    sents = [s.strip(" -") for s in _split_sentences(text) if s.strip(" -")]
    if not sents:
        return ""
    s = sents[0]
    if len(s) < 220 and len(sents) > 1:
        joined = f"{s} {sents[1]}"
        if len(joined) <= 280:
            s = joined
    return _strip_banned_global(s)[:280]


def _page_type(existing: str, title: str, h1: str, content: str) -> str:
    joined = normalize_text(f"{title} {h1} {content}")
    if any(w in joined for w in ("تحليل", "فحص", "اختبار")):
        return "test_page"
    return "general_page" if not existing else existing


def _extract_codes(url: str, title: str, h1: str, content: str) -> list[str]:
    candidates: list[str] = []
    slug_tokens = [w for w in re.split(r"[-_/]", urlparse(url).path.strip("/").lower()) if w]
    slug_text = " ".join(slug_tokens)
    if "hemoglobin" in slug_text and "a1c" in slug_text:
        candidates.append("HbA1c")
    if "free" in slug_text and "psa" in slug_text:
        candidates.append("Free PSA")
    for w in slug_tokens:
        key = re.sub(r"[^a-z0-9]", "", w)
        if key in LAB_TOKEN_CANONICAL:
            candidates.append(LAB_TOKEN_CANONICAL[key])

    for src in [title, h1]:
        for m in re.finditer(r"\(([A-Za-z][A-Za-z0-9\-\s]{1,24})\)", src or ""):
            candidates.append(m.group(1).strip())
        candidates.extend(re.findall(r"\b[A-Z][A-Z0-9\-]{1,10}\b", src or ""))

    for line in _split_sentences(content):
        if not re.search(r"(?:رمز|code|اختصار|\()", line, flags=re.IGNORECASE):
            continue
        for m in re.finditer(r"\(([A-Za-z][A-Za-z0-9\-\s]{1,24})\)", line):
            candidates.append(m.group(1).strip())
        candidates.extend(re.findall(r"\b[A-Z][A-Z0-9\-]{1,10}\b", line))

    out: list[str] = []
    seen: set[str] = set()
    for token in candidates:
        key = re.sub(r"[^a-z0-9]", "", token.lower())
        if key in DISEASE_TOKEN_BLOCKLIST:
            continue
        canon = LAB_TOKEN_CANONICAL.get(key)
        if not canon or canon.lower() in seen:
            continue
        seen.add(canon.lower())
        out.append(canon)
        if len(out) >= 8:
            break
    return out


def _extract_disease_tags(text: str) -> list[str]:
    out: list[str] = []
    for token in re.findall(r"\b[A-Z][A-Z0-9\-]{1,10}\b", text or ""):
        key = re.sub(r"[^a-z0-9]", "", token.lower())
        if key in DISEASE_TOKEN_BLOCKLIST:
            normalized = token.upper()
            if normalized not in out:
                out.append(normalized)
    return out


def _tags(test_name: str, codes: list[str], disease_tags: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in codes + disease_tags:
        clean = _strip_banned_global(t)
        key = normalize_text(clean)
        if key and key not in seen:
            seen.add(key)
            out.append(clean)
    for word in re.findall(r"[A-Za-z0-9\u0600-\u06FF]+", test_name):
        clean = _strip_banned_global(word)
        key = normalize_text(clean)
        if not key or key in TAG_STOPWORDS or key in seen:
            continue
        seen.add(key)
        out.append(clean)
        if len(out) >= 10:
            break
    return [x for x in out if x][:10]


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
        lang = str(row.get("lang", "") or "").strip().lower()
        if lang != "ar":
            dropped += 1
            continue
        url = str(row.get("url", "") or "").strip()
        raw_content = str(row.get("content", "") or "").strip()
        if not url or not raw_content:
            dropped += 1
            continue

        raw_title = str(row.get("title", "") or "")
        raw_h1 = str(row.get("h1", "") or "")

        title = _strip_banned_global(raw_title)
        h1 = _strip_banned_global(raw_h1)
        content_clean = _clean_content(raw_content)
        if not content_clean:
            dropped += 1
            continue

        test_name = _normalize_punct(re.sub(r"^\s*(?:تحليل|فحص|اختبار)\s+", "", (h1 or title or "").strip()))
        test_name = _strip_banned_global(test_name)
        codes = _extract_codes(url, raw_title, raw_h1, raw_content)
        disease_tags = _extract_disease_tags(f"{raw_title} {raw_h1} {raw_content}")
        page_type = _page_type(str(row.get("page_type", "") or "").strip(), title, h1, content_clean)
        if page_type != "test_page":
            dropped += 1
            continue
        doc_id = _stable_id(url)
        summary = _summary(content_clean)
        tags = _tags(test_name, codes, disease_tags)

        docs.append(
            {
                "id": doc_id,
                "source_type": "website",
                "url": url,
                "lang": "ar",
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
    parser.add_argument(
        "--chunks-out", dest="chunks_out", type=Path, default=SOURCES_WEB_DIR / "site_knowledge_chunks_hard.jsonl"
    )
    args = parser.parse_args()
    s = clean_site_knowledge_jsonl(args.input_path, args.clean_out, args.chunks_out)
    print(f"input_rows={s['input_rows']}, kept_docs={s['kept_docs']}, dropped_docs={s['dropped_docs']}, chunk_rows={s['chunk_rows']}")


if __name__ == "__main__":
    main()
