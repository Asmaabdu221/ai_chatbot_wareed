"""
PDF Lab Report Parser + KB-grounded summary composer.
No clinical diagnosis; educational explanation only.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

RESULT_KEYWORDS = [
    "النتيجة", "result", "value", "reference", "range", "ref", "unit", "الوحدة", "المدى المرجعي",
]
EXPLAIN_RESULT_KEYWORDS = [
    "اشرح التحاليل", "فسر النتائج", "حلل النتيجة", "وش معنى النتيجة", "شرح النتائج", "تفسير النتيجة",
]

SYNONYMS = {
    "cea": "Carcinoembryonic Antigen",
    "carcinoembryonic antigen": "Carcinoembryonic Antigen",
    "مستضد السرطان الجنيني": "Carcinoembryonic Antigen",
    "hba1c": "HbA1c",
    "السكر التراكمي": "HbA1c",
    "tsh": "TSH",
    "cbc": "CBC",
}


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub("[^\\u0600-\\u06FFa-zA-Z0-9\\s]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def is_report_explanation_request(user_text: str) -> bool:
    q = _norm(user_text or "")
    if not q:
        return False
    return any(_norm(k) in q for k in EXPLAIN_RESULT_KEYWORDS)


def _clean_text(text: str) -> str:
    t = (text or "").replace("\r", "\n")
    t = t.replace("\t", "    ")
    return t


def _normalize_test_name(name: str) -> str:
    n = _norm(name or "")
    if n in SYNONYMS:
        return SYNONYMS[n]
    return (name or "").strip()


def _parse_pipe_row(line: str) -> Optional[Dict[str, str]]:
    parts = [p.strip() for p in line.split("|") if p.strip()]
    if len(parts) < 2:
        return None
    if any(_norm(h) in _norm(parts[0]) for h in ("test", "الفحص", "analysis")):
        return None
    row = {
        "test_name": parts[0],
        "result_value": parts[1] if len(parts) > 1 else "",
        "unit": parts[2] if len(parts) > 2 else "",
        "reference_range": parts[3] if len(parts) > 3 else "",
        "flags_if_present": "",
    }
    return row if row["test_name"] and row["result_value"] else None


def _parse_spaced_row(line: str) -> Optional[Dict[str, str]]:
    # Example:
    # Vitamin D   18.2   ng/mL   30-100   L
    cols = [c.strip() for c in re.split(r"\s{2,}", line.strip()) if c.strip()]
    if len(cols) < 3:
        return None
    name = cols[0]
    value = cols[1]
    unit = cols[2] if len(cols) > 2 else ""
    reference = cols[3] if len(cols) > 3 else ""
    flag = cols[4] if len(cols) > 4 else ""
    if len(name) < 2:
        return None
    if not re.search(r"[0-9]", value):
        return None
    if flag and flag not in {"H", "L"}:
        flag = ""
    return {
        "test_name": name,
        "result_value": value,
        "unit": unit,
        "reference_range": reference,
        "flags_if_present": flag,
    }


def parse_lab_report_text(extracted_text: str) -> List[Dict[str, str]]:
    text = _clean_text(extracted_text)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    parsed: List[Dict[str, str]] = []

    for line in lines:
        norm = _norm(line)
        if len(line) < 4:
            continue
        if any(k in norm for k in [_norm(x) for x in RESULT_KEYWORDS]) and ("|" not in line):
            continue

        row = _parse_pipe_row(line) or _parse_spaced_row(line)
        if not row:
            continue
        row["test_name"] = _normalize_test_name(row["test_name"])
        parsed.append(row)

    dedup: Dict[str, Dict[str, str]] = {}
    for item in parsed:
        key = _norm(item["test_name"])
        if key and key not in dedup:
            dedup[key] = item
    return list(dedup.values())


def _lookup_test_context(test_name: str) -> Optional[Dict[str, Any]]:
    try:
        from app.data.knowledge_loader_v2 import get_knowledge_base

        kb = get_knowledge_base()
        hits = kb.search_tests(test_name, min_score=55, max_results=1)
        if hits:
            return hits[0].get("test")
    except Exception:
        pass
    try:
        from app.data.rag_pipeline import retrieve

        rag_hits, _ = retrieve(test_name, max_results=1, similarity_threshold=0.45)
        if rag_hits:
            return rag_hits[0].get("test")
    except Exception:
        return None
    return None


def compose_report_summary(parsed_rows: List[Dict[str, str]]) -> str:
    if not parsed_rows:
        return (
            "ما قدرت أطلع نتائج التحاليل بشكل واضح من الملف. "
            "جرب/ي ملف PDF أوضح، أو تواصل/ي معنا على 800-122-1220."
        )

    lines: List[str] = []
    for row in parsed_rows[:12]:
        test_name = row.get("test_name") or "فحص غير واضح"
        kb_test = _lookup_test_context(test_name)
        lines.append(f"اسم الفحص: {test_name}")
        lines.append(
            f"النتيجة: {(row.get('result_value') or 'غير واضحة')} {(row.get('unit') or '').strip()}".strip()
        )
        ref = row.get("reference_range") or "غير مذكور"
        lines.append(f"المدى المرجعي: {ref}")
        flag = row.get("flags_if_present")
        if flag:
            lines.append(f"ملاحظة التقرير: {flag}")
        if kb_test:
            name_ar = kb_test.get("analysis_name_ar") or test_name
            name_en = kb_test.get("analysis_name_en") or ""
            desc = (kb_test.get("description") or "").strip()
            reason = (kb_test.get("symptoms") or "").strip()
            lines.append(
                "معنى الفحص: "
                + f"{name_ar}"
                + (f" ({name_en})" if name_en else "")
                + (f" - {desc}" if desc else "")
                + (f" السبب الشائع لطلبه: {reason}" if reason else "")
            )
        else:
            lines.append("معنى الفحص: ما لقيت وصف مفصل لهذا الفحص بقاعدة المعرفة عندي.")
        lines.append("")

    lines.append("هذا شرح تثقيفي فقط، والتقييم الطبي النهائي يكون مع الطبيب المعالج.")
    lines.append("إذا تحتاج/ين تفاصيل أكثر، تواصل/ي معنا على 800-122-1220.")
    return "\n".join(lines).strip()
