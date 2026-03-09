from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("app/data/runtime")

TESTS_CLEAN_PATH = ROOT / "rag" / "tests_clean.jsonl"
TESTS_CHUNKS_PATH = ROOT / "rag" / "tests_chunks.jsonl"
PRICES_INDEX_PATH = ROOT / "lookup" / "tests_price_index.json"
FAQ_INDEX_PATH = ROOT / "lookup" / "faq_index.json"
BRANCHES_CLEAN_PATH = ROOT / "rag" / "branches_clean.jsonl"
PACKAGES_CLEAN_PATH = ROOT / "rag" / "packages_clean_v3.jsonl"

SYNONYMS_OUT_PATH = ROOT / "synonyms" / "synonyms_ar.json"
QA_OUT_PATH = ROOT / "reports" / "synonyms_qa.json"

DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
PUNCT_RE = re.compile(r"[^\w\s\u0600-\u06FF]")
WS_RE = re.compile(r"\s+")
PARENS_RE = re.compile(r"[()\[\]{}]")

GENERIC_BAD = {
    "test",
    "analysis",
    "lab",
    "blood",
    "serum",
    "package",
    "offer",
}

GENERIC_RISKY_SINGLE = {
    # English broad medical fragments
    "glucose",
    "blood",
    "level",
    "test",
    "analysis",
    "lab",
    "serum",
    # Arabic broad medical fragments
    "سكر",
    "دم",
    "تحليل",
    "فحص",
    "اختبار",
    "مستوى",
}

AR_STOP = {
    "ØªØ­Ù„ÙŠÙ„",
    "ØªØ­Ø§Ù„ÙŠÙ„",
    "ÙØ­Øµ",
    "Ø§Ø®ØªØ¨Ø§Ø±",
    "Ø§Ù„",
    "ÙÙŠ",
    "Ù…Ù†",
    "Ø¹Ù„Ù‰",
    "Ø§Ù„Ù‰",
    "Ø§Ù„Ù‰",
    "Ø¹Ù†",
    "Ù…Ø¹",
    "Ø§Ùˆ",
    "Ø£Ùˆ",
}


def normalize(text: Any) -> str:
    value = str(text or "").strip().lower()
    if not value:
        return ""
    value = DIACRITICS_RE.sub("", value)
    value = value.replace("Ù€", "")
    value = value.replace("Ø£", "Ø§").replace("Ø¥", "Ø§").replace("Ø¢", "Ø§")
    value = value.replace("Ù‰", "ÙŠ").replace("Ø©", "Ù‡")
    value = PUNCT_RE.sub(" ", value)
    value = WS_RE.sub(" ", value).strip()
    return value


def is_meaningful_alias(alias: str) -> bool:
    n = normalize(alias)
    if len(n) < 2:
        return False
    if n in GENERIC_BAD:
        return False
    if len(n.split()) == 1 and n in GENERIC_RISKY_SINGLE:
        return False
    return True


def is_code_like_alias(alias: str) -> bool:
    n = normalize(alias)
    if not n:
        return False
    if re.fullmatch(r"[a-z]{2,10}\d{1,4}[a-z]{0,3}\d{0,2}", n):
        return True
    # short lab abbreviations (CBC, TSH, ESR, ALT, etc.)
    return bool(re.fullmatch(r"[a-z]{2,4}", n))


def is_strong_test_alias(alias: str) -> bool:
    n = normalize(alias)
    if not is_meaningful_alias(n):
        return False
    tokens = n.split()
    if is_code_like_alias(n):
        return True
    if len(tokens) >= 2:
        return len(n) >= 5
    # Single-word aliases are allowed only when specific enough.
    if len(n) >= 5 and n not in GENERIC_RISKY_SINGLE:
        return True
    return False


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = (line or "").strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def uniq_sorted_aliases(values: set[str]) -> list[str]:
    cleaned: set[str] = set()
    for v in values:
        n = normalize(v)
        if is_meaningful_alias(n):
            cleaned.add(n)
    return sorted(cleaned)


def derive_aliases(values: list[str]) -> set[str]:
    out: set[str] = set()
    for raw in values:
        if not raw:
            continue
        out.add(raw)
        base = PARENS_RE.sub(" ", raw)
        out.add(base)
        out.add(re.sub(r"[-/]+", " ", base))
        for part in re.split(r"[-/|]", raw):
            part = part.strip()
            if part:
                out.add(part)
        tokens = normalize(raw).split()
        for t in tokens:
            if len(t) >= 2 and t not in AR_STOP and t not in GENERIC_BAD:
                out.add(t)
        for n in (2, 3):
            for i in range(0, max(0, len(tokens) - n + 1)):
                ng = " ".join(tokens[i : i + n]).strip()
                if is_meaningful_alias(ng):
                    out.add(ng)
    return out


def extract_text_terms(text: str) -> set[str]:
    tokens = [t for t in normalize(text).split() if len(t) >= 3 and t not in AR_STOP]
    out: set[str] = set(tokens)
    for n in (2, 3):
        for i in range(0, max(0, len(tokens) - n + 1)):
            ng = " ".join(tokens[i : i + n]).strip()
            if is_meaningful_alias(ng):
                out.add(ng)
    return out


def derive_test_aliases(
    canonical_ar: str,
    canonical_en: str,
    canonical_name: str,
    canonical_name_clean: str,
    code: Any,
) -> set[str]:
    raw_fields = [canonical_ar, canonical_en, canonical_name, canonical_name_clean]
    aliases = derive_aliases([f for f in raw_fields if str(f or "").strip()])
    strict = {normalize(a) for a in aliases if is_strong_test_alias(a)}

    # Always keep normalized full canonical names (if meaningful).
    for raw in raw_fields:
        n = normalize(raw)
        if n and is_meaningful_alias(n):
            strict.add(n)

    if code is not None and str(code).strip():
        strict.add(normalize(str(code).strip()))
    return strict


def build_tests_concepts() -> dict[str, dict[str, Any]]:
    tests = read_jsonl(TESTS_CLEAN_PATH)
    concepts: dict[str, dict[str, Any]] = {}

    for row in tests:
        canonical_ar = str(row.get("canonical_ar") or "").strip()
        canonical_name_clean = str(row.get("canonical_name_clean") or "").strip()
        canonical_name = str(row.get("canonical_name") or "").strip()
        code = row.get("code")

        if code is not None and str(code).strip():
            key = f"code::{str(code).strip()}"
        elif normalize(canonical_ar):
            key = normalize(canonical_ar)
        else:
            key = normalize(canonical_name_clean or canonical_name)
        if not key:
            continue

        canonical_en = str(row.get("canonical_en") or "").strip()
        aliases = derive_test_aliases(
            canonical_ar=canonical_ar,
            canonical_en=canonical_en,
            canonical_name=canonical_name,
            canonical_name_clean=canonical_name_clean,
            code=code,
        )
        canonical_aliases = {
            normalize(canonical_ar),
            normalize(canonical_en),
            normalize(canonical_name),
            normalize(canonical_name_clean),
            normalize(str(code or "").strip()),
        }
        canonical_aliases = {a for a in canonical_aliases if a and is_meaningful_alias(a)}

        concept = concepts.setdefault(
            key,
            {
                "display_name": canonical_ar or canonical_name_clean or canonical_name or key,
                "aliases": set(),
                "canonical_aliases": set(),
            },
        )
        concept["aliases"].update(aliases)
        concept["canonical_aliases"].update(canonical_aliases)
        if code is not None and str(code).strip():
            concept["aliases"].add(str(code).strip())

    # Merge tests chunks metadata only (avoid noisy free-text term expansion).
    chunks = read_jsonl(TESTS_CHUNKS_PATH)
    for ch in chunks:
        meta = ch.get("metadata") if isinstance(ch.get("metadata"), dict) else {}
        can_ar = str(meta.get("canonical_ar") or "").strip()
        can_en = str(meta.get("canonical_en") or "").strip()
        can_clean = str(meta.get("canonical_name_clean") or "").strip()
        code = meta.get("code")
        if code is not None and str(code).strip():
            key = f"code::{str(code).strip()}"
        else:
            key = normalize(can_ar)
        if not key or key not in concepts:
            continue
        concepts[key]["aliases"].update(
            derive_test_aliases(
                canonical_ar=can_ar,
                canonical_en=can_en,
                canonical_name=can_clean,
                canonical_name_clean=can_clean,
                code=code,
            )
        )

    # Merge prices into corresponding test concept when possible.
    if PRICES_INDEX_PATH.exists():
        prices = json.loads(PRICES_INDEX_PATH.read_text(encoding="utf-8"))
        records = prices.get("records", []) if isinstance(prices, dict) else []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            raw_aliases = [
                str(rec.get("name_ar") or "").strip(),
                str(rec.get("name_en") or "").strip(),
                str(rec.get("canonical_name_clean") or "").strip(),
                str(rec.get("code") or "").strip(),
            ]
            for k in rec.get("keys") or []:
                raw_aliases.append(str(k))
            cand_aliases = [a for a in uniq_sorted_aliases(derive_aliases(raw_aliases)) if is_strong_test_alias(a)]
            if not cand_aliases:
                continue

            # match by strongest alias overlap
            best_key = None
            best_overlap = 0
            cand_set = set(cand_aliases)
            for t_key, t_obj in concepts.items():
                t_set = set(t_obj["aliases"])
                overlap = len(cand_set & t_set)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_key = t_key
            if best_key and best_overlap >= 2:
                concepts[best_key]["aliases"].update(cand_set)

    # Prune ambiguous aliases that appear across many tests unless canonical/code-like.
    alias_count: Counter[str] = Counter()
    for obj in concepts.values():
        for a in obj["aliases"]:
            alias_count[normalize(a)] += 1

    final: dict[str, dict[str, Any]] = {}
    for key, obj in concepts.items():
        kept_aliases: set[str] = set()
        canonical_aliases = {normalize(a) for a in obj.get("canonical_aliases", set())}
        for a in obj["aliases"]:
            an = normalize(a)
            if not is_strong_test_alias(an):
                continue
            if an in canonical_aliases or is_code_like_alias(an):
                kept_aliases.add(an)
                continue
            if alias_count.get(an, 0) > 2:
                continue
            kept_aliases.add(an)
        final[key] = {
            "display_name": obj["display_name"],
            "aliases": uniq_sorted_aliases(kept_aliases),
        }
    return final


def build_packages_concepts() -> dict[str, dict[str, Any]]:
    rows = read_jsonl(PACKAGES_CLEAN_PATH)
    concepts: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("package_name") or "").strip()
        category = str(row.get("main_category") or "").strip()
        desc = str(row.get("description") or "").strip()
        tags = row.get("tags") if isinstance(row.get("tags"), list) else []
        tags = [str(t).strip() for t in tags if str(t).strip()]
        key = normalize(name) or normalize(category)
        if not key:
            continue
        aliases = derive_aliases([name, category, desc, *tags])
        concept = concepts.setdefault(key, {"display_name": name or category or key, "aliases": set()})
        concept["aliases"].update(aliases)

    final: dict[str, dict[str, Any]] = {}
    for key, obj in concepts.items():
        final[key] = {"display_name": obj["display_name"], "aliases": uniq_sorted_aliases(set(obj["aliases"]))}
    return final


def build_branches_concepts() -> dict[str, dict[str, Any]]:
    rows = read_jsonl(BRANCHES_CLEAN_PATH)
    concepts: dict[str, dict[str, Any]] = {}
    city_seed = {
        "Ø§Ù„Ø±ÙŠØ§Ø¶",
        "Ø¬Ø¯Ù‡",
        "Ø¬Ø¯Ø©",
        "Ù…ÙƒÙ‡",
        "Ù…ÙƒØ©",
        "Ø§Ù„Ù…Ø¯ÙŠÙ†Ù‡",
        "Ø§Ù„Ù…Ø¯ÙŠÙ†Ø©",
        "Ø§Ù„Ø¯Ù…Ø§Ù…",
        "Ø§Ù„Ø®Ø¨Ø±",
        "Ø§Ù„Ø§Ø­Ø³Ø§Ø¡",
        "Ø§Ù„Ø£Ø­Ø³Ø§Ø¡",
        "Ø§Ù„Ø·Ø§Ø¦Ù",
        "Ø§Ø¨Ù‡Ø§",
        "Ø£Ø¨Ù‡Ø§",
        "Ø¬Ø§Ø²Ø§Ù†",
        "ØªØ¨ÙˆÙƒ",
        "Ø§Ù„Ù‚ØµÙŠÙ…",
        "Ø­Ø§Ø¦Ù„",
        "Ù†Ø¬Ø±Ø§Ù†",
        "Ø§Ù„Ø¬Ø¨ÙŠÙ„",
    }

    for row in rows:
        section = str(row.get("section") or "").strip()
        branch = str(row.get("branch_name") or "").strip()
        raw_text = str(row.get("raw_text") or "").strip()
        if not section and not branch:
            continue

        branch_key = f"branch::{normalize(branch)}" if normalize(branch) else ""
        if branch_key:
            concept = concepts.setdefault(branch_key, {"display_name": branch, "aliases": set()})
            concept["aliases"].update(derive_aliases([branch, section, raw_text]))

        section_n = normalize(section)
        for city in city_seed:
            city_n = normalize(city)
            if city_n and city_n in section_n:
                city_key = f"city::{city_n}"
                city_obj = concepts.setdefault(city_key, {"display_name": city, "aliases": set()})
                city_obj["aliases"].update(derive_aliases([city, section, branch]))

    final: dict[str, dict[str, Any]] = {}
    for key, obj in concepts.items():
        final[key] = {"display_name": obj["display_name"], "aliases": uniq_sorted_aliases(set(obj["aliases"]))}
    return final


def build_faq_intents() -> dict[str, list[str]]:
    if not FAQ_INDEX_PATH.exists():
        return {}
    items = json.loads(FAQ_INDEX_PATH.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        return {}

    intent_rules = {
        "home_visit": {"زيارة منزلية", "زياره منزليه", "خدمة منزلية", "سحب منزلي"},
        "results_time": {"متى", "النتيجة", "نتيجة", "كم يوم", "وقت"},
        "home_collection": {"سحب", "منزل", "المنزل", "عينة", "عينه"},
        "booking": {"حجز", "موعد", "احجز", "طلب خدمة"},
        "contact": {"تواصل", "رقم", "اتصال", "خدمة العملاء", "واتساب"},
        "reports": {"تقرير", "النتائج", "نتائج", "pdf", "استلام"},
        "insurance/payment": {"تامين", "تأمين", "دفع", "سداد", "فيزا", "بطاقة"},
    }

    intent_aliases: dict[str, set[str]] = {k: set() for k in intent_rules}
    phrase_counter: Counter[str] = Counter()

    for row in items:
        q_norm = normalize(row.get("q_norm") or row.get("q") or "")
        if not q_norm:
            continue
        phrase_counter[q_norm] += 1
        for intent, kws in intent_rules.items():
            if any(normalize(k) in q_norm for k in kws):
                intent_aliases[intent].add(q_norm)
                intent_aliases[intent].update(extract_text_terms(q_norm))

    # add frequently occurring phrases (>=2) to related intents
    frequent = {p for p, c in phrase_counter.items() if c >= 2}
    for phrase in frequent:
        for intent, kws in intent_rules.items():
            if any(normalize(k) in phrase for k in kws):
                intent_aliases[intent].add(phrase)

    return {k: uniq_sorted_aliases(v) for k, v in intent_aliases.items() if v}


def _split_signal_phrases(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    parts = re.split(r"[\n,،;؛|/]+", raw)
    out: list[str] = []
    for p in parts:
        n = normalize(p)
        if len(n) >= 3:
            out.append(n)
    return out


def _test_concept_key(row: dict[str, Any]) -> str:
    code = row.get("code")
    if code is not None and str(code).strip():
        return f"code::{str(code).strip()}"
    canonical_ar = normalize(row.get("canonical_ar") or "")
    if canonical_ar:
        return canonical_ar
    return normalize(row.get("canonical_name_clean") or row.get("canonical_name") or "")


def _candidate_display(labels: list[str]) -> str:
    labels = [str(x).strip() for x in labels if str(x).strip()]
    if not labels:
        return ""
    ar = [x for x in labels if any("\u0600" <= ch <= "\u06FF" for ch in x)]
    if ar:
        ar.sort(key=lambda x: (len(normalize(x)), x))
        return ar[0]
    labels.sort(key=lambda x: (len(normalize(x)), x))
    return labels[0]


def build_general_concepts(
    tests: dict[str, dict[str, Any]],
    packages: dict[str, dict[str, Any]],
    branches: dict[str, dict[str, Any]],
    faq_intents: dict[str, list[str]],
    routing: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    test_rows = read_jsonl(TESTS_CLEAN_PATH)

    # Candidate nodes inferred from test signals.
    candidates: dict[str, dict[str, Any]] = {}

    def add_candidate(
        phrase: str,
        *,
        related_test: str = "",
        signal_type: str = "",
        category_hint: str = "",
    ) -> None:
        p = normalize(phrase)
        if len(p) < 3:
            return
        key = p
        node = candidates.setdefault(
            key,
            {
                "labels": [],
                "aliases": set(),
                "related_tests": set(),
                "signals": {
                    "symptoms": set(),
                    "preparation": set(),
                    "benefit": set(),
                    "category": set(),
                },
                "tokens": set(),
            },
        )
        node["labels"].append(phrase)
        node["aliases"].update(derive_aliases([phrase]))
        node["tokens"].update([t for t in p.split() if len(t) >= 3])
        if related_test:
            node["related_tests"].add(related_test)
        if signal_type in node["signals"]:
            node["signals"][signal_type].add(p)
        if category_hint:
            node["signals"]["category"].add(normalize(category_hint))

    for row in test_rows:
        test_key = _test_concept_key(row)
        if not test_key:
            continue

        category = str(row.get("category_norm") or row.get("category") or "").strip()
        base_names = [
            str(row.get("canonical_ar") or "").strip(),
            str(row.get("canonical_name_clean") or "").strip(),
            str(row.get("canonical_en") or "").strip(),
            category,
        ]
        for n in base_names:
            if n:
                add_candidate(n, related_test=test_key, signal_type="category", category_hint=category)

        for p in _split_signal_phrases(row.get("symptoms") or ""):
            add_candidate(p, related_test=test_key, signal_type="symptoms", category_hint=category)
        for p in _split_signal_phrases(row.get("benefit") or ""):
            add_candidate(p, related_test=test_key, signal_type="benefit", category_hint=category)
        for p in _split_signal_phrases(row.get("preparation") or ""):
            add_candidate(p, related_test=test_key, signal_type="preparation", category_hint=category)

        for fld in ("complementary_tests", "related_tests", "alternative_tests"):
            for p in _split_signal_phrases(row.get(fld) or ""):
                add_candidate(p, related_test=test_key, signal_type="category", category_hint=category)

    # Build generic intent concepts inferred from faq/routing (minimal fallback logic).
    for intent_key, aliases in faq_intents.items():
        add_candidate(intent_key, signal_type="category")
        for a in aliases:
            add_candidate(a, signal_type="category")
    for route_key, aliases in routing.items():
        add_candidate(route_key, signal_type="category")
        for a in aliases:
            add_candidate(a, signal_type="category")

    # Cluster candidates by overlap of important tokens and shared related tests.
    cand_items = sorted(candidates.items(), key=lambda kv: (len(kv[1]["related_tests"]), len(kv[1]["tokens"])), reverse=True)
    clusters: list[dict[str, Any]] = []

    for c_key, c_node in cand_items:
        c_tokens = c_node["tokens"]
        c_tests = c_node["related_tests"]
        placed = False
        for cl in clusters:
            inter = len(c_tokens & cl["tokens"])
            union = len(c_tokens | cl["tokens"]) or 1
            jaccard = inter / union
            shared_tests = len(c_tests & cl["related_tests"])
            if jaccard >= 0.5 or shared_tests >= 2:
                cl["members"].append(c_key)
                cl["tokens"].update(c_tokens)
                cl["related_tests"].update(c_tests)
                placed = True
                break
        if not placed:
            clusters.append(
                {
                    "members": [c_key],
                    "tokens": set(c_tokens),
                    "related_tests": set(c_tests),
                }
            )

    # Pre-index package/branch aliases for relation inference.
    package_alias_map: dict[str, set[str]] = defaultdict(set)
    for pk, pobj in packages.items():
        for a in pobj.get("aliases") or []:
            package_alias_map[normalize(a)].add(pk)
    branch_alias_map: dict[str, set[str]] = defaultdict(set)
    for bk, bobj in branches.items():
        for a in bobj.get("aliases") or []:
            branch_alias_map[normalize(a)].add(bk)

    concepts: dict[str, dict[str, Any]] = {}
    for cl in clusters:
        labels: list[str] = []
        aliases_set: set[str] = set()
        related_tests: set[str] = set()
        signals = {
            "symptoms": set(),
            "preparation": set(),
            "benefit": set(),
            "category": set(),
        }
        for m in cl["members"]:
            node = candidates[m]
            labels.extend(node["labels"])
            aliases_set.update(node["aliases"])
            related_tests.update(node["related_tests"])
            for sk in signals:
                signals[sk].update(node["signals"][sk])

        display_name = _candidate_display(labels)
        if not display_name:
            continue
        key = normalize(display_name).replace(" ", "_")[:120]
        if not key:
            continue

        related_packages: set[str] = set()
        related_branches: set[str] = set()
        for a in aliases_set:
            an = normalize(a)
            related_packages.update(package_alias_map.get(an, set()))
            related_branches.update(branch_alias_map.get(an, set()))

        related_test_names = []
        for t in sorted(related_tests):
            related_test_names.append(str((tests.get(t) or {}).get("display_name") or t))

        concepts[key] = {
            "display_name": display_name,
            "aliases": uniq_sorted_aliases(aliases_set),
            "related_tests": uniq_sorted_aliases(set(related_test_names)),
            "related_packages": sorted({normalize(x) for x in related_packages if normalize(x)}),
            "related_branches": sorted({normalize(x) for x in related_branches if normalize(x)}),
            "signals": {
                "symptoms": uniq_sorted_aliases(signals["symptoms"]),
                "preparation": uniq_sorted_aliases(signals["preparation"]),
                "benefit": uniq_sorted_aliases(signals["benefit"]),
                "category": uniq_sorted_aliases(signals["category"]),
            },
        }

    return concepts


def main() -> None:
    tests = build_tests_concepts()
    packages = build_packages_concepts()
    branches = build_branches_concepts()
    faq_intents = build_faq_intents()

    routing = {
        "price": ["سعر", "بكم", "كم السعر", "تكلفة"],
        "branch": ["فرع", "فروع", "موقع", "العنوان", "اقرب فرع", "أقرب فرع"],
        "package": ["باقة", "باقات", "عرض", "عروض", "بكج"],
        "test": ["تحليل", "فحص", "اختبار"],
        "symptoms": ["اعراض", "أعراض"],
        "preparation": ["تحضير", "قبل التحليل", "صيام", "صايم"],
    }

    concepts = build_general_concepts(
        tests=tests,
        packages=packages,
        branches=branches,
        faq_intents=faq_intents,
        routing=routing,
    )

    payload = {
        "tests": tests,
        "packages": packages,
        "branches": branches,
        "faq_intents": faq_intents,
        "routing": routing,
        "concepts": concepts,
    }

    SYNONYMS_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    QA_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with SYNONYMS_OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    top_20_concepts: list[dict[str, Any]] = []
    for k, v in list(concepts.items())[:20]:
        top_20_concepts.append(
            {
                "key": k,
                "display_name": v.get("display_name"),
                "aliases_sample": (v.get("aliases") or [])[:10],
                "related_tests_sample": (v.get("related_tests") or [])[:10],
            }
        )

    connected: list[dict[str, Any]] = []
    for k, v in concepts.items():
        conn = len(v.get("related_tests") or []) + len(v.get("related_packages") or []) + len(v.get("related_branches") or [])
        connected.append(
            {
                "key": k,
                "display_name": v.get("display_name"),
                "connections": conn,
                "related_tests_count": len(v.get("related_tests") or []),
                "related_packages_count": len(v.get("related_packages") or []),
                "related_branches_count": len(v.get("related_branches") or []),
            }
        )
    connected.sort(key=lambda x: x["connections"], reverse=True)

    qa = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_test_concepts": len(tests),
        "total_package_concepts": len(packages),
        "total_branch_concepts": len(branches),
        "total_faq_intents": len(faq_intents),
        "total_general_concepts": len(concepts),
        "top_20_concepts": top_20_concepts,
        "top_20_most_connected_concepts": connected[:20],
        "output_file": str(SYNONYMS_OUT_PATH),
    }

    with QA_OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(qa, f, ensure_ascii=False, indent=2)

    print(f"total_test_concepts: {len(tests)}")
    print(f"total_package_concepts: {len(packages)}")
    print(f"total_branch_concepts: {len(branches)}")
    print(f"total_faq_intents: {len(faq_intents)}")
    print(f"total_general_concepts: {len(concepts)}")
    print(f"output_path: {SYNONYMS_OUT_PATH}")
    print(f"report_path: {QA_OUT_PATH}")


if __name__ == "__main__":
    main()
