"""Deterministic runtime resolver for package queries.

Active runtime source of truth:
- app/data/runtime/rag/packages_clean.jsonl

This resolver is intentionally self-contained and UTF-8 clean.
It supports:
- general package listing queries
- category/package-family listing queries
- specific package lookup
- package price queries
- package detail/contents queries
- Arabic + English keyword matching
- partial/misspelled matching via normalization + weighted scoring
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.runtime.entity_memory import load_entity_memory
from app.services.runtime.selection_state import load_selection_state, save_selection_state
from app.services.runtime.text_normalizer import normalize_arabic

PACKAGES_JSONL_PATH = Path("app/data/runtime/rag/packages_clean.jsonl")

_GENERAL_HINTS = (
    "باقات",
    "باقاتكم",
    "عندكم باقات",
    "وش عندكم باقات",
    "ايش عندكم باقات",
    "الباقات المتوفرة",
    "الباقات المتوفره",
    "الباقات المتاحة",
    "الباقات المتاحه",
    "ما هي الباقات",
    "ماهي الباقات",
    "وش الباقات",
    "وش هي الباقات",
    "ايش الباقات",
    "ايش الباقات المتوفرة",
    "الباقات اللي عندكم",
    "انواع الباقات",
    "أنواع الباقات",
    "البرامج",
    "packages",
    "package list",
    "available packages",
)

_GENERAL_LISTING_HINTS = (
    "وش الباقات",
    "وش هي الباقات",
    "وش الباقات اللي عندكم",
    "ايش الباقات",
    "ايش الباقات المتوفرة",
    "ماهي الباقات",
    "ما هي الباقات",
    "انواع الباقات",
    "أنواع الباقات",
    "الباقات المتوفرة",
    "الباقات المتوفره",
    "الباقات المتاحة",
    "الباقات المتاحه",
    "الباقات اللي عندكم",
    "عندكم باقات",
    "وش عندكم باقات",
    "ايش عندكم باقات",
    "available packages",
    "package list",
)

_PRICE_HINTS = (
    "كم سعر",
    "كم اسعار",
    "كم تكلف",
    "كم تكلفه",
    "كم تكلفها",
    "سعر",
    "اسعار",
    "بكم",
    "تكلف",
    "تكلفة",
    "كم سعرها",
    "سعرها",
    "price",
    "cost",
    "how much",
)

_DETAIL_HINTS = (
    "وش تشمل",
    "ايش تشمل",
    "وش فيها",
    "ايش فيها",
    "ماذا تشمل",
    "محتواها",
    "تفاصيل",
    "تفاصيلها",
    "محتوى",
    "وش هي",
    "ايش هي",
    "what does it include",
    "what is included",
    "include",
    "includes",
    "details",
)

_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "الباقات المتخصصة": (
        "رمضان",
        "متخصصة",
        "متخصصه",
        "specialized",
        "specialised",
    ),
    "الباقات الجينية التشخيصية": (
        "جيني",
        "جينيه",
        "جينية",
        "وراثي",
        "وراثية",
        "تشخيصي",
        "تشخيصية",
        "diagnostic genetic",
        "genetic diagnostic",
    ),
    "الباقات الجينية الوقائية": (
        "وقائي",
        "وقائية",
        "preventive genetic",
        "genetic preventive",
    ),
    "التحاليل المخبرية الفردية": (
        "تحاليل فردية",
        "تحاليل فرديه",
        "فردية",
        "فرديه",
        "single test",
        "individual tests",
    ),
    "التحاليل الذاتية": (
        "ذاتي",
        "ذاتية",
        "self collection",
        "home collection",
    ),
    "التحاليل الجينية": (
        "تحاليل جينية",
        "تحاليل جينيه",
        "genetic tests",
        "dna",
    ),
}

_PRICE_NOT_AVAILABLE = "سعر هذه الباقة غير متوفر حاليًا في البيانات الحالية."
_PACKAGE_NOT_FOUND = "ما قدرت أحدد باقة محددة من سؤالك. اكتب اسم الباقة بشكل أوضح."

_STOPWORDS = {
    "باقه", "باقة", "باقات", "برنامج", "برامج",
    "تحليل", "تحاليل", "فحص", "فحوصات", "تفاصيل", "التحاليل",
    "ابي", "ابغى", "أبغى", "اريد", "أريد", "بدي", "محتاج", "احتاج",
    "عندي", "شيء", "شي", "ابيها", "اريدها", "ابا", "أبي",
    "كم", "سعر", "اسعار", "بكم", "وش", "ايش", "إيش", "ما", "ماهو", "هو", "هي",
    "في", "عن", "على", "من", "مع", "الى", "إلى", "او", "أو", "و",
    "هذه", "هذا", "هذي", "هاذي", "هذيك", "ذلك", "تبع", "تبعها",
    "package", "packages", "price", "cost", "details", "detail", "include", "includes",
    "the", "a", "an", "for", "of", "to", "and", "or", "what", "is", "are",
}

_GENERIC_LOW_SIGNAL = {
    "صحه", "صحة", "تحاليل", "تحليل", "فحص", "فحوصات", "شامله", "شاملة",
    "متخصصه", "متخصصة", "متابعه", "متابعة", "الكشف", "المبكر", "تفاصيل",
    "باقه", "باقة", "برنامج", "package", "packages", "test", "tests",
}

_STRONG_KEYWORDS = {
    "غده", "درقيه", "درقية", "thyroid",
    "سكري", "سكر", "glucose", "diabetes", "diabetic",
    "شعر", "hair", "تساقط", "alopecia",
    "فيتامين", "فيتامينات", "vitamin", "vitamins",
    "حديد", "iron", "فريتين", "ferritin", "انيميا", "anemia", "anaemia",
    "هرمون", "هرمونات", "hormone", "hormonal",
    "اطفال", "طفل", "children", "kids", "child",
    "رجال", "men", "male", "man",
    "نساء", "مراه", "مرأة", "امرأة", "woman", "women", "female",
    "رمضان", "ramadan",
    "اكتئاب", "depression",
    "صداع", "headache", "migraine",
    "عظام", "bone", "bones",
    "كبد", "الكبد", "liver",
    "كلى", "الكلي", "kidney", "renal",
    "حساسيه", "حساسية", "allergy", "allergies",
    "قمح", "جلوتين", "gluten", "wheat",
    "اورام", "أورام", "سرطان", "tumor", "tumour", "cancer",
    "معديه", "معدية", "infection", "infectious",
    "قولون", "هضمي", "colon", "digestive", "gastro",
    "تكميم", "كميم", "sleeve", "bariatric",
    "مونجارو", "mounjaro", "tirzepatide",
    "روكتان", "roaccutane", "accutane", "isotretinoin",
    "زواج", "marriage", "premarital",
    "جهاض", "إجهاض", "miscarriage",
    "رياضيين", "رياضي", "athlete", "athletes",
    "جيني", "وراثي", "dna", "genetic", "nifty", "well", "gender", "silver", "gold", "platinum",
    "معادن", "املاح", "أملاح", "minerals", "magnesium", "zinc", "calcium",
    "دهون", "cholesterol", "lipid", "lipids",
    "تخسيس", "وزن", "weight", "slimming",
    "اطفال", "صحة", "children",
}

_SYNONYMS: dict[str, tuple[str, ...]] = {
    "غده": ("غده", "الغده", "غدد", "درقيه", "درقية", "thyroid", "tsh", "t3", "t4"),
    "سكري": ("سكري", "سكر", "glucose", "diabetes", "diabetic", "hba1c", "انسولين", "insulin", "homa", "homa-ir", "fbs"),
    "شعر": ("شعر", "hair", "تساقط", "تقصف", "alopecia"),
    "فيتامين": ("فيتامين", "فيتامينات", "vitamin", "vitamins", "vit d", "vitamin d", "b12", "b6", "multi vitamins"),
    "حديد": ("حديد", "مخزون", "فريتين", "iron", "ferritin", "anemia", "anaemia", "فقر", "دم"),
    "هرمون": ("هرمون", "هرمونات", "hormone", "hormonal", "testosterone", "estrogen", "prolactin", "lh", "fsh"),
    "اطفال": ("اطفال", "أطفال", "طفل", "child", "children", "kids", "pediatric"),
    "رجال": ("رجال", "للرجال", "men", "male", "man"),
    "نساء": ("نساء", "للنساء", "مراه", "مرأة", "امرأة", "women", "woman", "female"),
    "رمضان": ("رمضان", "ramadan", "صيام", "صائم"),
    "اكتئاب": ("اكتئاب", "depression", "mood", "مزاج"),
    "صداع": ("صداع", "headache", "migraine"),
    "عظام": ("عظام", "bone", "bones", "calcium", "فيتامين د"),
    "كبد": ("كبد", "الكبد", "liver", "alt", "ast", "ggt", "alp"),
    "كلى": ("كلى", "الكلى", "كليه", "kidney", "renal", "creatinine", "egfr", "bun"),
    "حساسيه": ("حساسيه", "حساسية", "allergy", "allergies", "gluten", "قمح", "حساسية المستنشقات"),
    "اورام": ("اورام", "أورام", "سرطان", "tumor", "tumour", "cancer", "marker"),
    "معديه": ("معديه", "معدية", "infection", "infectious", "std", "pcr", "urine"),
    "قولون": ("قولون", "هضمي", "digestive", "gastro", "colon", "gluten", "سيبو", "sibo"),
    "تكميم": ("تكميم", "sleeve", "bariatric", "weight"),
    "مونجارو": ("مونجارو", "mounjaro", "tirzepatide"),
    "روكتان": ("روكتان", "roaccutane", "accutane", "isotretinoin"),
    "زواج": ("زواج", "marriage", "premarital"),
    "جهاض": ("جهاض", "إجهاض", "miscarriage"),
    "جيني": ("جيني", "وراثي", "dna", "genetic", "genetics", "nifty", "well", "gender", "silver", "gold", "platinum"),
    "معادن": ("معادن", "املاح", "أملاح", "minerals", "magnesium", "zinc", "calcium", "sodium", "potassium"),
    "دهون": ("دهون", "cholesterol", "lipid", "lipids", "ldl", "hdl", "triglycerides", "tg"),
    "تخسيس": ("تخسيس", "وزن", "weight", "slimming", "mounjaro"),
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _base_norm(value: Any) -> str:
    text = normalize_arabic(_safe_str(value))
    if not text:
        return ""
    text = (
        text.replace("ة", "ه")
        .replace("ى", "ي")
        .replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ؤ", "و")
        .replace("ئ", "ي")
        .replace("ھ", "ه")
        .replace("ـ", "")
    )
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = re.sub(r"[^0-9a-zA-Z\u0600-\u06FF\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _norm(value: Any) -> str:
    return _base_norm(value)


def _light_stem(token: str) -> str:
    token = _base_norm(token)
    if not token:
        return ""
    if token.startswith("ال") and len(token) > 3:
        token = token[2:]
    if token.startswith("لل") and len(token) > 3:
        token = token[2:]
    if token.endswith("يات") and len(token) > 5:
        token = token[:-3]
    elif token.endswith("ات") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("ون") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("ين") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("يه") and len(token) > 4:
        token = token[:-2] + "ي"
    elif token.endswith("ه") and len(token) > 3:
        token = token[:-1]
    return token.strip()


def _build_alias_map() -> dict[str, set[str]]:
    alias_map: dict[str, set[str]] = {}
    for canonical, values in _SYNONYMS.items():
        bag = {_base_norm(canonical), _light_stem(canonical)}
        for value in values:
            bag.add(_base_norm(value))
            bag.add(_light_stem(value))
        alias_map[_base_norm(canonical)] = {v for v in bag if v}
    return alias_map


_ALIAS_MAP = _build_alias_map()


def _tokenize(value: Any) -> list[str]:
    text = _base_norm(value)
    if not text:
        return []
    raw_tokens = text.split()
    tokens: list[str] = []
    for token in raw_tokens:
        if not token or token in _STOPWORDS:
            continue
        if len(token) == 1:
            continue
        tokens.append(token)
    return tokens


def _expand_tokens(tokens: list[str]) -> set[str]:
    expanded: set[str] = set()
    for token in tokens:
        norm = _base_norm(token)
        stem = _light_stem(token)
        if norm:
            expanded.add(norm)
        if stem:
            expanded.add(stem)
        for variants in _ALIAS_MAP.values():
            if norm in variants or stem in variants:
                expanded.update(variants)
    return expanded


def _expand_synonyms(tokens: list[str]) -> set[str]:
    return _expand_tokens(tokens)


def _extract_bigrams(tokens: list[str]) -> set[str]:
    if len(tokens) < 2:
        return set()
    return {f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1)}


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _safe_str(value)
    if not text:
        return None
    text = text.replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


@lru_cache(maxsize=1)
def load_packages_records() -> list[dict[str, Any]]:
    """Load package records from packages_clean.jsonl only."""
    if not PACKAGES_JSONL_PATH.exists():
        return []

    rows: list[dict[str, Any]] = []
    with PACKAGES_JSONL_PATH.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = _safe_str(raw_line)
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            package_name = _safe_str(obj.get("package_name"))
            main_category = _safe_str(obj.get("main_category"))
            offering_type = _safe_str(obj.get("offering_type"))
            if not package_name:
                continue

            item = dict(obj)
            item["id"] = _safe_str(obj.get("id"))
            item["source"] = _safe_str(obj.get("source")) or "packages"
            item["main_category"] = main_category
            item["offering_type"] = offering_type or "package"
            item["package_name"] = package_name
            item["description_short"] = _safe_str(obj.get("description_short"))
            item["description_full"] = _safe_str(obj.get("description_full"))
            item["price_raw"] = _safe_str(obj.get("price_raw"))
            item["price_number"] = _to_float_or_none(obj.get("price_number") or obj.get("price_raw"))
            item["currency"] = _safe_str(obj.get("currency")) or "ريال"
            item["included_count"] = obj.get("included_count")
            item["runtime_present"] = bool(obj.get("runtime_present", True))
            item["review_issues"] = _safe_str(obj.get("review_issues"))
            item["source_row"] = obj.get("source_row")
            item["is_active"] = bool(obj.get("is_active", True))

            combined_text = " ".join(
                [
                    package_name,
                    main_category,
                    item["description_short"],
                    item["description_full"],
                ]
            )
            item["package_name_norm"] = _norm(package_name)
            item["main_category_norm"] = _norm(main_category)
            item["combined_text"] = combined_text
            item["combined_norm"] = _norm(combined_text)
            item["combined_tokens"] = _tokenize(combined_text)
            rows.append(item)
    return rows


def _is_price_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _PRICE_HINTS)


def _is_general_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _GENERAL_HINTS)


def _is_general_listing_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _GENERAL_LISTING_HINTS)


def _is_detail_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _DETAIL_HINTS)


def _is_best_for_query(query_norm: str) -> bool:
    keywords = [
        "ايش افضل",
        "ايش أفضل",
        "وش افضل",
        "وش أفضل",
        "ايش احسن",
        "وش احسن",
        "ايش أنسب",
        "وش أنسب",
        "وش تنصحني",
        "ايش تنصحني",
        "تنصحني",
        "وش مناسب",
        "ايش مناسب",
        "يفيد",
        "يفيدني",
        "شيء لـ",
        "شي لـ",
        "ابي شيء لـ",
        "ابغى شيء لـ",
        "ابي باقة لـ",
        "ابغى باقة لـ",
        "وش الأفضل لـ",
        "ايش الأفضل لـ",
        "احسن باقة لـ",
        "افضل باقة لـ",
        "best package",
        "recommend",
        "recommended",
    ]
    return any(_norm(k) in query_norm for k in keywords)


def _detect_category(query_norm: str, records: list[dict[str, Any]]) -> str:
    categories = {
        _safe_str(r.get("main_category")): _safe_str(r.get("main_category_norm"))
        for r in records
        if _safe_str(r.get("main_category"))
    }
    for cat, cat_norm in categories.items():
        if cat_norm and cat_norm in query_norm:
            return cat

    for category, hints in _CATEGORY_HINTS.items():
        if any(_norm(h) in query_norm for h in hints):
            return category
    return ""


def _is_category_like_query(query_norm: str, detected_category: str) -> bool:
    if not query_norm:
        return False
    if detected_category and _norm(detected_category) in query_norm:
        return True
    category_tokens = (
        "الفئة",
        "فئة",
        "تصنيف",
        "نوع الباقات",
        "باقات رمضان",
        "باقات جينية",
        "تحاليل جينية",
    )
    return any(_norm(t) in query_norm for t in category_tokens)


def _is_package_like_offering(record: dict[str, Any]) -> bool:
    offering = _norm(record.get("offering_type"))
    if not offering:
        return False
    excluded_tokens = ("single_test", "single", "individual", "test")
    if any(token in offering for token in excluded_tokens):
        return False
    included_tokens = ("package", "genetic_package", "bundle", "باقه", "باقة", "باقات")
    return any(token in offering for token in included_tokens)


def _score_package_match(query: str, record: dict[str, Any]) -> float:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return 0.0

    query_set = _expand_synonyms(query_tokens)
    query_bigrams = _extract_bigrams(query_tokens)

    name = _safe_str(record.get("package_name"))
    name_norm = _safe_str(record.get("package_name_norm"))
    category = _safe_str(record.get("main_category"))
    short_desc = _safe_str(record.get("description_short"))
    full_desc = _safe_str(record.get("description_full"))

    combined_text = " ".join([name, category, short_desc, full_desc])
    record_tokens = _tokenize(combined_text)
    if not record_tokens:
        return 0.0

    record_set = _expand_synonyms(record_tokens)
    record_bigrams = _extract_bigrams(record_tokens)

    score = 0.0

    # Strong exact full-name match.
    query_norm = _norm(query)
    if query_norm and query_norm == name_norm:
        score += 20.0
    elif query_norm and name_norm and (name_norm in query_norm or query_norm in name_norm):
        score += 12.0

    # Direct token overlap.
    exact_overlap = query_set.intersection(record_set)
    score += 4.0 * len(exact_overlap)

    # Strong keyword boost.
    for key in _STRONG_KEYWORDS:
        key_norm = _base_norm(key)
        if key_norm and key_norm in query_set and key_norm in record_set:
            score += 6.0

    # Synonym-family boost.
    for variants in _ALIAS_MAP.values():
        if query_set.intersection(variants) and record_set.intersection(variants):
            score += 3.0

    # Bigram/phrase boost.
    for phrase in query_bigrams:
        if phrase in record_bigrams:
            score += 6.0
        elif phrase and phrase in _norm(combined_text):
            score += 4.0

    # Partial substring boost.
    for qt in query_set:
        if not qt or qt in _GENERIC_LOW_SIGNAL:
            continue
        for rt in record_set:
            if not rt or rt in _GENERIC_LOW_SIGNAL:
                continue
            if qt == rt:
                continue
            if qt in rt or rt in qt:
                score += 1.5

    # Name-first weighting.
    name_tokens = _expand_synonyms(_tokenize(name))
    name_overlap = query_set.intersection(name_tokens)
    score += 3.0 * len(name_overlap)

    # Multi-token bonus.
    if len(exact_overlap) >= 2:
        score += 5.0
    elif len(exact_overlap) == 1:
        score += 1.0

    # Prefer shorter / cleaner name hit when ties happen.
    if name_tokens:
        score += min(2.0, len(name_overlap) / max(1.0, len(name_tokens)))

    # Light penalty when query only contains generic tokens.
    meaningful_query_tokens = {t for t in query_set if t not in _GENERIC_LOW_SIGNAL}
    if not meaningful_query_tokens:
        score -= 2.0

    if score <= 0:
        score -= 2.0

    return score


def _find_specific_package(query: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = float("-inf")
    second_score = float("-inf")

    for record in records:
        score = _score_package_match(query, record)
        if score > best_score:
            second_score = best_score
            best_score = score
            best = record
        elif score > second_score:
            second_score = score

    if best is None:
        return None

    # Conservative threshold to avoid random wrong package selection.
    if best_score < 3.0:
        return None

    # If top two are too close and score itself is not very strong, prefer no match.
    if second_score > float("-inf") and best_score < 8.0 and abs(best_score - second_score) < 1.5:
        return None

    return best


def _find_ambiguous_package_candidates(query: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for record in records:
        score = _score_package_match(query, record)
        if score >= 8.0:
            scored.append((score, record))
    if len(scored) < 2:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    top_score = scored[0][0]
    close_candidates = [row for score, row in scored if (top_score - score) <= 1.5]
    if len(close_candidates) < 2:
        return []
    return close_candidates[:5]


def _format_ambiguous_package_options(candidates: list[dict[str, Any]]) -> str:
    lines = ["لقيت أكثر من باقة قريبة:"]
    for idx, row in enumerate(candidates, start=1):
        lines.append(f"{idx}) {_safe_str(row.get('package_name'))}")
    lines.append("اكتب الرقم أو اسم الباقة التي تقصدها.")
    return "\n".join(lines)


def _extract_best_for_topic(query: str) -> str:
    text = _norm(query)
    if not text:
        return ""
    cleanup_phrases = (
        "وش افضل", "وش أفضل", "ايش افضل", "ايش أفضل",
        "وش احسن", "ايش احسن", "وش أنسب", "ايش أنسب",
        "وش تنصحني", "ايش تنصحني", "تنصحني",
        "وش مناسب", "ايش مناسب",
        "ابي", "ابغى", "باقة", "باقه", "شيء", "شي",
        "افضل", "أفضل", "احسن", "أنسب",
    )
    clean = text
    for phrase in cleanup_phrases:
        clean = clean.replace(_norm(phrase), " ")
    clean = re.sub(r"\s+", " ", clean).strip()

    # Prefer phrase after prep "لـ/لل"
    for marker in (" ل", "لل"):
        if marker in clean:
            tail = clean.split(marker, 1)[1].strip()
            if tail:
                clean = tail
                break

    tokens = [t for t in _tokenize(clean) if t not in {"باقه", "باقة", "افضل", "أفضل", "احسن", "أنسب", "وش", "ايش", "تنصحني", "ابي", "ابغى"}]
    clean_topic = " ".join(tokens).strip()
    return clean_topic


def _format_best_for_options(query: str, rows: list[dict[str, Any]]) -> str:
    topic = _extract_best_for_topic(query)
    if topic:
        topic_text = topic
        if topic_text.startswith("ل"):
            lines = [f"أفضل الباقات {topic_text}:"]
        else:
            lines = [f"أفضل الباقات لـ{topic_text}:"]
    else:
        lines = ["هذي أفضل الباقات المناسبة:"]
    for idx, row in enumerate(rows, start=1):
        lines.append(f"{idx}) {_safe_str(row.get('package_name'))}")
    lines.append("")
    lines.append("اختر رقم الباقة اللي حاب تعرف عنها أكثر.")
    return "\n".join(lines)


def _is_best_for_details_followup_query(query_norm: str) -> bool:
    hints = (
        "نعم",
        "ايوا",
        "ايوه",
        "اشرح",
        "فصل",
        "فصل لي",
        "فصل اكثر",
        "التفاصيل",
        "وش فيها",
        "ايش تشمل",
        "ايش التحاليل",
        "التفاصيل",
    )
    return any(_norm(h) == query_norm or _norm(h) in query_norm for h in hints)


def _is_best_for_price_followup_query(query_norm: str) -> bool:
    hints = ("السعر", "سعر", "بكم", "كم سعرها", "كم سعره")
    return any(_norm(h) == query_norm or _norm(h) in query_norm for h in hints)


def _find_package_by_label(label: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = _norm(label)
    if not target:
        return None
    for row in records:
        row_name = _norm(_safe_str(row.get("package_name")))
        if row_name and (row_name == target or row_name in target or target in row_name):
            return row
    return None


def _format_best_for_selected_preview(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    short_desc = _safe_str(record.get("description_short"))
    lines = [name]
    if short_desc:
        lines.extend(["", short_desc])
    lines.extend([
        "",
        "إذا حاب أعرفك أكثر على التفاصيل أو التحاليل اللي تشملها، اكتب:",
        "• التفاصيل",
        "• وش فيها",
    ])
    return "\n".join(lines)


def _format_best_for_long_details(record: dict[str, Any]) -> str:
    full_desc = _safe_str(record.get("description_full"))
    short_desc = _safe_str(record.get("description_short"))
    body = full_desc if full_desc and _norm(full_desc) != _norm(short_desc) else short_desc
    if not body:
        body = "ما عندي تفاصيل إضافية واضحة في البيانات الحالية."
    lines = [
        "تمام  خليني أفصل لك أكثر:",
        "",
        body,
        "",
        "إذا حاب تعرف السعر، اكتب:",
        "• السعر",
    ]
    return "\n".join(lines)


def _format_best_for_price(record: dict[str, Any]) -> str:
    base = _format_package_price(record)
    lines = [
        base,
        "",
        "إذا حاب أقارنها لك مع باقة ثانية أو أرشح لك خيار أفضل، قل لي",
    ]
    return "\n".join(lines)


def _save_package_options(conversation_id: UUID | None, rows: list[dict[str, Any]], query_type: str) -> None:
    if conversation_id is None or not rows:
        return
    save_selection_state(
        conversation_id,
        options=[
            {
                "id": _safe_str(row.get("id")) or f"package_option::{idx}",
                "label": _safe_str(row.get("package_name")),
                "selection_payload": {
                    "package_name": _safe_str(row.get("package_name")),
                },
            }
            for idx, row in enumerate(rows, start=1)
        ],
        selection_type="package",
        query_type=query_type,
    )


def _format_general_overview(
    records: list[dict[str, Any]],
    conversation_id: UUID | None = None,
    limit: int = 20,
) -> str:
    active_rows = [r for r in records if bool(r.get("is_active", True))]
    rows = active_rows or records
    _save_package_options(conversation_id, rows[:limit], query_type="package_general")

    lines = ["الباقات المتاحة حاليًا:"]
    for idx, r in enumerate(rows[:limit], start=1):
        name = _safe_str(r.get("package_name"))
        price = r.get("price_number")
        currency = _safe_str(r.get("currency") or "ريال")
        if isinstance(price, (int, float)):
            lines.append(f"{idx}) {name} - {price:g} {currency}")
        else:
            lines.append(f"{idx}) {name}")

    if len(rows) > limit:
        lines.append(f"... يوجد أيضًا {len(rows) - limit} باقات إضافية.")
    lines.append("اكتب اسم الباقة مباشرة أو رقمها أو الكلمات الأقرب لها عشان أعرض التفاصيل.")
    return "\n".join(lines)


def _format_category_packages(
    category: str,
    records: list[dict[str, Any]],
    conversation_id: UUID | None = None,
    limit: int = 20,
) -> str:
    rows = [r for r in records if _safe_str(r.get("main_category")) == category]
    if not rows:
        return "ما لقيت باقات في هذه الفئة حاليًا."

    _save_package_options(conversation_id, rows[:limit], query_type="package_category")

    lines = [f"الباقات المتاحة ضمن فئة {category}:"]
    for idx, r in enumerate(rows[:limit], start=1):
        name = _safe_str(r.get("package_name"))
        price = r.get("price_number")
        currency = _safe_str(r.get("currency") or "ريال")
        if isinstance(price, (int, float)):
            lines.append(f"{idx}) {name} - {price:g} {currency}")
        else:
            lines.append(f"{idx}) {name}")

    if len(rows) > limit:
        lines.append(f"... يوجد أيضًا {len(rows) - limit} باقات إضافية.")
    lines.append("اكتب اسم الباقة أو رقمها إذا تحب أعرض لك التفاصيل.")
    return "\n".join(lines)


def _format_package_details(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    short_desc = _safe_str(record.get("description_short"))
    full_desc = _safe_str(record.get("description_full"))

    lines = [name]
    if short_desc:
        lines.append("")
        lines.append(short_desc)
    if full_desc and full_desc != short_desc:
        lines.append("")
        lines.append(full_desc)
    lines.append("")
    lines.append("إذا حاب تعرف السعر أو تفاصيل أكثر، اكتب:")
    lines.append("- السعر")
    lines.append("- التفاصيل")
    return "\n".join(lines)


def _format_package_price(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    currency = _safe_str(record.get("currency") or "ريال")
    price = record.get("price_number")
    if isinstance(price, (int, float)):
        return f"سعر {name}: {price:g} {currency}."
    return _PRICE_NOT_AVAILABLE


def resolve_packages_query(user_text: str, conversation_id: UUID | None = None) -> dict[str, Any]:
    """Resolve package queries deterministically from packages_clean.jsonl."""
    query = _safe_str(user_text)
    query_norm = _norm(query)
    if not query_norm:
        return {
            "matched": False,
            "answer": "",
            "route": "packages_no_match",
            "meta": {"query_type": "no_match", "reason": "empty_query"},
        }

    records = [r for r in load_packages_records() if bool(r.get("is_active", True))]
    if not records:
        records = load_packages_records()
    if not records:
        return {
            "matched": False,
            "answer": "",
            "route": "packages_no_match",
            "meta": {"query_type": "no_match", "reason": "packages_data_unavailable"},
        }

    best_for_context = False
    remembered_package_label = ""
    if conversation_id is not None:
        state = load_selection_state(conversation_id)
        best_for_context = _safe_str(state.get("query_type")) == "package_best_for"
        memory = load_entity_memory(conversation_id)
        if _safe_str(memory.get("last_intent")) == "package" and bool(memory.get("last_intent_has_entity")):
            remembered_package_label = _safe_str((memory.get("last_package") or {}).get("label"))

    if best_for_context and remembered_package_label:
        remembered_record = _find_package_by_label(remembered_package_label, records)
        if remembered_record is not None:
            if _is_best_for_details_followup_query(query_norm):
                return {
                    "matched": True,
                    "answer": _format_best_for_long_details(remembered_record),
                    "route": "packages_best_for_details",
                    "meta": {"query_type": "package_best_for_query"},
                }
            if _is_best_for_price_followup_query(query_norm):
                return {
                    "matched": True,
                    "answer": _format_best_for_price(remembered_record),
                    "route": "packages_best_for_price",
                    "meta": {"query_type": "package_best_for_query"},
                }

    category = _detect_category(query_norm, records)
    category_like = _is_category_like_query(query_norm, category)
    general_like = _is_general_query(query_norm)
    general_listing_like = _is_general_listing_query(query_norm)
    best_for_query = _is_best_for_query(query_norm)
    price_query = _is_price_query(query_norm)
    detail_query = _is_detail_query(query_norm)

    # General list of all packages must win before specific matching.
    if general_listing_like and not price_query and not detail_query and not category:
        return {
            "matched": True,
            "answer": _format_general_overview(records, conversation_id),
            "route": "packages_general",
            "meta": {
                "query_type": "package_general",
                "categories_count": len({_safe_str(r.get("main_category")) for r in records if _safe_str(r.get("main_category"))}),
            },
        }

    # Explicit category listing.
    if category and category_like and not price_query:
        return {
            "matched": True,
            "answer": _format_category_packages(category, records, conversation_id),
            "route": "packages_category",
            "meta": {
                "query_type": "package_category",
                "category": category,
            },
        }

    if best_for_query:
        scored = []
        for r in records:
            if not _is_package_like_offering(r):
                continue
            score = _score_package_match(query, r)
            if score > 2:
                scored.append((score, r))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            unique_top: list[dict[str, Any]] = []
            seen: set[str] = set()
            for _, row in scored:
                row_id = _safe_str(row.get("matched_package_id")) or _safe_str(row.get("id"))
                identity = row_id or _norm(_safe_str(row.get("package_name")))
                if not identity or identity in seen:
                    continue
                seen.add(identity)
                unique_top.append(row)
                if len(unique_top) >= 2:
                    break

            _save_package_options(conversation_id, unique_top, query_type="package_best_for")

            return {
                "matched": True,
                "answer": _format_best_for_options(query, unique_top),
                "route": "packages_best_for",
                "meta": {"query_type": "package_best_for_query"},
            }

    specific_match = _find_specific_package(query, records)
    ambiguous_candidates = _find_ambiguous_package_candidates(query, records)

    if ambiguous_candidates:
        _save_package_options(conversation_id, ambiguous_candidates, query_type="package_ambiguity")
        return {
            "matched": True,
            "answer": _format_ambiguous_package_options(ambiguous_candidates),
            "route": "packages_ambiguous",
            "meta": {
                "query_type": "package_ambiguity",
                "candidates_count": len(ambiguous_candidates),
            },
        }

    if price_query and specific_match is not None:
        package_id = _safe_str(specific_match.get("id"))
        if best_for_context:
            return {
                "matched": True,
                "answer": _format_best_for_price(specific_match),
                "route": "packages_best_for_price",
                "meta": {
                    "query_type": "package_best_for_query",
                    "matched_package_id": package_id,
                    "matched_package_name": _safe_str(specific_match.get("package_name")),
                },
            }
        return {
            "matched": True,
            "answer": _format_package_price(specific_match),
            "route": "packages_price",
            "meta": {
                "query_type": "package_price_query",
                "matched_package_id": package_id,
                "matched_package_name": _safe_str(specific_match.get("package_name")),
                "category": _safe_str(specific_match.get("main_category")),
                "price_available": isinstance(specific_match.get("price_number"), (int, float)),
            },
        }

    if specific_match is not None:
        package_id = _safe_str(specific_match.get("id"))
        if best_for_context and not detail_query:
            return {
                "matched": True,
                "answer": _format_best_for_selected_preview(specific_match),
                "route": "packages_best_for_selected",
                "meta": {
                    "query_type": "package_best_for_query",
                    "matched_package_id": package_id,
                    "matched_package_name": _safe_str(specific_match.get("package_name")),
                    "category": _safe_str(specific_match.get("main_category")),
                },
            }
        if best_for_context and detail_query:
            return {
                "matched": True,
                "answer": _format_best_for_long_details(specific_match),
                "route": "packages_best_for_details",
                "meta": {
                    "query_type": "package_best_for_query",
                    "matched_package_id": package_id,
                    "matched_package_name": _safe_str(specific_match.get("package_name")),
                    "category": _safe_str(specific_match.get("main_category")),
                },
            }
        return {
            "matched": True,
            "answer": _format_package_details(specific_match),
            "route": "packages_specific",
            "meta": {
                "query_type": "package_specific",
                "matched_package_id": package_id,
                "matched_package_name": _safe_str(specific_match.get("package_name")),
                "category": _safe_str(specific_match.get("main_category")),
            },
        }

    # If category detected but not phrased as explicit category request, still show that category.
    if category:
        return {
            "matched": True,
            "answer": _format_category_packages(category, records, conversation_id),
            "route": "packages_category",
            "meta": {
                "query_type": "package_category",
                "category": category,
            },
        }

    if general_like:
        return {
            "matched": True,
            "answer": _format_general_overview(records, conversation_id),
            "route": "packages_general",
            "meta": {
                "query_type": "package_general",
                "categories_count": len({_safe_str(r.get("main_category")) for r in records if _safe_str(r.get("main_category"))}),
            },
        }

    if price_query:
        return {
            "matched": True,
            "answer": _PACKAGE_NOT_FOUND,
            "route": "packages_price",
            "meta": {
                "query_type": "package_price_query",
                "matched_package_id": "",
                "reason": "price_query_without_specific_package",
            },
        }

    return {
        "matched": False,
        "answer": "",
        "route": "packages_no_match",
        "meta": {"query_type": "no_match", "reason": "not_packages_intent"},
    }


if __name__ == "__main__":
    samples = [
        "وش الباقات اللي عندكم",
        "بكم باقة الغدة",
        "وش تشمل باقة الغدة",
        "تحليل الحساسية",
        "صحة الاطفال",
        "باقات رمضان",
    ]
    for text in samples:
        result = resolve_packages_query(text)
        print(f"INPUT: {text}")
        print(f"ROUTE: {result.get('route')}")
        print(f"MATCHED: {result.get('matched')}")
        print(f"META: {result.get('meta')}")
        print(f"ANSWER: {result.get('answer')}")
        print("-" * 72)
