"""Deterministic response formatting helpers for runtime answers."""

from __future__ import annotations

import ast
import re

_MULTISPACE_RE = re.compile(r"[ \t]+")
_MULTILINE_RE = re.compile(r"\n{3,}")
_PY_LIST_RE = re.compile(r"\[[^\[\]]+\]")

_TERM_TRANSLATIONS = {
    "Calcium": "الكالسيوم",
    "Phosphorus": "الفوسفور",
    "Parathyroid Hormone (PTH)": "هرمون جار الدرقية (PTH)",
    "PTH": "هرمون جار الدرقية (PTH)",
    "whole blood": "دم كامل",
    "serum": "مصل",
    "plasma": "بلازما",
    "urine": "بول",
    "stool": "براز",
    "swab": "مسحة",
}

_SAMPLE_PHRASE_REPLACEMENTS = {
    "R.Temp.": "درجة حرارة الغرفة",
    "Room temperature": "درجة حرارة الغرفة",
    "Collected": "يحفظ",
}


def _safe_str(value: object) -> str:
    return str(value or "").strip()


def _normalize_spacing(text: str) -> str:
    value = _safe_str(text)
    value = _MULTISPACE_RE.sub(" ", value)
    value = re.sub(r"[ ]+\n", "\n", value)
    value = _MULTILINE_RE.sub("\n\n", value)
    return value.strip()


def _translate_terms(text: str) -> str:
    value = text
    for src, dst in _TERM_TRANSLATIONS.items():
        value = re.sub(re.escape(src), dst, value, flags=re.IGNORECASE)
    for src, dst in _SAMPLE_PHRASE_REPLACEMENTS.items():
        value = value.replace(src, dst)
    return value


def _simplify_heading(line: str) -> str:
    value = _safe_str(line)
    # Remove very long technical parenthetical tails when heading is too long.
    if len(value) > 95 and "(" in value and ")" in value:
        value = re.sub(r"\s*\([^)]*\)", "", value).strip()
    return value


def _safe_parse_list_literal(chunk: str) -> list[str] | None:
    try:
        parsed = ast.literal_eval(chunk)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(parsed, list):
        return None
    out: list[str] = []
    for item in parsed:
        text = _safe_str(item)
        if text:
            out.append(text)
    return out or None


def _replace_python_lists(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        parsed = _safe_parse_list_literal(match.group(0))
        if not parsed:
            return match.group(0)
        return "\n".join(f"• {_translate_terms(item)}" for item in parsed)

    return _PY_LIST_RE.sub(repl, text)


def _normalize_bullets(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    for i, raw in enumerate(lines):
        line = _safe_str(raw)
        if line.startswith("- "):
            line = f"• {line[2:].strip()}"
        if i == 0:
            line = _simplify_heading(line)
        out.append(line)
    return "\n".join(out).strip()


def format_runtime_answer(answer: str) -> str:
    """Post-process runtime answer text without changing business logic."""
    value = _normalize_spacing(answer)
    if not value:
        return ""
    value = _translate_terms(value)
    value = _replace_python_lists(value)
    value = _normalize_bullets(value)
    value = _normalize_spacing(value)
    return value


if __name__ == "__main__":
    samples = [
        "التحاليل المكملة لـ فيتامين د:\n- ['Calcium', 'Parathyroid Hormone (PTH)', 'Phosphorus']",
        "نوع العينة لـ الفحص قبل الولادة غير الغازي:\n20 ml whole blood in two tubes cell free streck (SPECIAL TUBE) R.Temp.",
        "تحليل طويل جدًا (Long Technical Name With Extra Details) :\n- item one\n- item two",
    ]
    for sample in samples:
        print("BEFORE:")
        print(sample)
        print("AFTER:")
        print(format_runtime_answer(sample))
        print("-" * 72)
