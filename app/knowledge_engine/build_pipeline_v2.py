from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.paths import (
    EXCEL_ANALYSES_PATH,
    EXCEL_BRANCHES_PATH,
    EXCEL_FAQ_PATH,
    EXCEL_PACKAGES_PATH,
    EXCEL_PRAACISE_PATH,
    RUNTIME_DIR,
)
from app.knowledge_engine.excel_cleaner import clean_packages_excel
from app.knowledge_engine.embedding_stub import embed

NORMALIZE_VERSION = "v2-light-ar-en"

PACKAGE_ALIAS_BLOCKLIST = {
    "pcr",
    "vitamins",
    "urine",
    "std",
    "dna",
    "gold",
    "silver",
    "platinum",
    "test",
    "profile",
}

PACKAGE_SECTION_BLOCKLIST = {
    "تفاصيل التحليل",
    "الهدف",
    "طريقة التحليل",
    "المجالات التي يغطيها",
    "اللياقة البدنية",
    "الصحة العامة",
    "التغذية",
    "البشرة",
    "النتائج والتوصيات",
    "السعر والمدة",
    "الخلاصة",
    "المزيد من التفاصيل",
    "أهمية",
}


@dataclass(frozen=True)
class BuildConfig:
    analyses_path: Path = EXCEL_ANALYSES_PATH
    praacise_path: Path = EXCEL_PRAACISE_PATH
    packages_path: Path = EXCEL_PACKAGES_PATH
    faq_path: Path = EXCEL_FAQ_PATH
    branches_path: Path = EXCEL_BRANCHES_PATH
    runtime_dir: Path = RUNTIME_DIR


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


PACKAGE_SECTION_BLOCKLIST_NORM = {normalize_text(x) for x in PACKAGE_SECTION_BLOCKLIST}


def _stable_id(prefix: str, key: str) -> str:
    return f"{prefix}_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}"


def _pick_column(df: pd.DataFrame, candidates: list[str], fallback_index: int = 0) -> str | None:
    cols = list(df.columns)
    norm_cols = {normalize_text(c): c for c in cols}
    for cand in candidates:
        c = norm_cols.get(normalize_text(cand))
        if c:
            return c
    for col in cols:
        c_norm = normalize_text(col)
        if any(normalize_text(cand) in c_norm for cand in candidates):
            return col
    if cols and 0 <= fallback_index < len(cols):
        return cols[fallback_index]
    return None


def _parse_price(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _extract_price_from_text(text: str) -> float | None:
    value = str(text or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    patterns = [
        r"السعر\s*[:：]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*ريال",
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*ريال",
    ]
    for pattern in patterns:
        m = re.search(pattern, value)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _load_praacise_master(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    df = pd.read_excel(path)
    col_ar = _pick_column(df, ["arabic name", "analysis_name_ar", "اسم التحليل بالعربية", "اسم التحليل"], 0)
    col_en = _pick_column(df, ["english name", "analysis_name_en", "english_name", "اسم التحليل بالانجليزية"], 1)
    col_price = _pick_column(df, ["price", "السعر", "fee"], 2)
    master: dict[str, dict[str, Any]] = {}
    norm_to_display: dict[str, str] = {}
    for _, row in df.iterrows():
        name_ar = str(row[col_ar]).strip() if col_ar and pd.notna(row[col_ar]) else ""
        name_en = str(row[col_en]).strip() if col_en and pd.notna(row[col_en]) else ""
        price = _parse_price(row[col_price]) if col_price else None
        pref = name_en or name_ar
        key = normalize_text(pref)
        if not key:
            continue
        rec = {"name_ar": name_ar, "name_en": name_en, "price": price}
        master[key] = rec
        for alias in [name_ar, name_en]:
            n = normalize_text(alias)
            if n:
                master[n] = rec
        norm_to_display[key] = name_ar or name_en
    return master, norm_to_display


def build_tests_kb(config: BuildConfig, pra_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    df = pd.read_excel(config.analyses_path)
    col_ar = _pick_column(df, ["analysis_name_ar", "اسم التحليل بالعربية", "اسم التحليل"], 0)
    col_en = _pick_column(df, ["analysis_name_en", "english_name", "unnamed 0", "name_en"], 1)
    col_price = _pick_column(df, ["price", "السعر"])
    preserve_cols = [c for c in df.columns if c not in {col_ar, col_en, col_price}]
    docs: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        name_ar = str(row[col_ar]).strip() if col_ar and pd.notna(row[col_ar]) else ""
        name_en = str(row[col_en]).strip() if col_en and pd.notna(row[col_en]) else ""
        key = normalize_text(name_en or name_ar)
        if not key:
            continue
        pra = pra_map.get(key, {})
        merged = {
            "id": _stable_id("test", key),
            "canonical_key": key,
            "name_ar_final": pra.get("name_ar") or name_ar,
            "name_en_final": pra.get("name_en") or name_en,
            "price_final": pra.get("price") if pra.get("price") is not None else _parse_price(row[col_price]) if col_price else None,
        }
        for col in preserve_cols:
            value = row[col]
            merged[str(col)] = None if pd.isna(value) else value
        docs.append(merged)
    docs.sort(key=lambda x: x["id"])
    return docs


def _short_description(text: str) -> str:
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    if lines:
        if len(lines) == 1:
            return lines[0]
        return " ".join(lines[:2])
    parts = [p.strip() for p in re.split(r"(?<=[.!؟])\s+", str(text or "")) if p.strip()]
    return " ".join(parts[:2])


def _clean_package_test_candidate(raw_line: str) -> str:
    line = raw_line.strip()
    line = re.sub(r"^\s*[-–•*]+\s*", "", line)
    line = re.sub(r":\s*$", "", line).strip()
    line = re.sub(r"^\s*(?:اختبار|تحليل)\s+", "", line).strip()
    return line


def _is_section_heading(line: str) -> bool:
    norm = normalize_text(_clean_package_test_candidate(line))
    if not norm:
        return True
    if norm in PACKAGE_SECTION_BLOCKLIST_NORM:
        return True
    return any(h in norm for h in PACKAGE_SECTION_BLOCKLIST_NORM)


def _extract_test_names_strict(text: str) -> list[str]:
    reject_patterns = ("يكشف", "يقيس", "يستخدم", "يساعد", "يتم جمع", "يعكس")
    out: list[str] = []
    seen: set[str] = set()
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _is_section_heading(line):
            continue

        starts_test_word = line.startswith("اختبار") or line.startswith("تحليل")
        starts_bullet = bool(re.match(r"^\s*[-–•]", line))
        has_short_paren = bool(re.search(r"\(([A-Za-z0-9]{2,12})\)", line))
        short_colon_with_paren = line.endswith(":") and len(line) < 90 and has_short_paren

        is_candidate = False
        if starts_test_word:
            is_candidate = True
        elif starts_bullet and ("اختبار" in line or "تحليل" in line or has_short_paren or len(line) <= 80):
            is_candidate = True
        elif short_colon_with_paren:
            is_candidate = True

        if not is_candidate:
            continue

        cleaned = _clean_package_test_candidate(line)
        if not cleaned or len(cleaned) > 130:
            continue
        if any(v in cleaned for v in reject_patterns):
            continue

        norm = normalize_text(cleaned)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(cleaned)
    return out


def _prepare_tests_lookup(tests_kb: list[dict[str, Any]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for rec in tests_kb:
        test_id = str(rec.get("id", "") or "")
        names = [
            str(rec.get("name_ar_final", "") or ""),
            str(rec.get("name_en_final", "") or ""),
            str(rec.get("canonical_key", "") or ""),
        ]
        for nm in names:
            key = normalize_text(nm)
            if key:
                items.append({"key": key, "id": test_id, "name_ar": str(rec.get("name_ar_final", "") or ""), "name_en": str(rec.get("name_en_final", "") or "")})
    return items


def _match_test_to_kb(norm_test: str, lookup: list[dict[str, str]]) -> dict[str, str]:
    if not norm_test:
        return {"test_id": "", "mapped_name_ar": "", "mapped_name_en": ""}
    exact = next((x for x in lookup if x["key"] == norm_test), None)
    if exact:
        return {"test_id": exact["id"], "mapped_name_ar": exact["name_ar"], "mapped_name_en": exact["name_en"]}

    best: dict[str, str] | None = None
    best_score = 0
    for item in lookup:
        key = item["key"]
        if len(norm_test) < 4 or len(key) < 4:
            continue
        if norm_test in key or key in norm_test:
            score = min(len(norm_test), len(key))
            if score > best_score:
                best_score = score
                best = item
    if best and best_score >= 5:
        return {"test_id": best["id"], "mapped_name_ar": best["name_ar"], "mapped_name_en": best["name_en"]}
    return {"test_id": "", "mapped_name_ar": "", "mapped_name_en": ""}


def _load_runtime_tests_kb(runtime_dir: Path) -> list[dict[str, Any]]:
    path = runtime_dir / "tests_kb.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _safe_package_name(raw_name: str) -> str:
    value = str(raw_name or "")
    first_line = ""
    for line in value.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            first_line = line
            break
    if len(first_line) > 120:
        first_line = first_line[:120].rstrip()
    return first_line


def _remove_baqa_prefix(name: str) -> str:
    return re.sub(r"^\s*باقة\s+", "", name).strip()


def _english_phrases_from_name(name: str) -> list[str]:
    # Keep only 2+ token phrases; single generic tokens are blocked separately.
    phrases = re.findall(r"[A-Za-z0-9]+(?:\s+[A-Za-z0-9]+)+", name)
    out: list[str] = []
    for phrase in phrases:
        p = normalize_text(phrase)
        if not p:
            continue
        if len([t for t in p.split() if t]) < 2:
            continue
        out.append(phrase.strip())
    return out


def _package_alias_candidates(name: str) -> list[str]:
    candidates: list[str] = [name]
    no_prefix = _remove_baqa_prefix(name)
    if no_prefix and normalize_text(no_prefix) != normalize_text(name):
        candidates.append(no_prefix)
    candidates.extend(_english_phrases_from_name(name))
    return candidates


def _valid_alias(alias: str) -> bool:
    norm = normalize_text(alias)
    if not norm:
        return False
    tokens = [t for t in norm.split() if t]
    if len(tokens) == 1 and tokens[0] in PACKAGE_ALIAS_BLOCKLIST:
        return False
    return True


def make_package_display(package: dict[str, Any]) -> dict[str, Any]:
    tests = package.get("tests") or []
    clean_tests: list[str] = []
    for item in tests:
        t = str(item or "").strip()
        if not t:
            continue
        if len(t) > 130:
            continue
        if any(bad in t for bad in ("يكشف", "يستخدم", "يقيس", "يساعد", "يتم جمع", "يعكس")):
            continue
        clean_tests.append(t)
    return {
        "id": package.get("id"),
        "name": package.get("name"),
        "price": package.get("price"),
        "description_short": package.get("description_short"),
        "tests": clean_tests,
    }


def _drop_embedded_package_header_rows(df: pd.DataFrame, col_name: str | None, col_desc: str | None, col_price: str | None) -> pd.DataFrame:
    def is_headerish(value: Any) -> bool:
        t = normalize_text(value)
        if not t:
            return False
        return any(
            marker in t
            for marker in (
                normalize_text("اسم الباقه"),
                normalize_text("اسم الباقة"),
                normalize_text("وصف الباقه"),
                normalize_text("وصف الباقة"),
                normalize_text("سعر الباقه"),
                normalize_text("سعر الباقة"),
            )
        )

    mask = pd.Series(False, index=df.index)
    for c in [col_name, col_desc, col_price]:
        if c and c in df.columns:
            mask = mask | df[c].apply(is_headerish)
    return df[~mask].copy()


def build_packages(
    config: BuildConfig,
    pra_map: dict[str, dict[str, Any]],
    tests_kb: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, list[str]]]:
    df = clean_packages_excel(config.packages_path)

    map_tests_from = _load_runtime_tests_kb(config.runtime_dir)
    if not map_tests_from and tests_kb:
        map_tests_from = tests_kb
    tests_lookup = _prepare_tests_lookup(map_tests_from)

    packages: list[dict[str, Any]] = []
    by_name: dict[str, str] = {}
    alias_to_pkg_ids: dict[str, set[str]] = {}

    for _, row in df.iterrows():
        name_raw = str(row.get("name", "")).strip()
        description_long = str(row.get("description_long", ""))
        name = _safe_package_name(name_raw)
        if not name:
            continue

        price = _parse_price(row.get("price"))

        tests = _extract_test_names_strict(description_long)
        tests_mapped: list[dict[str, str]] = []
        for t in tests:
            key = normalize_text(t)
            matched = _match_test_to_kb(key, tests_lookup)
            if not matched["test_id"]:
                p = pra_map.get(key, {})
                matched["mapped_name_ar"] = matched["mapped_name_ar"] or p.get("name_ar", "")
                matched["mapped_name_en"] = matched["mapped_name_en"] or p.get("name_en", "")
            tests_mapped.append({"raw": t, "normalized": key, **matched})

        norm_name = normalize_text(name)
        if not norm_name:
            continue
        pkg_id = _stable_id("pkg", norm_name)

        package_obj = {
            "id": pkg_id,
            "name": name,
            "name_normalized": norm_name,
            "price": price,
            "description_short": _short_description(description_long),
            "description_long": description_long,
            "tests": tests,
            "tests_mapped": tests_mapped,
        }
        packages.append(package_obj)
        by_name[norm_name] = pkg_id

        for alias in _package_alias_candidates(name):
            alias_norm = normalize_text(alias)
            if not _valid_alias(alias_norm):
                continue
            alias_to_pkg_ids.setdefault(alias_norm, set()).add(pkg_id)

    packages.sort(key=lambda x: x["id"])

    aliases: dict[str, str] = {}
    alias_conflicts: dict[str, list[str]] = {}
    for alias, pkg_ids in alias_to_pkg_ids.items():
        if len(pkg_ids) == 1:
            aliases[alias] = next(iter(pkg_ids))
        else:
            alias_conflicts[alias] = sorted(pkg_ids)

    index = {
        "version": "packages_index_v2",
        "by_name": by_name,
        "aliases": aliases,
    }
    return packages, index, alias_conflicts


def build_faq_index(config: BuildConfig) -> dict[str, Any]:
    df = pd.read_excel(config.faq_path)
    col_q = _pick_column(df, ["question", "السؤال"], 0)
    col_a = _pick_column(df, ["answer", "الجواب", "الإجابة"], 1)
    items: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        q = str(row[col_q]).strip() if col_q and pd.notna(row[col_q]) else ""
        a = str(row[col_a]).strip() if col_a and pd.notna(row[col_a]) else ""
        if not q or not a:
            continue
        items[normalize_text(q)] = {"question": q, "answer": a}
    return {"normalize_version": NORMALIZE_VERSION, "items": items}


def build_branches_index(config: BuildConfig) -> dict[str, Any]:
    df = pd.read_excel(config.branches_path)
    col_city = _pick_column(df, ["city", "المدينة"], 0)
    col_area = _pick_column(df, ["area", "المنطقة"], 1)
    col_branch = _pick_column(df, ["branch_name", "branch", "الفرع"], 2)
    branches: list[dict[str, Any]] = []
    by_city: dict[str, list[str]] = {}
    by_area: dict[str, list[str]] = {}
    by_name: dict[str, str] = {}
    for _, row in df.iterrows():
        city = str(row[col_city]).strip() if col_city and pd.notna(row[col_city]) else ""
        area = str(row[col_area]).strip() if col_area and pd.notna(row[col_area]) else ""
        name = str(row[col_branch]).strip() if col_branch and pd.notna(row[col_branch]) else ""
        if not (city or area or name):
            continue
        key = normalize_text(name or f"{city} {area}")
        branch_id = _stable_id("branch", key)
        item = {
            "id": branch_id,
            "city": city,
            "area": area,
            "branch_name": name,
            "city_norm": normalize_text(city),
            "area_norm": normalize_text(area),
            "branch_name_norm": normalize_text(name),
        }
        branches.append(item)
        if item["city_norm"]:
            by_city.setdefault(item["city_norm"], []).append(branch_id)
        if item["area_norm"]:
            by_area.setdefault(item["area_norm"], []).append(branch_id)
        if item["branch_name_norm"]:
            by_name[item["branch_name_norm"]] = branch_id
    branches.sort(key=lambda x: x["id"])
    return {"branches": branches, "by_city": by_city, "by_area": by_area, "by_name": by_name}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_all(config: BuildConfig | None = None, write_embeddings: bool = True) -> dict[str, Any]:
    cfg = config or BuildConfig()
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)

    pra_map, _ = _load_praacise_master(cfg.praacise_path)
    tests_kb = build_tests_kb(cfg, pra_map)
    _write_json(cfg.runtime_dir / "tests_kb.json", tests_kb)

    packages, packages_index, packages_alias_conflicts = build_packages(cfg, pra_map, tests_kb=tests_kb)
    faq_index = build_faq_index(cfg)
    branches_index = build_branches_index(cfg)

    _write_json(cfg.runtime_dir / "packages.json", packages)
    _write_json(cfg.runtime_dir / "packages_index.json", packages_index)
    _write_json(cfg.runtime_dir / "faq_index.json", faq_index)
    _write_json(cfg.runtime_dir / "branches_index.json", branches_index)

    tests_embeddings = []
    if write_embeddings:
        for rec in tests_kb:
            doc = " ".join(
                [
                    str(rec.get("name_ar_final", "")),
                    str(rec.get("name_en_final", "")),
                    str(rec.get("description", "")),
                    str(rec.get("category", "")),
                ]
            ).strip()
            tests_embeddings.append({"id": rec["id"], "vector": embed(doc)})
        _write_json(cfg.runtime_dir / "tests_embeddings.json", tests_embeddings)

    manifest = {
        "build_time": datetime.now(timezone.utc).isoformat(),
        "version": "v2",
        "normalize_version": NORMALIZE_VERSION,
        "counts": {
            "tests_kb": len(tests_kb),
            "packages": len(packages),
            "faq_items": len(faq_index.get("items", {})),
            "branches": len(branches_index.get("branches", [])),
            "tests_embeddings": len(tests_embeddings),
        },
        "packages_alias_conflicts": packages_alias_conflicts,
        "sources": [
            cfg.analyses_path.name,
            cfg.praacise_path.name,
            cfg.packages_path.name,
            cfg.faq_path.name,
            cfg.branches_path.name,
        ],
        "outputs": [
            "tests_kb.json",
            "packages.json",
            "packages_index.json",
            "faq_index.json",
            "branches_index.json",
            "manifest.json",
        ]
        + (["tests_embeddings.json"] if write_embeddings else []),
    }
    _write_json(cfg.runtime_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Knowledge Engine V2 runtime artifacts.")
    parser.add_argument("--all", action="store_true", help="Build all V2 runtime outputs.")
    args = parser.parse_args()
    if not args.all:
        parser.print_help()
        return 1
    build_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
