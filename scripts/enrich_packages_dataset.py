import json
import re
from pathlib import Path


PATH = Path("app/data/runtime/rag/packages_clean.jsonl")
BACKUP = PATH.with_suffix(PATH.suffix + ".bak_smart_upgrade")


TEST_PATTERNS = [
    re.compile(r"(?:^|\n)\s*\d+\s*[\.)\-]\s*([^\n]{2,120})", re.IGNORECASE),
    re.compile(r"(?:تحليل|تحاليل)\s+([^\n\.,،:]{2,80})", re.IGNORECASE),
    re.compile(r"\b([A-Z]{2,}(?:/[A-Z]{2,})?)\b"),
]

BEST_FOR_KEYWORDS = {
    "السكر": ["سكر", "سكري", "hba1c", "glucose", "insulin"],
    "الغدة الدرقية": ["غده", "الغده", "درقي", "thyroid", "tsh", "t3", "t4"],
    "فيتامينات ومعادن": ["فيتامين", "vitamin", "حديد", "ferritin", "zinc", "magnesium", "calcium"],
    "الدهون وصحة القلب": ["cholesterol", "ldl", "hdl", "triglyceride", "دهون", "قلب"],
    "الكبد": ["كبد", "liver", "alt", "ast", "ggt", "alp"],
    "الكلى": ["كلى", "kidney", "creatinine", "egfr", "urea", "bun"],
    "الطاقة والإرهاق": ["تعب", "ارهاق", "إرهاق", "خمول", "دوخه", "دوخة"],
    "الشعر": ["شعر", "تساقط", "hair", "alopecia"],
    "الصيام ورمضان": ["رمضان", "صيام", "صائم"],
    "المناعة": ["مناعة", "immune", "infection", "عدوى"],
}


def safe_str(v):
    return str(v or "").strip()


def normalize_ar(s: str) -> str:
    s = safe_str(s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي").replace("ـ", "")
    s = re.sub(r"[\u064B-\u065F\u0670]", "", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def extract_tests(text: str) -> list[str]:
    out: list[str] = []
    for pat in TEST_PATTERNS:
        for m in pat.finditer(text):
            v = safe_str(m.group(1))
            if len(v) < 2:
                continue
            v = re.sub(r"^[\-:–]+", "", v).strip()
            v = re.sub(r"\s{2,}", " ", v)
            if v and v not in out:
                out.append(v)

    cleaned: list[str] = []
    for t in out:
        if len(t) > 80:
            continue
        if any(x in t for x in ("تفاصيل", "تشمل هذه", "فوائد", "لماذا")):
            continue
        cleaned.append(t)
    return cleaned[:20]


def build_aliases(package_name: str) -> list[str]:
    base = safe_str(package_name)
    if not base:
        return []
    aliases = [base]

    no_prefix = re.sub(r"^\s*باقة\s+", "", base).strip()
    if no_prefix and no_prefix not in aliases:
        aliases.append(no_prefix)
    if no_prefix:
        with_prefix = f"باقة {no_prefix}"
        if with_prefix not in aliases:
            aliases.append(with_prefix)

    compact = re.sub(r"[\-_/]+", " ", base)
    compact = re.sub(r"\s+", " ", compact).strip()
    if compact and compact not in aliases:
        aliases.append(compact)

    norm = normalize_ar(base)
    if norm and norm not in [normalize_ar(a) for a in aliases]:
        aliases.append(norm)

    return aliases[:10]


def infer_best_for(text_blob: str) -> list[str]:
    n = normalize_ar(text_blob)
    labels: list[str] = []
    for label, kws in BEST_FOR_KEYWORDS.items():
        for kw in kws:
            if normalize_ar(kw) in n:
                labels.append(label)
                break
    if not labels:
        labels.append("فحص صحي عام")
    return labels[:6]


def main() -> None:
    if not PATH.exists():
        raise SystemExit(f"Missing file: {PATH}")

    if not BACKUP.exists():
        BACKUP.write_text(PATH.read_text(encoding="utf-8"), encoding="utf-8")

    rows: list[dict | str] = []
    updated = 0
    with PATH.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                rows.append(raw)
                continue
            if not isinstance(obj, dict):
                rows.append(obj)
                continue

            name = safe_str(obj.get("package_name") or obj.get("Package Name"))
            category = safe_str(obj.get("category") or obj.get("main_category") or obj.get("Main Category"))
            dshort = safe_str(obj.get("description_short") or obj.get("Description Short"))
            dfull = safe_str(obj.get("description_full") or obj.get("Description Full"))
            text_blob = " ".join([name, category, dshort, dfull]).strip()

            if not obj.get("tests_included"):
                obj["tests_included"] = extract_tests(dfull)
                updated += 1

            if not obj.get("best_for"):
                obj["best_for"] = infer_best_for(text_blob)
                updated += 1

            if not obj.get("aliases"):
                obj["aliases"] = build_aliases(name)
                updated += 1

            aliases = obj.get("aliases") if isinstance(obj.get("aliases"), list) else []
            tests = obj.get("tests_included") if isinstance(obj.get("tests_included"), list) else []
            best_for = obj.get("best_for") if isinstance(obj.get("best_for"), list) else []

            search_parts = [
                name,
                category,
                dshort,
                dfull,
                " ".join([safe_str(x) for x in aliases]),
                " ".join([safe_str(x) for x in tests]),
                " ".join([safe_str(x) for x in best_for]),
            ]
            obj["search_text"] = " ".join([p for p in search_parts if p]).strip()

            rows.append(obj)

    with PATH.open("w", encoding="utf-8") as f:
        for r in rows:
            if isinstance(r, dict):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            else:
                f.write(str(r) + "\n")

    print(f"rows={len(rows)} updated_fields={updated} backup={BACKUP}")


if __name__ == "__main__":
    main()
