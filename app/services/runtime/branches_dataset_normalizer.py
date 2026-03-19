"""Normalize branches dataset into an additive stable schema (non-destructive)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic

INPUT_PATH = Path("app/data/runtime/rag/branches_clean.jsonl")
OUTPUT_PATH = Path("app/data/runtime/rag/branches_clean.normalized.jsonl")

_CITY_ALIASES = {
    "الرياض": "الرياض",
    "جده": "جدة",
    "جدة": "جدة",
    "الشرقيه": "الشرقية",
    "الشرقية": "الشرقية",
    "المدينه": "المدينة",
    "المدينة": "المدينة",
    "مكه": "مكة",
    "مكه المكرمه": "مكة المكرمة",
    "مكة": "مكة",
    "مكة المكرمة": "مكة المكرمة",
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _extract_city_from_section(section: str) -> str:
    section_clean = _safe_str(section)
    section_norm = normalize_arabic(section_clean)
    if not section_norm:
        return ""

    # Common shape: "فروع منطقة <city>"
    match = re.search(r"فروع\s+منطقه\s+(.+)$", section_norm)
    if match:
        candidate = _safe_str(match.group(1))
    else:
        tokens = [t for t in section_norm.split() if t and t not in {"فروع", "منطقه", "منطقة"}]
        candidate = _safe_str(tokens[-1] if tokens else "")

    return normalize_city_name(candidate)


def normalize_city_name(city: str) -> str:
    """Normalize city label into a stable Arabic value when possible."""
    value = _safe_str(city)
    if not value:
        return ""

    norm = normalize_arabic(value)
    return _CITY_ALIASES.get(norm, value)


def _strip_branch_prefix(name_norm: str) -> str:
    value = _safe_str(name_norm)
    for prefix in ("الفرع الرئيسي", "الفرع الرييسي", "فرع", "الفرع"):
        if value.startswith(prefix):
            value = _safe_str(value[len(prefix) :])
    return value.lstrip("- ").strip()


def infer_district(branch_name: str, city: str = "") -> str:
    """Infer district conservatively from branch name when safe; otherwise empty."""
    name_norm = normalize_arabic(_safe_str(branch_name))
    if not name_norm:
        return ""

    district = _strip_branch_prefix(name_norm)
    city_norm = normalize_arabic(_safe_str(city))
    if city_norm and district.endswith(city_norm):
        district = _safe_str(district[: -len(city_norm)]).rstrip("- ")

    if len(district) < 2:
        return ""

    return district


def slugify_arabic_id_part(text: str) -> str:
    """Build deterministic ASCII-safe slug part from normalized Arabic text."""
    normalized = normalize_arabic(text)
    if not normalized:
        return "unknown"

    # Keep ascii letters/digits if present, else convert spaces into underscores.
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^a-z0-9_\u0600-\u06FF]", "", normalized)
    normalized = normalized.replace(" ", "_")
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "unknown"


def build_stable_branch_id(branch_name: str, city: str) -> str:
    """Create deterministic stable branch id."""
    city_part = slugify_arabic_id_part(city)
    branch_part = slugify_arabic_id_part(branch_name)
    return f"branch::{city_part}_{branch_part}"


def normalize_branch_record(row: dict[str, Any]) -> dict[str, Any]:
    """Return additive normalized branch record while preserving existing fields."""
    item = dict(row)

    branch_name = _safe_str(item.get("branch_name"))
    section = _safe_str(item.get("section"))
    city = normalize_city_name(_safe_str(item.get("city")) or _extract_city_from_section(section))
    district = _safe_str(item.get("district")) or infer_district(branch_name, city)

    maps_url = _safe_str(item.get("maps_url")) or _safe_str(item.get("map_url"))

    item["source"] = _safe_str(item.get("source")) or "branches"
    item["branch_name"] = branch_name
    item["city"] = city
    item["district"] = district
    item["hours"] = _safe_str(item.get("hours"))
    item["maps_url"] = maps_url
    # Backward compatibility: keep old field exactly as-is for current resolver behavior.
    if "map_url" not in item:
        item["map_url"] = maps_url

    item["latitude"] = item.get("latitude") if item.get("latitude") not in ("", " ") else None
    item["longitude"] = item.get("longitude") if item.get("longitude") not in ("", " ") else None

    if "is_active" not in item:
        item["is_active"] = True

    item["id"] = _safe_str(item.get("id")) or build_stable_branch_id(branch_name, city)

    return item


def normalize_branches_dataset(
    input_path: Path = INPUT_PATH,
    output_path: Path = OUTPUT_PATH,
) -> dict[str, int]:
    """Normalize branches dataset and write additive JSONL output."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    total = 0
    written = 0
    skipped = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8") as src, output_path.open("w", encoding="utf-8") as dst:
        for raw_line in src:
            line = _safe_str(raw_line)
            if not line:
                continue
            total += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(row, dict):
                skipped += 1
                continue

            normalized = normalize_branch_record(row)
            dst.write(json.dumps(normalized, ensure_ascii=False) + "\n")
            written += 1

    return {"total": total, "written": written, "skipped": skipped}


if __name__ == "__main__":
    stats = normalize_branches_dataset()
    print(f"Input : {INPUT_PATH.as_posix()}")
    print(f"Output: {OUTPUT_PATH.as_posix()}")
    print(f"Stats : total={stats['total']} written={stats['written']} skipped={stats['skipped']}")
