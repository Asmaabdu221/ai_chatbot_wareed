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
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.runtime.entity_memory import load_entity_memory
from app.services.runtime.selection_state import load_selection_state, save_selection_state
from app.services.runtime.text_normalizer import normalize_arabic

PACKAGES_JSONL_PATH = Path("app/data/runtime/rag/packages_clean.jsonl")
logger = logging.getLogger(__name__)

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
    "وش يعني",
    "عرفني على",
    "what does it include",
    "what is included",
    "include",
    "includes",
    "details",
)

_INCLUSION_HINTS = (
    "وش تشمل",
    "ايش فيها",
    "كم تحليل فيها",
    "هل تحتوي على",
)

_ANALYTE_QUERY_HINTS = (
    "فيها",
    "تشمل",
    "هل تحتوي",
    "contains",
    "include",
    "includes",
)

_COMPARE_HINTS = ("الفرق بين", "قارن", "قارنة", "compare")
_ALTERNATIVE_HINTS = ("مشابه", "باقة ثانية", "بديل", "غيرها", "alternative", "similar")
_AMBIGUOUS_TERMS = ("الغدة", "الاطفال", "الأطفال", "الحساسية")

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

_SYMPTOM_GOAL_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("للشعر", ("للشعر", "الشعر", "تساقط", "hair", "alopecia")),
    ("للغدة", ("للغده", "للغدة", "الغده", "الغدة", "thyroid", "tsh", "هرمونات")),
    ("للسكر", ("للسكر", "السكر", "سكري", "diabetes", "glucose", "hba1c")),
    ("للقولون", ("للقولون", "القولون", "قولون", "digestive", "gastro", "ibs")),
)

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


def _parse_numeric_selection_value(text: str) -> int | None:
    value = _safe_str(text).translate(
        str.maketrans({"٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9"})
    )
    if not re.fullmatch(r"\d{1,2}", value):
        return None
    try:
        return int(value)
    except ValueError:
        return None


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


def _contains_boundary_phrase(query_norm: str, phrase: str) -> bool:
    phrase_norm = _norm(phrase)
    if not query_norm or not phrase_norm:
        return False
    if query_norm == phrase_norm:
        return True
    return f" {phrase_norm} " in f" {query_norm} "


def _detector_score(
    query_norm: str,
    *,
    hints: tuple[str, ...] | list[str],
    strong_keywords: tuple[str, ...] | list[str] = (),
    domain_phrases: tuple[str, ...] | list[str] = (),
    blockers: tuple[str, ...] | list[str] = (),
    ambiguity_penalty: bool = False,
) -> dict[str, float]:
    q_tokens = _tokenize(query_norm)
    q_set = _expand_synonyms(q_tokens)
    q_bigrams = _extract_bigrams(q_tokens)

    score = 0.0
    exact_hits = 0.0
    boundary_hits = 0.0
    overlap_hits = 0.0
    strong_hits = 0.0
    domain_hits = 0.0
    blocker_hits = 0.0
    ambiguity_hits = 0.0

    for hint in hints:
        hint_norm = _norm(hint)
        if not hint_norm:
            continue
        if query_norm == hint_norm:
            score += 3.0
            exact_hits += 1.0
        elif _contains_boundary_phrase(query_norm, hint_norm):
            score += 2.0
            boundary_hits += 1.0
        elif hint_norm in query_norm:
            score += 1.0

        hint_tokens = _tokenize(hint_norm)
        if hint_tokens:
            hint_set = _expand_synonyms(hint_tokens)
            overlap = len(q_set & hint_set)
            if overlap and overlap == len(hint_tokens):
                score += 1.25
                overlap_hits += 1.0
            elif overlap and len(hint_tokens) > 1:
                score += 0.5
                overlap_hits += 0.5

    for keyword in strong_keywords:
        keyword_norm = _norm(keyword)
        if not keyword_norm:
            continue
        if _contains_boundary_phrase(query_norm, keyword_norm) or keyword_norm in q_set:
            score += 1.5
            strong_hits += 1.0

    for phrase in domain_phrases:
        phrase_norm = _norm(phrase)
        if not phrase_norm:
            continue
        if _contains_boundary_phrase(query_norm, phrase_norm):
            score += 1.0
            domain_hits += 1.0
            continue
        phrase_tokens = _tokenize(phrase_norm)
        if len(phrase_tokens) == 2 and f"{phrase_tokens[0]} {phrase_tokens[1]}" in q_bigrams:
            score += 0.75
            domain_hits += 0.75

    for blocker in blockers:
        blocker_norm = _norm(blocker)
        if not blocker_norm:
            continue
        if _contains_boundary_phrase(query_norm, blocker_norm):
            score -= 2.0
            blocker_hits += 1.0

    if ambiguity_penalty and len(q_tokens) <= 2 and all(t in _GENERIC_LOW_SIGNAL for t in q_tokens):
        score -= 1.5
        ambiguity_hits += 1.0

    return {
        "score": score,
        "exact": exact_hits,
        "boundary": boundary_hits,
        "overlap": overlap_hits,
        "strong": strong_hits,
        "domain": domain_hits,
        "blockers": blocker_hits,
        "ambiguity_penalty": ambiguity_hits,
    }


def _detector_pick(
    detector_name: str,
    query_norm: str,
    scores: dict[str, float],
    *,
    min_score: float,
    legacy_match: bool,
) -> bool:
    score = float(scores.get("score", 0.0))
    fallback_reason = ""
    if score >= min_score:
        result = True
    else:
        result = legacy_match
        fallback_reason = "weak_or_ambiguous_score_legacy_substring"
    logger.debug(
        "packages_resolver.detector name=%s query=%r scores=%s result=%s fallback_reason=%s",
        detector_name,
        query_norm,
        scores,
        result,
        fallback_reason,
    )
    return result


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
    legacy = any(_norm(h) in query_norm for h in _PRICE_HINTS)
    scores = _detector_score(
        query_norm,
        hints=_PRICE_HINTS,
        strong_keywords=("سعر", "بكم", "price", "cost", "how much"),
        domain_phrases=("كم سعر", "how much"),
        blockers=("الفرق بين", "قارن"),
    )
    return _detector_pick("price", query_norm, scores, min_score=2.0, legacy_match=legacy)


def _is_general_query(query_norm: str) -> bool:
    legacy = any(_norm(h) in query_norm for h in _GENERAL_HINTS)
    scores = _detector_score(
        query_norm,
        hints=_GENERAL_HINTS,
        strong_keywords=("باقات", "packages", "البرامج"),
        domain_phrases=("available packages", "package list"),
        blockers=("كم سعر", "وش تشمل", "ايش تشمل", "الفرق بين", "بديل"),
        ambiguity_penalty=True,
    )
    return _detector_pick("general", query_norm, scores, min_score=2.0, legacy_match=legacy)


def _is_general_listing_query(query_norm: str) -> bool:
    legacy = any(_norm(h) in query_norm for h in _GENERAL_LISTING_HINTS)
    scores = _detector_score(
        query_norm,
        hints=_GENERAL_LISTING_HINTS,
        strong_keywords=("باقات", "available", "package list"),
        domain_phrases=("الباقات المتوفرة", "الباقات اللي عندكم", "available packages"),
        blockers=("كم سعر", "وش تشمل", "ايش تشمل", "الفرق بين"),
        ambiguity_penalty=True,
    )
    return _detector_pick("general_listing", query_norm, scores, min_score=2.0, legacy_match=legacy)


def _is_detail_query(query_norm: str) -> bool:
    legacy = any(_norm(h) in query_norm for h in _DETAIL_HINTS)
    scores = _detector_score(
        query_norm,
        hints=_DETAIL_HINTS,
        strong_keywords=("تفاصيل", "details", "include", "includes"),
        domain_phrases=("what is included", "what does it include"),
        blockers=("كم سعر", "الفرق بين"),
    )
    return _detector_pick("detail", query_norm, scores, min_score=2.0, legacy_match=legacy)


def _is_inclusion_query(query_norm: str) -> bool:
    legacy = any(_norm(h) in query_norm for h in _INCLUSION_HINTS)
    scores = _detector_score(
        query_norm,
        hints=_INCLUSION_HINTS,
        strong_keywords=("تشمل", "تحتوي", "contains", "include"),
        domain_phrases=("هل تحتوي على", "كم تحليل فيها"),
        blockers=("كم سعر",),
    )
    return _detector_pick("inclusion", query_norm, scores, min_score=1.75, legacy_match=legacy)


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
    legacy = any(_norm(k) in query_norm for k in keywords)
    scores = _detector_score(
        query_norm,
        hints=tuple(keywords),
        strong_keywords=("افضل", "أفضل", "احسن", "انسب", "تنصحني", "recommend", "recommended", "best"),
        domain_phrases=("best package", "افضل باقة", "احسن باقة"),
        blockers=("الفرق بين", "قارن"),
    )
    return _detector_pick("best_for", query_norm, scores, min_score=2.0, legacy_match=legacy)


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


def _detect_audience_terms(query_norm: str) -> tuple[str, tuple[str, ...]] | None:
    audience_map: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("للنساء", ("للنساء", "نساء", "مراه", "مرأة", "امرأة", "women", "woman", "female")),
        ("للرجال", ("للرجال", "رجال", "men", "male", "man")),
        ("للأطفال", ("للاطفال", "للأطفال", "اطفال", "أطفال", "طفل", "children", "child", "kids", "pediatric")),
    )
    for label, terms in audience_map:
        if any(_norm(t) in query_norm for t in terms):
            return (label, terms)
    return None


def _detect_symptom_goal_query(query_norm: str) -> tuple[str, tuple[str, ...]] | None:
    for label, terms in _SYMPTOM_GOAL_HINTS:
        if any(_norm(t) in query_norm for t in terms):
            return (label, terms)
    return None


def _extract_analyte_terms(query: str) -> list[str]:
    query_norm = _norm(query)
    if not query_norm:
        return []
    tokens = _tokenize(query_norm)
    excluded = {"فيها", "تشمل", "يشمل", "تحتوي", "هل", "على", "package", "باقه", "باقة"}
    terms: list[str] = []
    for t in tokens:
        if t in excluded:
            continue
        if len(t) < 2:
            continue
        terms.append(t)
    # Keep stable order, unique.
    out: list[str] = []
    seen: set[str] = set()
    for t in terms:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _is_analyte_query(query_norm: str, analyte_terms: list[str]) -> bool:
    if not analyte_terms:
        return False
    legacy = any(_norm(h) in query_norm for h in _ANALYTE_QUERY_HINTS)
    scores = _detector_score(
        query_norm,
        hints=_ANALYTE_QUERY_HINTS,
        strong_keywords=("فيها", "تشمل", "contains", "include"),
        domain_phrases=("هل تحتوي",),
        blockers=("الفرق بين", "بديل"),
    )
    # Slight boost for analyte-rich queries while keeping conservative thresholding.
    if len(analyte_terms) >= 2:
        scores["score"] = float(scores.get("score", 0.0)) + 0.5
    return _detector_pick("analyte", query_norm, scores, min_score=1.75, legacy_match=legacy)


def _is_compare_query(query_norm: str) -> bool:
    legacy = any(_norm(h) in query_norm for h in _COMPARE_HINTS)
    scores = _detector_score(
        query_norm,
        hints=_COMPARE_HINTS,
        strong_keywords=("الفرق", "بين", "compare"),
        domain_phrases=("الفرق بين",),
        blockers=("بديل", "مشابه"),
    )
    return _detector_pick("compare", query_norm, scores, min_score=2.0, legacy_match=legacy)


def _is_alternatives_query(query_norm: str) -> bool:
    legacy = any(_norm(h) in query_norm for h in _ALTERNATIVE_HINTS)
    scores = _detector_score(
        query_norm,
        hints=_ALTERNATIVE_HINTS,
        strong_keywords=("بديل", "مشابه", "similar", "alternative"),
        domain_phrases=("باقة ثانية",),
        blockers=("الفرق بين", "قارن"),
    )
    return _detector_pick("alternatives", query_norm, scores, min_score=1.75, legacy_match=legacy)


def _is_ambiguous_package_query(query_norm: str) -> bool:
    legacy = any(_norm(h) in query_norm for h in _AMBIGUOUS_TERMS)
    scores = _detector_score(
        query_norm,
        hints=_AMBIGUOUS_TERMS,
        strong_keywords=_AMBIGUOUS_TERMS,
        domain_phrases=(),
        blockers=("كم سعر", "وش تشمل", "ايش تشمل"),
        ambiguity_penalty=True,
    )
    return _detector_pick("ambiguous_package", query_norm, scores, min_score=1.5, legacy_match=legacy)


def _is_category_like_query(query_norm: str, detected_category: str) -> bool:
    if not query_norm:
        return False
    legacy_detected = bool(detected_category and _norm(detected_category) in query_norm)
    if legacy_detected:
        logger.debug(
            "packages_resolver.detector name=%s query=%r scores=%s result=%s fallback_reason=%s",
            "category_like",
            query_norm,
            {"score": 3.0, "legacy_detected_category": 1.0},
            True,
            "",
        )
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
    legacy = any(_norm(t) in query_norm for t in category_tokens)
    scores = _detector_score(
        query_norm,
        hints=category_tokens,
        strong_keywords=("الفئة", "تصنيف", "جينية"),
        domain_phrases=("نوع الباقات", "باقات رمضان", "تحاليل جينية"),
        blockers=("كم سعر", "وش تشمل"),
    )
    return _detector_pick("category_like", query_norm, scores, min_score=1.75, legacy_match=legacy)


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


def _extract_specific_package_candidate(query: str) -> str | None:
    """Strip lead-in wording and keep likely package-name phrase only."""
    q = _norm(query)
    if not q:
        return None
    if _is_general_listing_query(q) or _is_general_query(q):
        return None
    has_package_like_token = any(token in q for token in ("باقة", "باقه", "باقات", "package", "packages"))
    if not has_package_like_token:
        return None
    cleanup_prefixes = (
        "ايش هي",
        "وش هي",
        "عرفني على",
        "ممكن",
        "ابغى",
        "ابي",
        "عن",
        "باقة",
        "باقه",
        "package",
    )
    candidate = q
    changed = True
    while changed and candidate:
        changed = False
        for prefix in cleanup_prefixes:
            p = _norm(prefix)
            if p and candidate.startswith(p):
                candidate = candidate[len(p):].strip()
                changed = True
    cleaned = re.sub(r"\s+", " ", candidate).strip()
    return cleaned or None


def _find_specific_package_by_name_pass(query: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidate = _extract_specific_package_candidate(query)
    if not candidate:
        return None

    best: dict[str, Any] | None = None
    best_score = -1.0
    cand_tokens = set(_tokenize(candidate))
    if not cand_tokens:
        return None

    for row in records:
        name = _safe_str(row.get("package_name"))
        name_norm = _safe_str(row.get("package_name_norm")) or _norm(name)
        if not name_norm:
            continue
        if candidate == name_norm:
            return row
        if candidate in name_norm or name_norm in candidate:
            return row

        name_tokens = set(_tokenize(name_norm))
        overlap = cand_tokens.intersection(name_tokens)
        score = float(len(overlap))
        if cand_tokens and overlap:
            score += len(overlap) / max(1.0, float(len(cand_tokens)))
        if score > best_score:
            best_score = score
            best = row

    if best is None:
        return None
    # Require near-exact lexical overlap for this direct-name pass.
    if best_score < 2.0:
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
    if tokens and tokens[0].startswith("ل") and len(tokens[0]) > 1:
        tokens[0] = tokens[0][1:]
    clean_topic = " ".join(tokens).strip()
    return clean_topic


def _format_best_for_options(query: str, rows: list[dict[str, Any]]) -> str:
    topic = _extract_best_for_topic(query)
    if topic:
        lines = [f"أفضل الباقات ل{topic}:"]
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
        "فصل",
        "فصل لي",
        "فصل اكثر",
        "وضح",
        "طيب وضح",
        "التفاصيل",
        "وش فيها",
        "ايش فيها",
        "ايش تشمل",
        "وش تشمل",
        "ايش التحاليل",
        "عطيني التفاصيل",
        "ابغى التفاصيل",
    )
    return any(_norm(h) == query_norm or _norm(h) in query_norm for h in hints)


def _is_best_for_price_followup_query(query_norm: str) -> bool:
    hints = ("السعر", "سعر", "سعرها", "بكم", "كم سعرها", "كم سعره")
    return any(_norm(h) == query_norm or _norm(h) in query_norm for h in hints)


def _is_package_details_followup_query(query_norm: str) -> bool:
    hints = (
        "نعم",
        "ايوا",
        "ايوه",
        "طيب",
        "تمام",
        "اوكي",
        "ok",
        "كمل",
        "شرح",
        "اشرح",
        "التفاصيل",
        "تفاصيل",
        "وش فيها",
        "ايش فيها",
        "وش تشمل",
        "ايش تشمل",
    )
    return any(_norm(h) == query_norm or _norm(h) in query_norm for h in hints)


def _is_package_price_followup_query(query_norm: str) -> bool:
    hints = ("السعر", "سعر", "سعرها", "بكم", "كم سعرها", "كم سعره")
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


def _resolve_package_numeric_selection(
    text: str,
    *,
    records: list[dict[str, Any]],
    conversation_id: UUID | None,
) -> dict[str, Any] | None:
    if conversation_id is None:
        return None
    number = _parse_numeric_selection_value(text)
    if number is None:
        return None
    state = load_selection_state(conversation_id)
    if _safe_str(state.get("last_selection_type")) != "package":
        return None
    options = list(state.get("last_options") or [])
    index = number - 1
    if index < 0 or index >= len(options):
        return None
    selected = options[index] if isinstance(options[index], dict) else {}
    payload = selected.get("selection_payload") or {}
    package_name = _safe_str(payload.get("package_name")) or _safe_str(selected.get("label"))
    if not package_name:
        return None
    matched = _find_package_by_label(package_name, records)
    if matched is None:
        matched = _find_specific_package(f"باقة {package_name}", records)
    if matched is None:
        return None
    return {
        "matched": True,
        "answer": _format_best_for_selected_preview(matched),
        "route": "packages_selected",
        "meta": {
            "query_type": "package_selection_query",
            "matched_package_id": _safe_str(matched.get("id")),
            "matched_package_name": _safe_str(matched.get("package_name")),
            "selection_number": number,
        },
    }


def _format_best_for_selected_preview(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    short_desc = _safe_str(record.get("description_short"))
    name_norm = _norm(name)
    def _is_meaningful_description(text: str) -> bool:
        t = _safe_str(text)
        if not t:
            return False
        t_norm = _norm(t)
        if not t_norm:
            return False
        if t_norm == name_norm:
            return False
        if t_norm in {f"{name_norm}:", f"{name_norm} -", f"{name_norm} –", f"{name_norm} —"}:
            return False
        return True

    if not _is_meaningful_description(short_desc):
        short_desc = ""
    if not short_desc:
        full_desc = _safe_str(record.get("description_full"))
        if full_desc:
            for part in re.split(r"[\.،\n]+", full_desc):
                candidate = _safe_str(part)
                if _is_meaningful_description(candidate):
                    short_desc = candidate
                    break
            if not short_desc:
                clipped = _safe_str(full_desc[:150])
                if _is_meaningful_description(clipped):
                    short_desc = clipped
    if not short_desc:
        short_desc = "هذه الباقة تساعد في تقييم الحالة بشكل شامل."
    if short_desc:
        short_desc = re.sub(rf"^\s*{re.escape(name)}\s*[:\-–—]?\s*", "", short_desc, flags=re.IGNORECASE).strip()
    lines = [name]
    if short_desc:
        lines.extend(["", short_desc])
    lines.extend(["", "إذا حاب أشرح لك أكثر عن الباقة أو أوضح لك التحاليل التي تشملها، أقدر أفصلها لك."])
    return "\n".join(lines)


def _format_best_for_long_details(record: dict[str, Any]) -> str:
    full_desc = _safe_str(record.get("description_full"))
    short_desc = _safe_str(record.get("description_short"))
    body = full_desc if full_desc and _norm(full_desc) != _norm(short_desc) else short_desc
    if not body:
        body = "ما عندي تفاصيل إضافية واضحة في البيانات الحالية."
    lines = ["تمام.", "", body, "", "إذا حاب بعدها أعرفك على السعر أو أقارنها لك مع باقة ثانية، أقدر أوضح لك."]
    return "\n".join(lines)


def _format_best_for_price(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    currency = _safe_str(record.get("currency") or "ريال")
    price = record.get("price_number")
    if isinstance(price, (int, float)):
        base = f"سعر {name}: {price:g} {currency}."
    else:
        base = _PRICE_NOT_AVAILABLE
    lines = [base, "", "إذا حاب، أقدر أقارنها لك مع باقة ثانية أو أرشح لك خيار أقرب لاحتياجك."]
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
        lines.append(f"{idx}) {name}")

    if len(rows) > limit:
        lines.append(f"... يوجد أيضًا {len(rows) - limit} باقات إضافية.")
    lines.append("اكتب اسم الباقة أو رقمها إذا حاب أعرض لك التفاصيل.")
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


def _format_package_preview(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    short_desc = _safe_str(record.get("description_short"))
    if not short_desc:
        full_desc = _safe_str(record.get("description_full"))
        if full_desc:
            parts = re.split(r"[\.،\n]+", full_desc)
            for part in parts:
                candidate = _safe_str(part)
                if candidate:
                    short_desc = candidate
                    break
    lines = [name]
    if short_desc:
        lines.extend(["", short_desc])
    return "\n".join(lines)


def _format_package_full_details(record: dict[str, Any]) -> str:
    full_desc = _safe_str(record.get("description_full"))
    if full_desc:
        return full_desc
    short_desc = _safe_str(record.get("description_short"))
    if short_desc:
        return short_desc
    return "تفاصيل هذه الباقة غير متوفرة حالياً."


def _format_package_inclusions(record: dict[str, Any], *, query_norm: str = "") -> str:
    name = _safe_str(record.get("package_name"))
    full_desc = _safe_str(record.get("description_full"))
    short_desc = _safe_str(record.get("description_short"))
    included_count = record.get("included_count")

    lines: list[str] = [name]

    count_value: int | None = None
    if isinstance(included_count, int):
        count_value = included_count
    elif isinstance(included_count, float):
        count_value = int(included_count)
    else:
        txt = _safe_str(included_count)
        if txt.isdigit():
            count_value = int(txt)
    if "كم تحليل" in query_norm and count_value is not None:
        lines.extend(["", f"عدد التحاليل في الباقة: {count_value} تحليل."])

    candidates: list[str] = []
    for part in re.split(r"[\n\r]+", full_desc):
        line = _safe_str(part)
        if not line:
            continue
        if re.match(r"^\d+\s*[\.\)-]\s*", line):
            candidates.append(line)
            continue
        if any(token in line for token in ("تشمل", "تحاليل", "تحليل", "contains", "include")):
            candidates.append(line)

    if not candidates and full_desc:
        candidates = [s.strip() for s in re.split(r"[\.،\n]+", full_desc) if _safe_str(s)][:8]
    if not candidates and short_desc:
        candidates = [short_desc]

    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        key = _norm(item)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    if deduped:
        lines.append("")
        lines.append("تشمل الباقة:")
        for item in deduped[:10]:
            if re.match(r"^\d+\s*[\.\)-]\s*", item):
                lines.append(item)
            else:
                lines.append(f"- {item}")
    elif len(lines) == 1:
        lines.extend(["", "تفاصيل التحاليل المشمولة غير واضحة حالياً في البيانات."])

    return "\n".join(lines)


def _format_package_price(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    currency = _safe_str(record.get("currency") or "ريال")
    price = record.get("price_number")
    if isinstance(price, (int, float)):
        return f"سعر {name}: {price:g} {currency}."
    return _PRICE_NOT_AVAILABLE


def _format_audience_packages(
    audience_label: str,
    rows: list[dict[str, Any]],
    *,
    conversation_id: UUID | None = None,
    limit: int = 20,
) -> str:
    if not rows:
        return f"ما لقيت باقات {audience_label} حالياً."
    _save_package_options(conversation_id, rows[:limit], query_type="package_audience")
    lines = [f"الباقات المناسبة {audience_label}:"]
    for idx, r in enumerate(rows[:limit], start=1):
        lines.append(f"{idx}) {_safe_str(r.get('package_name'))}")
    if len(rows) > limit:
        lines.append(f"... يوجد أيضًا {len(rows) - limit} باقات إضافية.")
    lines.append("اكتب اسم الباقة أو رقمها إذا تحب أعرض لك التفاصيل.")
    return "\n".join(lines)


def _format_goal_packages(
    goal_label: str,
    rows: list[dict[str, Any]],
    *,
    conversation_id: UUID | None = None,
    limit: int = 20,
) -> str:
    if not rows:
        return f"ما لقيت باقات {goal_label} حالياً."
    _save_package_options(conversation_id, rows[:limit], query_type="package_goal")
    lines = [f"الباقات المناسبة {goal_label}:"]
    for idx, r in enumerate(rows[:limit], start=1):
        lines.append(f"{idx}) {_safe_str(r.get('package_name'))}")
    if len(rows) > limit:
        lines.append(f"... يوجد أيضًا {len(rows) - limit} باقات إضافية.")
    lines.append("اكتب اسم الباقة أو رقمها إذا تحب أعرض لك التفاصيل.")
    return "\n".join(lines)


def _find_packages_by_analyte(records: list[dict[str, Any]], analyte_terms: list[str]) -> list[dict[str, Any]]:
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in records:
        desc_blob = " ".join([
            _safe_str(row.get("description_full")),
            _safe_str(row.get("description_short")),
        ])
        desc_norm = _norm(desc_blob)
        if not desc_norm:
            continue
        hit_count = 0
        for term in analyte_terms:
            t = _norm(term)
            if t and t in desc_norm:
                hit_count += 1
        if hit_count > 0:
            scored.append((hit_count, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored]


def _format_packages_by_analyte(
    analyte_terms: list[str],
    rows: list[dict[str, Any]],
    *,
    conversation_id: UUID | None = None,
    limit: int = 20,
) -> str:
    term_text = " / ".join(analyte_terms[:3])
    if not rows:
        return f"ما لقيت باقات تشمل {term_text} حالياً."
    _save_package_options(conversation_id, rows[:limit], query_type="package_analyte")
    lines = [f"الباقات التي تشمل {term_text}:"]
    for idx, r in enumerate(rows[:limit], start=1):
        lines.append(f"{idx}) {_safe_str(r.get('package_name'))}")
    if len(rows) > limit:
        lines.append(f"... يوجد أيضًا {len(rows) - limit} باقات إضافية.")
    lines.append("اكتب اسم الباقة أو رقمها إذا تحب أعرض لك التفاصيل.")
    return "\n".join(lines)


def _extract_compare_targets(query: str) -> tuple[str, str] | None:
    q = _norm(query)
    if not q:
        return None
    if "الفرق بين" in q:
        tail = q.split("الفرق بين", 1)[1].strip()
        for sep in (" و ", " و", "و ", "/", "-", "vs"):
            if sep in tail:
                left, right = tail.split(sep, 1)
                left = _safe_str(left)
                right = _safe_str(right)
                if left and right:
                    return (left, right)
    if "قارن" in q:
        tail = q.split("قارن", 1)[1].strip()
        for sep in (" و ", " و", "و ", "/", "-", "vs"):
            if sep in tail:
                left, right = tail.split(sep, 1)
                left = _safe_str(left)
                right = _safe_str(right)
                if left and right:
                    return (left, right)
    return None


def _find_top_scored_packages(query: str, records: list[dict[str, Any]], *, min_score: float = 3.0, limit: int = 5) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in records:
        score = _score_package_match(query, row)
        if score >= min_score:
            scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, row in scored:
        identity = _safe_str(row.get("id")) or _norm(_safe_str(row.get("package_name")))
        if not identity or identity in seen:
            continue
        seen.add(identity)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _format_package_comparison(left: dict[str, Any], right: dict[str, Any]) -> str:
    def _price_text(row: dict[str, Any]) -> str:
        price = row.get("price_number")
        currency = _safe_str(row.get("currency") or "ريال")
        if isinstance(price, (int, float)):
            return f"{price:g} {currency}"
        return "غير متوفر"

    l_name = _safe_str(left.get("package_name"))
    r_name = _safe_str(right.get("package_name"))
    l_short = _safe_str(left.get("description_short")) or _safe_str(left.get("description_full"))
    r_short = _safe_str(right.get("description_short")) or _safe_str(right.get("description_full"))
    lines = [
        f"مقارنة بين {l_name} و {r_name}:",
        "",
        f"1) {l_name}",
        f"- السعر: {_price_text(left)}",
        f"- الوصف المختصر: {l_short[:220] if l_short else 'غير متوفر'}",
        "",
        f"2) {r_name}",
        f"- السعر: {_price_text(right)}",
        f"- الوصف المختصر: {r_short[:220] if r_short else 'غير متوفر'}",
    ]
    return "\n".join(lines)


def _format_alternative_packages(base_name: str, rows: list[dict[str, Any]], *, limit: int = 3) -> str:
    lines = [f"باقات مشابهة لـ{base_name}:"]
    for idx, row in enumerate(rows[:limit], start=1):
        lines.append(f"{idx}) {_safe_str(row.get('package_name'))}")
    lines.append("اكتب رقم الباقة أو اسمها إذا حاب تفاصيل أكثر.")
    return "\n".join(lines)


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

    # Highest priority: numbered package selection from conversation state.
    numeric_selection_result = _resolve_package_numeric_selection(
        query,
        records=records,
        conversation_id=conversation_id,
    )
    if numeric_selection_result is not None:
        return numeric_selection_result

    best_for_context = False
    remembered_package_label = ""
    remembered_package_record: dict[str, Any] | None = None
    if conversation_id is not None:
        state = load_selection_state(conversation_id)
        best_for_context = _safe_str(state.get("query_type")) == "package_best_for"
        memory = load_entity_memory(conversation_id)
        if _safe_str(memory.get("last_intent")) == "package" and bool(memory.get("last_intent_has_entity")):
            remembered_package_label = _safe_str((memory.get("last_package") or {}).get("label"))
            if remembered_package_label:
                remembered_package_record = _find_package_by_label(remembered_package_label, records)

    explicit_package_match_for_override = _find_specific_package_by_name_pass(query, records)
    if explicit_package_match_for_override is None:
        explicit_package_match_for_override = _find_specific_package(query, records)
    has_explicit_package_in_query = explicit_package_match_for_override is not None

    if remembered_package_record is not None and not has_explicit_package_in_query:
        remembered_id = _safe_str(remembered_package_record.get("id"))
        if _is_package_price_followup_query(query_norm):
            if best_for_context:
                return {
                    "matched": True,
                    "answer": _format_best_for_price(remembered_package_record),
                    "route": "packages_best_for_price",
                    "meta": {
                        "query_type": "package_best_for_query",
                        "matched_package_id": remembered_id,
                        "matched_package_name": _safe_str(remembered_package_record.get("package_name")),
                    },
                }
            return {
                "matched": True,
                "answer": _format_package_price(remembered_package_record),
                "route": "packages_price",
                "meta": {
                    "query_type": "package_price_query",
                    "matched_package_id": remembered_id,
                    "matched_package_name": _safe_str(remembered_package_record.get("package_name")),
                    "category": _safe_str(remembered_package_record.get("main_category")),
                    "price_available": isinstance(remembered_package_record.get("price_number"), (int, float)),
                },
            }
        if _is_package_details_followup_query(query_norm):
            if best_for_context:
                return {
                    "matched": True,
                    "answer": _format_best_for_long_details(remembered_package_record),
                    "route": "packages_best_for_details",
                    "meta": {"query_type": "package_best_for_query"},
                }
            return {
                "matched": True,
                "answer": _format_package_full_details(remembered_package_record),
                "route": "packages_specific_details",
                "meta": {
                    "query_type": "package_specific_details",
                    "matched_package_id": remembered_id,
                    "matched_package_name": _safe_str(remembered_package_record.get("package_name")),
                    "category": _safe_str(remembered_package_record.get("main_category")),
                },
            }

    if best_for_context and remembered_package_label and not has_explicit_package_in_query:
        remembered_record = remembered_package_record
        if remembered_record is not None:
            strong_best_for_followup = {"نعم", "ايوا", "ايوه", "تمام", "اوكي", "ok"}
            if query_norm in {_norm(v) for v in strong_best_for_followup}:
                return {
                    "matched": True,
                    "answer": _format_best_for_long_details(remembered_record),
                    "route": "packages_best_for_details",
                    "meta": {"query_type": "package_best_for_query"},
                }
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
    compare_query = _is_compare_query(query_norm)
    alternatives_query = _is_alternatives_query(query_norm)
    ambiguous_query = _is_ambiguous_package_query(query_norm)
    price_query = _is_price_query(query_norm)
    inclusion_query = _is_inclusion_query(query_norm)
    detail_query = _is_detail_query(query_norm)
    audience_terms = _detect_audience_terms(query_norm)
    symptom_goal_terms = _detect_symptom_goal_query(query_norm)
    analyte_terms = _extract_analyte_terms(query)
    analyte_query = _is_analyte_query(query_norm, analyte_terms)

    # General list must win before specific/best-for/ambiguity.
    if general_listing_like:
        return {
            "matched": True,
            "answer": _format_general_overview(records, conversation_id),
            "route": "packages_general",
            "meta": {
                "query_type": "package_general",
                "categories_count": len({_safe_str(r.get("main_category")) for r in records if _safe_str(r.get("main_category"))}),
            },
        }
    specific_match = _find_specific_package(query, records)
    direct_name_match = _find_specific_package_by_name_pass(query, records)
    if direct_name_match is not None:
        specific_match = direct_name_match
    ambiguous_candidates = _find_ambiguous_package_candidates(query, records)
    has_package_keyword = any(k in query_norm for k in ("باقة", "باقه", "package"))
    strong_specific_like = specific_match is not None and (
        has_package_keyword
        or detail_query
        or inclusion_query
        or price_query
        or direct_name_match is not None
    )

    # Compare intent has highest priority in package resolver.
    if compare_query:
        compare_targets = _extract_compare_targets(query)
        left_match: dict[str, Any] | None = None
        right_match: dict[str, Any] | None = None

        if compare_targets:
            left_rows = _find_top_scored_packages(compare_targets[0], records, min_score=3.0, limit=1)
            right_rows = _find_top_scored_packages(compare_targets[1], records, min_score=3.0, limit=1)
            left_match = left_rows[0] if left_rows else None
            right_match = right_rows[0] if right_rows else None
        elif strong_specific_like and specific_match is not None:
            left_match = specific_match

        if (
            left_match is not None
            and right_match is not None
            and _safe_str(left_match.get("id")) != _safe_str(right_match.get("id"))
        ):
            return {
                "matched": True,
                "answer": _format_package_comparison(left_match, right_match),
                "route": "packages_compare",
                "meta": {
                    "query_type": "package_compare_query",
                    "left_package": _safe_str(left_match.get("package_name")),
                    "right_package": _safe_str(right_match.get("package_name")),
                },
            }

        if left_match is not None and right_match is None:
            return {
                "matched": True,
                "answer": (
                    f"حددت الباقة الأولى: {_safe_str(left_match.get('package_name'))}.\n"
                    "اكتب اسم الباقة الثانية عشان أقارن بينهم."
                ),
                "route": "packages_compare",
                "meta": {
                    "query_type": "package_compare_query",
                    "left_package": _safe_str(left_match.get("package_name")),
                    "right_package": "",
                    "reason": "second_package_missing",
                },
            }

        return {
            "matched": True,
            "answer": "للمقارنة اكتب اسم باقتين بوضوح، مثال: قارن باقة الغدة وباقة السكر.",
            "route": "packages_compare",
            "meta": {
                "query_type": "package_compare_query",
                "left_package": "",
                "right_package": "",
                "reason": "insufficient_compare_targets",
            },
        }

    if audience_terms and not price_query and not strong_specific_like and not compare_query:
        audience_label, terms = audience_terms
        filtered_rows: list[dict[str, Any]] = []
        for row in records:
            blob = " ".join([
                _safe_str(row.get("package_name")),
                _safe_str(row.get("description_short")),
                _safe_str(row.get("description_full")),
            ])
            blob_norm = _norm(blob)
            if any(_norm(t) in blob_norm for t in terms):
                filtered_rows.append(row)
        if filtered_rows:
            return {
                "matched": True,
                "answer": _format_audience_packages(audience_label, filtered_rows, conversation_id=conversation_id),
                "route": "packages_audience",
                "meta": {
                    "query_type": "package_audience_query",
                    "audience": audience_label,
                    "results_count": len(filtered_rows),
                },
            }

    if symptom_goal_terms and not price_query and not strong_specific_like and not compare_query:
        goal_label, terms = symptom_goal_terms
        filtered_rows: list[dict[str, Any]] = []
        for row in records:
            blob = " ".join([
                _safe_str(row.get("description_full")),
                _safe_str(row.get("description_short")),
                _safe_str(row.get("package_name")),
            ])
            blob_norm = _norm(blob)
            if any(_norm(t) in blob_norm for t in terms):
                filtered_rows.append(row)
        if filtered_rows:
            return {
                "matched": True,
                "answer": _format_goal_packages(goal_label, filtered_rows, conversation_id=conversation_id),
                "route": "packages_goal",
                "meta": {
                    "query_type": "package_goal_query",
                    "goal": goal_label,
                    "results_count": len(filtered_rows),
                },
            }

    # Strong specific package pass should win before best-for/ambiguity flows.
    if strong_specific_like and specific_match is not None and not compare_query and not alternatives_query:
        package_id = _safe_str(specific_match.get("id"))
        if price_query:
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
        if inclusion_query:
            return {
                "matched": True,
                "answer": _format_package_inclusions(specific_match, query_norm=query_norm),
                "route": "packages_inclusions",
                "meta": {
                    "query_type": "package_inclusion_query",
                    "matched_package_id": package_id,
                    "matched_package_name": _safe_str(specific_match.get("package_name")),
                    "category": _safe_str(specific_match.get("main_category")),
                },
            }
        if detail_query:
            return {
                "matched": True,
                "answer": _format_package_full_details(specific_match),
                "route": "packages_specific_details",
                "meta": {
                    "query_type": "package_specific_details",
                    "matched_package_id": package_id,
                    "matched_package_name": _safe_str(specific_match.get("package_name")),
                    "category": _safe_str(specific_match.get("main_category")),
                },
            }
        if best_for_context:
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
        return {
            "matched": True,
            "answer": _format_package_preview(specific_match),
            "route": "packages_specific",
            "meta": {
                "query_type": "package_specific",
                "matched_package_id": package_id,
                "matched_package_name": _safe_str(specific_match.get("package_name")),
                "category": _safe_str(specific_match.get("main_category")),
            },
        }

    if best_for_query and not strong_specific_like:
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
                if len(unique_top) >= 3:
                    break

            _save_package_options(conversation_id, unique_top, query_type="package_best_for")

            return {
                "matched": True,
                "answer": _format_best_for_options(query, unique_top),
                "route": "packages_best_for",
                "meta": {"query_type": "package_best_for_query"},
            }

    if ambiguous_query and not price_query and not detail_query and not inclusion_query and not compare_query:
        options = _find_top_scored_packages(query, records, min_score=3.0, limit=5)
        if len(options) >= 2:
            _save_package_options(conversation_id, options, query_type="package_ambiguity")
            return {
                "matched": True,
                "answer": _format_ambiguous_package_options(options),
                "route": "packages_ambiguous",
                "meta": {
                    "query_type": "package_ambiguity",
                    "candidates_count": len(options),
                },
            }

    if analyte_query:
        analyte_rows = _find_packages_by_analyte(records, analyte_terms)
        if analyte_rows:
            return {
                "matched": True,
                "answer": _format_packages_by_analyte(analyte_terms, analyte_rows, conversation_id=conversation_id),
                "route": "packages_by_analyte",
                "meta": {
                    "query_type": "package_analyte_query",
                    "analyte_terms": analyte_terms[:5],
                    "results_count": len(analyte_rows),
                },
            }

    if alternatives_query:
        base = specific_match or remembered_package_record
        if base is not None:
            base_name = _safe_str(base.get("package_name"))
            candidates = _find_top_scored_packages(base_name, records, min_score=2.5, limit=6)
            alternatives = [r for r in candidates if _safe_str(r.get("id")) != _safe_str(base.get("id"))]
            if alternatives:
                _save_package_options(conversation_id, alternatives[:5], query_type="package_alternatives")
                return {
                    "matched": True,
                    "answer": _format_alternative_packages(base_name, alternatives, limit=5),
                    "route": "packages_alternatives",
                    "meta": {
                        "query_type": "package_alternatives_query",
                        "base_package": base_name,
                        "results_count": len(alternatives[:5]),
                    },
                }

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

    if inclusion_query and specific_match is not None:
        package_id = _safe_str(specific_match.get("id"))
        return {
            "matched": True,
            "answer": _format_package_inclusions(specific_match, query_norm=query_norm),
            "route": "packages_inclusions",
            "meta": {
                "query_type": "package_inclusion_query",
                "matched_package_id": package_id,
                "matched_package_name": _safe_str(specific_match.get("package_name")),
                "category": _safe_str(specific_match.get("main_category")),
            },
        }

    if price_query and remembered_package_record is not None:
        remembered_id = _safe_str(remembered_package_record.get("id"))
        return {
            "matched": True,
            "answer": _format_package_price(remembered_package_record),
            "route": "packages_price",
            "meta": {
                "query_type": "package_price_query",
                "matched_package_id": remembered_id,
                "matched_package_name": _safe_str(remembered_package_record.get("package_name")),
                "category": _safe_str(remembered_package_record.get("main_category")),
                "price_available": isinstance(remembered_package_record.get("price_number"), (int, float)),
            },
        }

    if inclusion_query and remembered_package_record is not None:
        remembered_id = _safe_str(remembered_package_record.get("id"))
        return {
            "matched": True,
            "answer": _format_package_inclusions(remembered_package_record, query_norm=query_norm),
            "route": "packages_inclusions",
            "meta": {
                "query_type": "package_inclusion_query",
                "matched_package_id": remembered_id,
                "matched_package_name": _safe_str(remembered_package_record.get("package_name")),
                "category": _safe_str(remembered_package_record.get("main_category")),
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
        if detail_query:
            return {
                "matched": True,
                "answer": _format_package_full_details(specific_match),
                "route": "packages_specific_details",
                "meta": {
                    "query_type": "package_specific_details",
                    "matched_package_id": package_id,
                    "matched_package_name": _safe_str(specific_match.get("package_name")),
                    "category": _safe_str(specific_match.get("main_category")),
                },
            }
        return {
            "matched": True,
            "answer": _format_package_preview(specific_match),
            "route": "packages_specific",
            "meta": {
                "query_type": "package_specific",
                "matched_package_id": package_id,
                "matched_package_name": _safe_str(specific_match.get("package_name")),
                "category": _safe_str(specific_match.get("main_category")),
            },
        }

    if detail_query and remembered_package_record is not None:
        remembered_id = _safe_str(remembered_package_record.get("id"))
        return {
            "matched": True,
            "answer": _format_package_full_details(remembered_package_record),
            "route": "packages_specific_details",
            "meta": {
                "query_type": "package_specific_details",
                "matched_package_id": remembered_id,
                "matched_package_name": _safe_str(remembered_package_record.get("package_name")),
                "category": _safe_str(remembered_package_record.get("main_category")),
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
