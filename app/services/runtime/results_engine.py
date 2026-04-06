"""Deterministic and safe result-interpretation engine."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic

RESULTS_JSONL_PATH = Path("app/data/runtime/rag/results_clean.jsonl")
_CONSULT_TEXT = "يرجى استشارة الطبيب، ولمزيد من المعلومات تواصل معنا."
_NEED_MORE_INFO = "أرسل صورة التحليل أو اكتب اسم التحليل مع النتيجة والمرجع الأدنى والأعلى."
_GENERIC_WORDS = ("نتيجتي", "نتيجة", "النتيجة", "تحليل", "فحص", "test", "result")
_ALIAS_NOISE_HINTS = ("باقة", "باقه", "package", "offer", "عرض")
_GENERIC_WORDS_NORM = {normalize_arabic(w) for w in _GENERIC_WORDS}
_QUALITATIVE_TOKENS = {
    "negative": "negative",
    "non reactive": "non_reactive",
    "non-reactive": "non_reactive",
    "reactive": "reactive",
    "positive": "positive",
    "nil": "negative",
    "normal": "normal",
    "abnormal": "abnormal",
    "سلبي": "negative",
    "غير تفاعلي": "non_reactive",
    "تفاعلي": "reactive",
    "ايجابي": "positive",
    "إيجابي": "positive",
    "طبيعي": "normal",
    "غير طبيعي": "abnormal",
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return normalize_arabic(_safe_str(value))


def _to_float(value: Any) -> float | None:
    text = _safe_str(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _extract_numeric_value(query: str) -> float | None:
    value = _safe_str(query).translate(
        str.maketrans(
            {
                "٠": "0",
                "١": "1",
                "٢": "2",
                "٣": "3",
                "٤": "4",
                "٥": "5",
                "٦": "6",
                "٧": "7",
                "٨": "8",
                "٩": "9",
                "٫": ".",
                ",": ".",
            }
        )
    )
    matches = re.findall(r"[-+]?\d+(?:\.\d+)?", value)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def _strip_numbers(text: str) -> str:
    value = _safe_str(text).translate(
        str.maketrans(
            {
                "٠": "0",
                "١": "1",
                "٢": "2",
                "٣": "3",
                "٤": "4",
                "٥": "5",
                "٦": "6",
                "٧": "7",
                "٨": "8",
                "٩": "9",
                "٫": ".",
                ",": ".",
            }
        )
    )
    # Remove standalone numeric result values only; keep code digits inside names (e.g. HbA1c).
    return re.sub(r"(?<![A-Za-z\u0621-\u063A\u0641-\u064A])[-+]?\d+(?:\.\d+)?(?![A-Za-z\u0621-\u063A\u0641-\u064A])", " ", value)


def _clean_query_for_name_match(query: str) -> str:
    n = _norm(_strip_numbers(query))
    if not n:
        return ""
    tokens = [t for t in n.split() if t and t not in _GENERIC_WORDS_NORM]
    return " ".join(tokens).strip()


def _compact_code(text: str) -> str:
    """Compact alnum code-like tokens to handle forms like 'Hb A1c' vs 'HbA1c'."""
    n = _norm(text)
    if not n:
        return ""
    return re.sub(r"[^a-z0-9\u0621-\u063A\u0641-\u064A]", "", n)


def _has_clear_structured_rules(rules: list[Any]) -> bool:
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        op = _safe_str(rule.get("operator"))
        val = _to_float(rule.get("value"))
        min_v = _to_float(rule.get("min"))
        max_v = _to_float(rule.get("max"))
        if op and val is not None:
            return True
        if min_v is not None or max_v is not None:
            return True
    return False


def _is_safe_record(record: dict[str, Any]) -> bool:
    level = _norm(record.get("ai_ready_level"))
    if level == "high":
        return True
    if level != "medium":
        return False

    min_v = _to_float(record.get("min_value"))
    max_v = _to_float(record.get("max_value"))
    has_numeric_range = min_v is not None or max_v is not None
    has_structured_rules = _has_clear_structured_rules(_as_list(record.get("structured_rules"))) or _has_clear_structured_rules(
        _as_list(record.get("rules"))
    )
    return has_numeric_range or has_structured_rules


def _normalize_terms(record: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    name = _safe_str(record.get("test_name"))
    if name:
        terms.append(_norm(name))
    for alias in _as_list(record.get("aliases")):
        alias_raw = _safe_str(alias)
        alias_norm_raw = _norm(alias_raw)
        # Keep deterministic matching focused on test naming; skip package/offer aliases.
        if any(h in alias_norm_raw for h in _ALIAS_NOISE_HINTS):
            continue
        a = _norm(alias)
        if a:
            terms.append(a)
    out: list[str] = []
    seen: set[str] = set()
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


@lru_cache(maxsize=1)
def load_results_records() -> list[dict[str, Any]]:
    if not RESULTS_JSONL_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    with RESULTS_JSONL_PATH.open("r", encoding="utf-8") as f:
        for raw in f:
            line = _safe_str(raw)
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if not _safe_str(obj.get("test_name")):
                continue
            item = dict(obj)
            item["terms_norm"] = _normalize_terms(item)
            item["safe_interpretation"] = _is_safe_record(item)
            rows.append(item)
    return rows


def _match_record(query: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    query_name = _clean_query_for_name_match(query)
    if not query_name:
        return None
    query_compact = _compact_code(query_name)

    best: dict[str, Any] | None = None
    best_score = 0.0

    for record in records:
        for term in _as_list(record.get("terms_norm")):
            score = 0.0
            if query_name == term:
                score = 1.0
            elif query_compact and query_compact == _compact_code(term):
                score = 0.99
            elif term and term in query_name:
                score = 0.95
            elif query_name and query_name in term:
                score = 0.85
            if score > best_score:
                best = record
                best_score = score

    if best is None or best_score < 0.85:
        return None
    return best


def _classify_by_range(value: float, min_v: float | None, max_v: float | None) -> str | None:
    if min_v is not None and value < min_v:
        return "أقل من المستوى الطبيعي"
    if max_v is not None and value > max_v:
        return "فوق المستوى الطبيعي"
    if min_v is not None or max_v is not None:
        return "ضمن الطبيعي"
    return None


def _classify_by_rules(value: float, rules: list[Any]) -> str | None:
    # Prefer explicit normal range rules.
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        min_v = _to_float(rule.get("min"))
        max_v = _to_float(rule.get("max"))
        status = _norm(rule.get("status"))
        if status == "normal" and (min_v is not None or max_v is not None):
            return _classify_by_range(value, min_v, max_v)

    # Fallback to threshold-style normal rules.
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        status = _norm(rule.get("status"))
        op = _safe_str(rule.get("operator"))
        threshold = _to_float(rule.get("value"))
        if status != "normal" or not op or threshold is None:
            continue

        if op == "<=":
            return "ضمن الطبيعي" if value <= threshold else "فوق المستوى الطبيعي"
        if op == "<":
            return "ضمن الطبيعي" if value < threshold else "فوق المستوى الطبيعي"
        if op == ">=":
            return "ضمن الطبيعي" if value >= threshold else "أقل من المستوى الطبيعي"
        if op == ">":
            return "ضمن الطبيعي" if value > threshold else "أقل من المستوى الطبيعي"
        if op in {"=", "=="}:
            return "ضمن الطبيعي" if value == threshold else ("فوق المستوى الطبيعي" if value > threshold else "أقل من المستوى الطبيعي")

    return None


def _rule_matches_value(value: float, rule: dict[str, Any]) -> bool:
    op = _safe_str(rule.get("operator"))
    min_v = _to_float(rule.get("min"))
    max_v = _to_float(rule.get("max"))
    threshold = _to_float(rule.get("value"))

    if min_v is not None or max_v is not None:
        if min_v is not None and value < min_v:
            return False
        if max_v is not None and value > max_v:
            return False
        return True

    if threshold is None or not op:
        return False
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    if op in {"=", "=="}:
        return value == threshold
    return False


def _map_rule_to_verdict(rule: dict[str, Any]) -> str | None:
    status = _norm(rule.get("status"))
    label = _norm(rule.get("label"))
    text = f"{status} {label}".strip()

    if "below_normal" in text or "deficien" in text or "insuff" in text or "sever" in text:
        return "أقل من المستوى الطبيعي"
    if "normal" in text or "sufficient" in text:
        return "ضمن الطبيعي"
    if (
        "above_normal" in text
        or "high" in text
        or "overdose" in text
        or "prediabetes" in text
        or "prediabetic" in text
        or "diabetic" in text
    ):
        return "فوق المستوى الطبيعي"
    return None


def _classify_multi_band(value: float, rules: list[Any]) -> str | None:
    for raw_rule in rules:
        if not isinstance(raw_rule, dict):
            continue
        if not _rule_matches_value(value, raw_rule):
            continue
        verdict = _map_rule_to_verdict(raw_rule)
        if verdict:
            return verdict
    return None


def _extract_text_result_value(query: str) -> str | None:
    q = _norm(query)
    if not q:
        return None
    found = ""
    found_len = 0
    for raw_token, canonical in _QUALITATIVE_TOKENS.items():
        token = _norm(raw_token)
        if token and token in q and len(token) > found_len:
            found = canonical
            found_len = len(token)
    return found or None


def _map_qualitative_to_verdict(token: str) -> str | None:
    t = _norm(token)
    if t in {"negative", "non_reactive", "normal"}:
        return "ضمن الطبيعي"
    if t in {"positive", "reactive", "abnormal"}:
        return "فوق المستوى الطبيعي"
    return None


def _classify_qualitative(record: dict[str, Any], query: str) -> str | None:
    user_value = _extract_text_result_value(query)
    if not user_value:
        return None

    allowed = {_norm(v) for v in _as_list(record.get("qualitative_values")) if _norm(v)}
    for rule in _as_list(record.get("structured_rules")):
        if not isinstance(rule, dict):
            continue
        for key in ("label", "status"):
            val = _norm(rule.get(key))
            if val:
                allowed.add(val)
        for val in _as_list(rule.get("allowed_values")):
            norm_val = _norm(val)
            if norm_val:
                allowed.add(norm_val)

    user_norm = _norm(user_value)
    if allowed:
        match_found = any(user_norm == v or user_norm in v or v in user_norm for v in allowed)
        if not match_found:
            return None
    return _map_qualitative_to_verdict(user_norm)


def interpret_result_query(query: str) -> str:
    records = load_results_records()
    if not records:
        return _NEED_MORE_INFO

    record = _match_record(query, records)
    if not record:
        return _NEED_MORE_INFO
    if not bool(record.get("safe_interpretation")):
        return _NEED_MORE_INFO

    mode = _norm(record.get("interpretation_mode")) or "numeric range"
    structured_rules = _as_list(record.get("structured_rules"))
    if not structured_rules:
        structured_rules = _as_list(record.get("rules"))

    if mode == "qualitative":
        verdict = _classify_qualitative(record, query)
        if verdict is None:
            return _NEED_MORE_INFO
        return f"{verdict}\n{_CONSULT_TEXT}"

    value = _extract_numeric_value(query)
    if value is None:
        return _NEED_MORE_INFO

    min_v = _to_float(record.get("min_value"))
    max_v = _to_float(record.get("max_value"))

    verdict: str | None = None
    if mode in {"numeric_range", "numeric range"}:
        verdict = _classify_by_rules(value, structured_rules) if structured_rules else None
        if verdict is None:
            verdict = _classify_by_range(value, min_v, max_v)
    elif mode in {"multi_band", "multi band"}:
        verdict = _classify_multi_band(value, structured_rules)
        if verdict is None:
            verdict = _classify_by_range(value, min_v, max_v)
    elif mode == "threshold":
        verdict = _classify_by_rules(value, structured_rules)
    else:
        # Conservative fallback for unknown mode: only numeric-range comparison.
        verdict = _classify_by_range(value, min_v, max_v)

    if verdict is None:
        return _NEED_MORE_INFO
    return f"{verdict}\n{_CONSULT_TEXT}"
