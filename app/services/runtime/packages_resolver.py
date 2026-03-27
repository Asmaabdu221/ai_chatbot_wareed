"""Deterministic runtime resolver for package queries.

Rebuilt to use ONLY packages_clean.jsonl as the active runtime source of truth.
Matching is corpus-driven from package_name/category/descriptions in the JSONL.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.runtime.selection_state import save_selection_state
from app.services.runtime.text_normalizer import normalize_arabic

PACKAGES_JSONL_PATH = Path("app/data/runtime/rag/packages_clean.jsonl")

_GENERAL_HINTS = (
    "باقات",
    "باقاتكم",
    "عندكم باقات",
    "وش عندكم باقات",
    "ايش عندكم باقات",
    "الباقات المتوفره",
    "الباقات المتاحة",
    "وش الباقات",
    "ايش الباقات",
    "ايش الباقات المتوفره",
    "ما هي الباقات",
    "البرامج",
    "packages",
    "package list",
)

_GENERAL_LISTING_HINTS = (
    "وش الباقات",
    "ايش الباقات",
    "ماهي الباقات",
    "ما هي الباقات",
    "انواع الباقات",
    "الباقات المتوفرة",
    "الباقات المتاحة",
    "الباقات اللي عندكم",
    "عندكم باقات",
)

_PRICE_HINTS = (
    "كم سعر",
    "كم اسعار",
    "سعر",
    "اسعار",
    "بكم",
    "كم تكلف",
    "تكلف",
    "تكلفة",
    "price",
    "cost",
)

_DETAIL_HINTS = (
    "وش تشمل",
    "ايش تشمل",
    "وش فيها",
    "ايش فيها",
    "تفاصيل",
    "محتوى",
    "contains",
    "details",
    "what does it include",
    "include",
)

_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "الباقات المتخصصة": ("رمضان", "متخصصه", "متخصصة", "specialized"),
    "الباقات الجينية التشخيصية": ("جيني", "وراثي", "تشخيصي", "diagnostic genetic"),
    "الباقات الجينية الوقائية": ("جيني", "وراثي", "وقائي", "preventive genetic"),
    "التحاليل المخبرية الفردية": ("تحاليل فرديه", "تحاليل فردية", "single test", "individual tests"),
    "التحاليل الذاتية": ("ذاتي", "ذاتيه", "self collection", "home collection"),
    "التحاليل الجينية": ("تحاليل جينيه", "تحاليل جينية", "genetic tests"),
}

_PRICE_NOT_AVAILABLE = "سعر هذه الباقة غير متوفر حاليًا في البيانات الحالية."
_PACKAGE_NOT_FOUND = "ما قدرت أحدد باقة محددة من سؤالك. اكتب اسم الباقة بشكل أوضح."

_STOPWORDS = {
    "باقه", "باقة", "باقات", "تحليل", "تحاليل", "فحص", "تفاصيل", "التحاليل",
    "ابي", "ابغى", "اريد", "بدي", "محتاج", "احتاج", "عندي", "شيء", "شي", "ابيها",
    "كم", "سعر", "اسعار", "بكم", "وش", "ايش", "ما", "ماهو", "هو", "هي", "في", "عن",
    "ل", "لل", "على", "من", "مع", "الى", "او", "و", "او", "بعد", "قبل", "هذه", "هذا",
    "package", "packages", "price", "cost", "details", "detail", "include", "includes",
    "the", "a", "an", "for", "of", "to", "and", "or",
}

_GENERIC_LOW_SIGNAL = {
    "صحه", "صحة", "تحاليل", "تحليل", "فحص", "فحوصات", "شامله", "شاملة", "متخصصه", "متخصصة",
    "متابعه", "متابعة", "الكشف", "المبكر", "تفاصيل", "باقه", "باقة", "package", "packages",
    "test", "tests",
}

_STRONG_KEYWORDS = {
    "غده", "درقيه", "درقية", "thyroid",
    "سكري", "سكر", "glucose", "diabetes", "diabetic",
    "شعر", "hair", "تساقط", "alopecia",
    "فيتامين", "فيتامينات", "vitamin", "vitamins",
    "حديد", "iron", "فقر", "انيميا", "anemia", "anaemia",
    "هرمون", "هرمونات", "hormone", "hormonal",
    "اطفال", "طفل", "children", "kids", "child",
    "رجال", "men", "male", "man",
    "نساء", "مراه", "مرأة", "woman", "women", "female",
    "رمضان", "ramadan",
    "اكتئاب", "depression",
    "صداع", "migraine", "headache",
    "عظام", "bone", "bones",
    "كبد", "الكبد", "liver",
    "كلى", "الكلي", "kidney", "renal",
    "حساسيه", "حساسية", "allergy", "allergies",
    "قمح", "جلوتين", "gluten", "wheat",
    "اورام", "سرطان", "tumor", "tumour", "cancer",
    "معديه", "معدية", "pcr", "std", "infection", "infectious",
    "قولون", "هضمي", "colon", "digestive", "gastro",
    "تكميم", "كميم", "sleeve",
    "مونجارو", "mounjaro",
    "روكتان", "roaccutane", "accutane", "isotretinoin",
    "زواج", "marriage", "premarital",
    "جهاض", "إجهاض", "miscarriage",
    "رياضيين", "رياضي", "athlete", "athletes",
    "dna", "well", "silver", "gold", "platinum", "nifty", "gender", "جيني", "وراثي",
    "معادن", "املاح", "magnesium", "zinc", "calcium", "minerals",
    "دهون", "cholesterol", "lipid", "lipids",
}

_SYNONYMS: dict[str, tuple[str, ...]] = {
    "غده": ("غده", "الغده", "غدد", "درقيه", "درقية", "thyroid", "thyroids", "tsh", "t3", "t4"),
    "سكري": ("سكري", "سكر", "glucose", "diabetes", "diabetic", "hba1c", "انسولين", "insulin", "homa", "homa-ir"),
    "شعر": ("شعر", "hair", "تساقط", "تقصف", "alopecia"),
    "فيتامين": ("فيتامين", "فيتامينات", "vitamin", "vitamins", "vit d", "vitamin d", "b12"),
    "حديد": ("حديد", "فريتين", "مخزون", "iron", "ferritin", "anaemia", "anemia", "فقر", "دم"),
    "هرمون": ("هرمون", "هرمونات", "hormone", "hormonal", "testosterone", "estrogen", "prolactin", "lh", "fsh"),
    "اطفال": ("اطفال", "طفل", "أطفال", "child", "children", "kids", "pediatric"),
    "رجال": ("رجال", "للرجال", "men", "male", "man"),
    "نساء": ("نساء", "للنساء", "مراه", "مرأة", "امرأة", "women", "woman", "female"),
    "رمضان": ("رمضان", "ramadan", "صيام", "صائم"),
    "اكتئاب": ("اكتئاب", "depression", "mood", "مزاج"),
    "صداع": ("صداع", "headache", "migraine"),
    "عظام": ("عظام", "bone", "bones", "calcium", "فيتامين د"),
    "كبد": ("كبد", "الكبد", "liver", "alt", "ast", "ggt", "alp"),
    "كلى": ("كلى", "الكلى", "كليه", "kidney", "renal", "creatinine", "egfr", "bun"),
    "حساسيه": ("حساسيه", "حساسية", "allergy", "allergies", "gluten", "قمح"),
    "اورام": ("اورام", "اورام", "سرطان", "tumor", "tumour", "cancer", "marker"),
    "معديه": ("معديه", "معدية", "infection", "infectious", "pcr", "std", "urine"),
    "قولون": ("قولون", "هضمي", "digestive", "gastro", "gluten", "سيبو", "sibo"),
    "تكميم": ("تكميم", "sleeve", "bariatric", "weight"),
    "مونجارو": ("مونجارو", "mounjaro", "tirzepatide"),
    "روكتان": ("روكتان", "roaccutane", "accutane", "isotretinoin"),
    "زواج": ("زواج", "marriage", "premarital"),
    "جيني": ("جيني", "وراثي", "dna", "genetic", "genetics", "nifty", "well", "gender"),
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
    if token.endswith("يه") and len(token) > 4:
        token = token[:-2] + "ي"
    elif token.endswith("يه") and len(token) > 3:
        token = token[:-1]
    elif token.endswith("ه") and len(token) > 3:
        token = token[:-1]
    elif token.endswith("ات") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("ون") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("ين") and len(token) > 4:
        token = token[:-2]
    return token.strip()


def _english_alias_norms() -> dict[str, set[str]]:
    alias_map: dict[str, set[str]] = {}
    for canonical, values in _SYNONYMS.items():
        bag = {_base_norm(canonical), _light_stem(canonical)}
        for value in values:
            bag.add(_base_norm(value))
            bag.add(_light_stem(value))
        alias_map[_base_norm(canonical)] = {v for v in bag if v}
    return alias_map


_ALIAS_MAP = _english_alias_norms()


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
    try:
        return float(text)
    except ValueError:
        return None


def _query_without_price_words(query: str) -> str:
    text = _base_norm(query)
    if not text:
        return ""
    removal_phrases = (
        "كم سعر", "كم اسعار", "ما سعر", "وش سعر", "ايش سعر", "بكم", "price", "cost",
        "وش تشمل", "ايش تشمل", "وش فيها", "ايش فيها", "تفاصيل",
    )
    for phrase in removal_phrases:
        text = text.replace(_base_norm(phrase), " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _record_text_blob(item: dict[str, Any]) -> str:
    return " | ".join(
        part for part in (
            _safe_str(item.get("package_name")),
            _safe_str(item.get("main_category")),
            _safe_str(item.get("offering_type")),
            _safe_str(item.get("description_short")),
            _safe_str(item.get("description_full")),
        )
        if part
    )


def _doc_frequency(records: list[dict[str, Any]]) -> dict[str, int]:
    df: dict[str, int] = {}
    for row in records:
        seen = set(_tokenize(_record_text_blob(row)))
        for token in seen:
            df[token] = df.get(token, 0) + 1
            stem = _light_stem(token)
            if stem:
                df[stem] = df.get(stem, 0) + 1
    return df


@lru_cache(maxsize=1)
def load_packages_records() -> list[dict[str, Any]]:
    """Load runtime package records from packages_clean.jsonl only."""
    if not PACKAGES_JSONL_PATH.exists():
        return []

    base_rows: list[dict[str, Any]] = []
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
            if not package_name or not main_category or not offering_type:
                continue

            item = dict(obj)
            item["id"] = _safe_str(obj.get("id"))
            item["source"] = _safe_str(obj.get("source")) or "packages"
            item["main_category"] = main_category
            item["offering_type"] = offering_type
            item["package_name"] = package_name
            item["description_short"] = _safe_str(obj.get("description_short"))
            item["description_full"] = _safe_str(obj.get("description_full"))
            item["price_raw"] = _safe_str(obj.get("price_raw"))
            item["price_number"] = _to_float_or_none(obj.get("price_number"))
            item["currency"] = _safe_str(obj.get("currency"))
            item["included_count"] = obj.get("included_count")
            item["runtime_present"] = bool(obj.get("runtime_present"))
            item["review_issues"] = _safe_str(obj.get("review_issues"))
            item["source_row"] = obj.get("source_row")
            item["is_active"] = bool(obj.get("is_active", True))
            base_rows.append(item)

    # Deduplicate exact repeated entries by normalized name + category + price + offering_type
    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for item in base_rows:
        key = (
            _base_norm(item.get("package_name")),
            _base_norm(item.get("main_category")),
            _safe_str(item.get("offering_type")),
            _safe_str(item.get("price_raw")) or str(item.get("price_number") or ""),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)

    df = _doc_frequency(deduped)

    rows: list[dict[str, Any]] = []
    for item in deduped:
        text_blob = _record_text_blob(item)
        package_name_norm = _base_norm(item.get("package_name"))
        main_category_norm = _base_norm(item.get("main_category"))
        package_name_tokens = _tokenize(item.get("package_name"))
        category_tokens = _tokenize(item.get("main_category"))
        desc_tokens = _tokenize(" ".join([
            _safe_str(item.get("description_short")),
            _safe_str(item.get("description_full"))[:1200],
        ]))
        blob_tokens = _tokenize(text_blob)

        all_tokens = list(dict.fromkeys(package_name_tokens + category_tokens + desc_tokens + blob_tokens))
        all_stems = {_light_stem(t) for t in all_tokens if _light_stem(t)}
        bigrams = _extract_bigrams(package_name_tokens)
        keyword_weights: dict[str, float] = {}
        for token in all_tokens:
            stem = _light_stem(token)
            doc_count = max(1, df.get(token) or df.get(stem) or 1)
            rarity_bonus = 1.0 / math.sqrt(doc_count)
            base = 1.2 if token in package_name_tokens else 0.7
            if token in _STRONG_KEYWORDS or stem in _STRONG_KEYWORDS:
                base += 1.3
            if token in _GENERIC_LOW_SIGNAL or stem in _GENERIC_LOW_SIGNAL:
                base -= 0.5
            keyword_weights[token] = round(max(0.15, base + rarity_bonus), 4)

        row = dict(item)
        row["package_name_norm"] = package_name_norm
        row["main_category_norm"] = main_category_norm
        row["text_blob_norm"] = _base_norm(text_blob)
        row["package_name_tokens"] = package_name_tokens
        row["category_tokens"] = category_tokens
        row["desc_tokens"] = desc_tokens
        row["all_tokens"] = all_tokens
        row["all_stems"] = list(all_stems)
        row["name_bigrams"] = list(bigrams)
        row["keyword_weights"] = keyword_weights
        rows.append(row)

    return rows


def _is_price_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _PRICE_HINTS)


def _is_general_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _GENERAL_HINTS)


def _is_general_listing_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _GENERAL_LISTING_HINTS)


def _is_detail_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _DETAIL_HINTS)


def _detect_category(query_norm: str, records: list[dict[str, Any]]) -> str:
    categories = {
        _safe_str(r.get("main_category")): _safe_str(r.get("main_category_norm")) for r in records
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
    if detected_category and detected_category and _base_norm(detected_category) in query_norm:
        return True

    category_tokens = (
        "التحاليل الذاتيه",
        "التحاليل الذاتية",
        "التحاليل الجينيه",
        "التحاليل الجينية",
        "الباقات الجينيه",
        "الباقات الجينية",
        "فئه",
        "فئة",
        "تصنيف",
        "category",
    )
    return any(_norm(t) in query_norm for t in category_tokens)


def _score_package_match(query_text: str, record: dict[str, Any]) -> float:
    query_norm = _base_norm(query_text)
    if not query_norm:
        return 0.0

    record_name = _safe_str(record.get("package_name"))
    name_norm = _safe_str(record.get("package_name_norm"))
    text_blob_norm = _safe_str(record.get("text_blob_norm"))
    if not name_norm:
        return 0.0

    query_core = _query_without_price_words(query_norm)
    query_tokens = _tokenize(query_core or query_norm)
    query_expanded = _expand_tokens(query_tokens)
    query_stems = {_light_stem(t) for t in query_expanded if _light_stem(t)}
    query_bigrams = _extract_bigrams(query_tokens)

    name_tokens = set(record.get("package_name_tokens") or [])
    category_tokens = set(record.get("category_tokens") or [])
    desc_tokens = set(record.get("desc_tokens") or [])
    all_tokens = set(record.get("all_tokens") or [])
    all_stems = set(record.get("all_stems") or [])
    name_bigrams = set(record.get("name_bigrams") or [])
    keyword_weights: dict[str, float] = dict(record.get("keyword_weights") or {})

    score = 0.0

    # Strong direct equality / containment.
    if query_norm == name_norm or query_core == name_norm:
        score += 120.0
    if query_core and query_core in name_norm:
        score += 48.0
    if query_core and name_norm in query_core:
        score += 28.0
    if query_norm in text_blob_norm:
        score += 20.0

    # Token exact matches, weighted by rarity and field importance.
    overlap_count = 0
    for token in query_expanded:
        stem = _light_stem(token)
        token_weight = keyword_weights.get(token, keyword_weights.get(stem, 0.75))

        if token in name_tokens:
            score += 9.0 * token_weight
            overlap_count += 1
            continue
        if stem and stem in name_tokens:
            score += 8.0 * token_weight
            overlap_count += 1
            continue
        if token in category_tokens:
            score += 4.0 * token_weight
            overlap_count += 1
            continue
        if token in all_tokens:
            score += 3.2 * token_weight
            overlap_count += 1
            continue
        if stem and stem in all_stems:
            score += 2.5 * token_weight
            overlap_count += 1
            continue

        # Partial / substring support.
        for candidate in name_tokens:
            if token and candidate and (token in candidate or candidate in token):
                score += 3.0 * token_weight
                overlap_count += 1
                break
        else:
            for candidate in all_tokens:
                if token and candidate and (token in candidate or candidate in token):
                    score += 1.4 * token_weight
                    overlap_count += 1
                    break

    # Bigram / phrase bonuses.
    for bigram in query_bigrams:
        if bigram in name_bigrams:
            score += 12.0
        elif bigram and bigram in text_blob_norm:
            score += 6.0

    # Strong keyword bonuses.
    for keyword in _STRONG_KEYWORDS:
        keyword_norm = _base_norm(keyword)
        keyword_stem = _light_stem(keyword)
        if (keyword_norm in query_expanded or keyword_stem in query_stems) and (
            keyword_norm in all_tokens or keyword_stem in all_stems or keyword_norm in text_blob_norm
        ):
            score += 10.0

    # Similarity fallback against package name only.
    # This is intentionally low weight to avoid wrong nearest-name picks.
    if query_core:
        intersection = len(set(query_tokens) & name_tokens)
        union = max(1, len(set(query_tokens) | name_tokens))
        jaccard = intersection / union
        score += 10.0 * jaccard

    # Multi-token coherence bonus.
    if overlap_count >= 2:
        score += 8.0
    elif overlap_count == 1:
        score += 1.5

    # Penalize generic-only overlap to avoid "صحة" matching every package.
    generic_hits = 0
    for token in query_tokens:
        stem = _light_stem(token)
        if token in _GENERIC_LOW_SIGNAL or stem in _GENERIC_LOW_SIGNAL:
            if token in all_tokens or stem in all_stems:
                generic_hits += 1
    if generic_hits and overlap_count <= generic_hits:
        score -= 6.0

    # Penalize if nothing actually overlaps.
    if overlap_count == 0 and query_core not in name_norm and name_norm not in query_core:
        score -= 8.0

    # Slight bonus for package/test wording alignment.
    offering = _safe_str(record.get("offering_type")).lower()
    if "dna" in query_expanded and "genetic" in offering:
        score += 4.0
    if "package" in query_expanded and "package" in offering:
        score += 2.0

    return round(score, 4)


def _find_specific_package(query_text: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = float("-inf")
    second_score = float("-inf")

    for record in records:
        score = _score_package_match(query_text, record)
        if score > best_score:
            second_score = best_score
            best_score = score
            best = record
        elif score > second_score:
            second_score = score

    if best is None:
        return None

    # Conservative threshold + margin to reduce wrong selections.
    if best_score < 8.0:
        return None
    if second_score > float("-inf") and best_score - second_score < 1.5 and best_score < 18.0:
        return None
    return best


def _format_general_overview(records: list[dict[str, Any]], conversation_id: UUID | None = None) -> str:
    active_rows = [r for r in records if "package" in _safe_str(r.get("offering_type")).lower()]
    rows = active_rows or records
    rows = sorted(
        rows,
        key=lambda r: (
            0 if isinstance(r.get("price_number"), (int, float)) else 1,
            _safe_str(r.get("package_name")),
        ),
    )
    top_rows = rows[:20]

    if conversation_id is not None and top_rows:
        save_selection_state(
            conversation_id,
            options=[
                {
                    "id": _safe_str(row.get("id")) or f"package_option::{idx}",
                    "label": _safe_str(row.get("package_name")),
                    "selection_payload": {"package_name": _safe_str(row.get("package_name"))},
                }
                for idx, row in enumerate(top_rows, start=1)
            ],
            selection_type="package",
            query_type="package_general",
        )

    counts: dict[str, int] = {}
    for r in rows:
        cat = _safe_str(r.get("main_category"))
        if cat:
            counts[cat] = counts.get(cat, 0) + 1

    lines = ["الباقات المتاحة حاليًا:"]
    for idx, row in enumerate(top_rows, start=1):
        name = _safe_str(row.get("package_name"))
        price = row.get("price_number")
        if isinstance(price, (int, float)):
            lines.append(f"{idx}) {name} - {price:g} {_safe_str(row.get('currency') or 'ريال')}")
        else:
            lines.append(f"{idx}) {name}")
    if len(rows) > len(top_rows):
        lines.append(f"... يوجد أيضًا {len(rows) - len(top_rows)} باقات إضافية.")
    lines.append("اكتب اسم الباقة مباشرة أو رقمها أو الكلمات الأقرب لها عشان أعرض التفاصيل.")
    return "\n".join(lines)


def _format_category_packages(category: str, records: list[dict[str, Any]], conversation_id: UUID | None = None) -> str:
    rows = [r for r in records if _safe_str(r.get("main_category")) == category]
    if not rows:
        return "ما لقيت باقات في هذه الفئة حاليًا."

    if conversation_id is not None:
        save_selection_state(
            conversation_id,
            options=[
                {
                    "id": _safe_str(row.get("id")) or f"package_option::{idx}",
                    "label": _safe_str(row.get("package_name")),
                    "selection_payload": {"package_name": _safe_str(row.get("package_name"))},
                }
                for idx, row in enumerate(rows[:20], start=1)
            ],
            selection_type="package",
            query_type="package_category",
        )

    lines = [f"الباقات المتاحة ضمن فئة {category}:"]
    for idx, r in enumerate(rows[:20], start=1):
        name = _safe_str(r.get("package_name"))
        price = r.get("price_number")
        if isinstance(price, (int, float)):
            lines.append(f"{idx}) {name} - {price:g} {_safe_str(r.get('currency') or 'ريال')}")
        else:
            lines.append(f"{idx}) {name}")
    if len(rows) > 20:
        lines.append(f"... ({len(rows) - 20} عناصر إضافية)")
    lines.append("اكتب اسم العنصر أو رقمه عشان أعرض تفاصيله.")
    return "\n".join(lines)


def _format_package_details(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    category = _safe_str(record.get("main_category"))
    offering_type = _safe_str(record.get("offering_type"))
    desc = _safe_str(record.get("description_short")) or _safe_str(record.get("description_full"))
    currency = _safe_str(record.get("currency") or "ريال")
    price = record.get("price_number")

    lines = [
        f"{name}",
        f"الفئة: {category}",
        f"النوع: {offering_type}",
    ]
    if desc:
        lines.append(f"الوصف: {desc}")
    if isinstance(price, (int, float)):
        lines.append(f"السعر: {price:g} {currency}")
    else:
        lines.append(_PRICE_NOT_AVAILABLE)
    return "\n".join(lines)


def _format_package_price(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    currency = _safe_str(record.get("currency") or "ريال")
    price = record.get("price_number")
    if isinstance(price, (int, float)):
        return f"سعر {name}: {price:g} {currency}."
    return _PRICE_NOT_AVAILABLE


def resolve_packages_query(user_text: str, conversation_id: UUID | None = None) -> dict[str, Any]:
    """Resolve package-like queries deterministically from packages_clean.jsonl."""
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

    category = _detect_category(query_norm, records)
    category_like = _is_category_like_query(query_norm, category)
    general_like = _is_general_query(query_norm)
    general_listing_like = _is_general_listing_query(query_norm)
    price_query = _is_price_query(query_norm)
    detail_query = _is_detail_query(query_norm)
    specific_match = _find_specific_package(query, records)

    # Category queries should win when they are clearly asking about a category list,
    # unless we have a strong specific package match.
    if category and category_like and not price_query and specific_match is None:
        return {
            "matched": True,
            "answer": _format_category_packages(category, records, conversation_id),
            "route": "packages_category",
            "meta": {
                "query_type": "package_category",
                "category": category,
            },
        }

    # Explicit package-listing requests should return the general overview
    # before specific package matching.
    if general_listing_like and not price_query and not category:
        return {
            "matched": True,
            "answer": _format_general_overview(records, conversation_id),
            "route": "packages_general",
            "meta": {
                "query_type": "package_general",
                "categories_count": len({_safe_str(r.get('main_category')) for r in records}),
            },
        }

    if specific_match is not None and price_query:
        package_id = _safe_str(specific_match.get("id"))
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
        route = "packages_specific_details" if detail_query else "packages_specific"
        return {
            "matched": True,
            "answer": _format_package_details(specific_match),
            "route": route,
            "meta": {
                "query_type": "package_specific",
                "matched_package_id": package_id,
                "matched_package_name": _safe_str(specific_match.get("package_name")),
                "category": _safe_str(specific_match.get("main_category")),
            },
        }

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

    if general_like or "باقه" in query_norm or "باقات" in query_norm or "package" in query_norm:
        return {
            "matched": True,
            "answer": _format_general_overview(records, conversation_id),
            "route": "packages_general",
            "meta": {
                "query_type": "package_general",
                "categories_count": len({_safe_str(r.get('main_category')) for r in records}),
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
    try:
        import sys

        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    samples = [
        "وش عندكم باقات",
        "باقات رمضان",
        "باقة نهار رمضان الشاملة",
        "كم سعر باقة نهار رمضان الشاملة",
        "بكم باقه صحه الغده",
        "thyroid package",
        "ابي شيء للشعر",
    ]
    for text in samples:
        result = resolve_packages_query(text)
        print(f"INPUT: {text}")
        print(f"ROUTE: {result.get('route')}")
        print(f"MATCHED: {result.get('matched')}")
        print(f"META: {result.get('meta')}")
        print(f"ANSWER: {result.get('answer')}")
        print("-" * 72)
