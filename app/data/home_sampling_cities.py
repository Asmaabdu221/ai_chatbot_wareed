"""
Home-sampling (الزيارة المنزلية) service-area list + availability checker.

Single source of truth for the cities where Wareed offers home sample
collection. Used by the conversation flow to validate a city the customer
names after asking about home visits.
"""

from __future__ import annotations

# normalized-friendly key -> display name (Arabic)
HOME_SAMPLING_CITIES = {
    "الحوطه": "الحوطة",
    "الخرج": "الخرج",
    "الدمام": "الدمام",
    "الدوادمي": "الدوادمي",
    "الرياض": "الرياض",
    "الزلفي": "الزلفي",
    "السليل": "السليل",
    "الطائف": "الطائف",
    "القصيم": "القصيم",
    "المزاحميه": "المزاحمية",
    "جده": "جدة",
    "حائل": "حائل",
    "حفر الباطن": "حفر الباطن",
    "عفيف": "عفيف",
    "مكه المكرمه": "مكة المكرمة",
    "وادي الدواسر": "وادي الدواسر",
}

_MIN_TOKEN_LEN = 3


def _strip_article(s: str) -> str:
    """Drop a leading definite article for matching, keeping short words intact."""
    s = (s or "").strip()
    if s.startswith("ال") and len(s) > 4:  # leading "ال"
        return s[2:]
    return s


def check_city_availability(city_input: str) -> tuple[bool, str]:
    """Return (is_available, display_name_or_original).

    Matching strategy (most precise first), all on Arabic-normalized text:
      1. Exact match on the full name or its article-stripped form
         (so a query without the definite article still matches).
      2. Token-set intersection between the query and a city's words, so a
         single word or a short sentence ("انا في الرياض") still resolves,
         while distinct one-letter neighbours do NOT collide.
      3. Strict fuzzy match (token_sort_ratio) on the article-stripped forms
         as a last resort (so Khobar does NOT match Kharj).

    Returns the canonical display name when available, else the original input.
    """
    from app.utils.arabic_normalizer import normalize
    from rapidfuzz import fuzz

    norm_input = normalize((city_input or "").strip())
    if not norm_input:
        return False, city_input
    base_input = _strip_article(norm_input)
    input_tokens = {
        _strip_article(tok)
        for tok in norm_input.split()
        if len(_strip_article(tok)) >= _MIN_TOKEN_LEN
    }

    # Pre-compute normalized variants for each known city.
    candidates = []  # (norm_full, base_full, {city_tokens}, display)
    for key, display in HOME_SAMPLING_CITIES.items():
        nf = normalize(key)
        city_tokens = {
            _strip_article(tok)
            for tok in nf.split()
            if len(_strip_article(tok)) >= _MIN_TOKEN_LEN
        }
        candidates.append((nf, _strip_article(nf), city_tokens, display))

    # 1. Exact match (full or article-stripped).
    for nf, bf, _toks, display in candidates:
        if norm_input == nf or base_input == bf:
            return True, display

    # 2. Token-set intersection (handles single word and short sentences).
    if input_tokens:
        for _nf, _bf, city_tokens, display in candidates:
            if input_tokens & city_tokens:
                return True, display

    # 3. Strict fuzzy on article-stripped forms.
    best_score, best_display = 0, city_input
    for _nf, bf, _toks, display in candidates:
        score = fuzz.token_sort_ratio(base_input, bf)
        if score > best_score:
            best_score, best_display = score, display
    if best_score >= 88:
        return True, best_display

    return False, city_input
