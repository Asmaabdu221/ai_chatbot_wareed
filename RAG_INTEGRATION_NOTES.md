# RAG Integration Notes — `tests_REBUILT.xlsx`

How the rebuilt workbook maps to the 6 chatbot scenarios, with sample lookups and indexing guidance.
File: `app/data/sources/excel/tests_REBUILT.xlsx` · 574 tests · 6 sheets · key = `test_id` (`TEST_001…574`).

> **Trust model:** every enriched value carries a `data_source` tag (`ORIGINAL`, `LIS_REFERENCE`, `DERIVED`, `AI_GENERATED`) and each row has `needs_review` + `review_flags`. Anything tagged `AI_GENERATED` or containing `NEEDS_REVIEW` must be confirmed by the lab before it is shown to patients as fact (especially ranges and clinical significance).

## Sheets
| Sheet | Purpose |
|---|---|
| `التحاليل الكاملة` | Master — one row per test, 44 columns (header row 1 = Arabic, row 2 = English keys; **data starts row 3**) |
| `فجوات البيانات` | Column completion rates + bar chart + manual-fill priorities |
| `الكلمات المرادفة` | **Synonym index** — 35.7k flat rows `search_term \| test_id \| name_ar \| name_en \| match_type` (the RAG search table) |
| `الأعراض والتحاليل` | Symptom → test_ids + package_ids |
| `التحاليل المتشابهة` | Disambiguation groups + decision helpers |
| `ملخص التحسينات` | Before/after summary |

```python
import pandas as pd
P = "app/data/sources/excel/tests_REBUILT.xlsx"
tests = pd.read_excel(P, sheet_name="التحاليل الكاملة", header=1, dtype=str).fillna("")   # header=1 → English keys
syn   = pd.read_excel(P, sheet_name="الكلمات المرادفة", dtype=str).fillna("")
symap = pd.read_excel(P, sheet_name="الأعراض والتحاليل", dtype=str).fillna("")
disamb= pd.read_excel(P, sheet_name="التحاليل المتشابهة", dtype=str).fillna("")
by_id = tests.set_index("test_id")
```

## Scenario → columns → lookup

### 1) Zero-miss name matching
Index the **synonym sheet** for fuzzy search; resolve hit → `test_id` → master row.
- Index columns: `الكلمات المرادفة.search_term` (covers official AR/EN, `short_names`, `Aliases (EN)/(AR)`, `common_misspellings`, and symptom phrasings via `match_type`).
```python
from rapidfuzz import process, fuzz
choices = syn["search_term"].tolist()
def resolve(q, thr=82):
    m = process.extractOne(q, choices, scorer=fuzz.token_sort_ratio)
    if m and m[1] >= thr:
        return syn.iloc[m[2]]["test_id"]
    return None
```
Build the vector/fuzzy index over `search_term` once at startup; keep `match_type` so you can rank exact names above symptom phrasings.

### 2) Cross-selling
Master columns: `التحاليل المكملة`, `تحاليل بديلة`, `تحاليل قريبة`, `package_id` (+ `package_names`).
```python
r = by_id.loc[test_id]
upsell = {"complementary": r["التحاليل المكملة"], "alternative": r["تحاليل بديلة"],
          "related": r["تحاليل قريبة"], "packages": r["package_id"]}   # package_id is fuzzy → NEEDS_REVIEW
```

### 3) Smart navigation / disambiguation
When a query matches >1 test or a known ambiguous stem, use the **disambiguation sheet** + master `disambiguation_group`, `test_comparison`, `best_for`.
```python
grp = by_id.loc[test_id]["disambiguation_group"]
if grp:
    row = disamb[disamb["group_name"] == grp].iloc[0]
    ask = row["decision_helper"]      # clarifying question to show the patient
    members = row["test_ids"]
```

### 4) Symptom-based recommendations
Use the **symptoms sheet** (symptom → test_ids + package_ids). Match the patient phrase against `symptom_ar` (and the `symptom`/`symptom_alias` rows in the synonym sheet).
```python
def tests_for_symptom(phrase, thr=80):
    cands = symap["symptom_ar"].tolist()
    m = process.extractOne(phrase, cands, scorer=fuzz.token_set_ratio)
    if m and m[1] >= thr:
        row = symap.iloc[m[2]]
        return row["test_ids"].split(", "), row["package_ids"]   # offer the package as upsell
    return [], ""
```

### 5) Fasting & preparation
Master: `fasting_required` (نعم/لا), `fasting_hours`, `التحضير قبل التحليل`, `special_notes`.
```python
r = by_id.loc[test_id]
fasting = {"required": r["fasting_required"], "hours": r["fasting_hours"],
           "prep": r["التحضير قبل التحليل"], "notes": r["special_notes"]}
```

### 6) Availability & pricing
Master: `is_available`, `service_id`, `السعر` (gate behind phone capture per current policy), `TAT`, `result_time_hours`, `branch_availability` (NEEDS_BRANCH_DATA).
```python
r = by_id.loc[test_id]
# price shown only AFTER phone collection (existing chatbot policy)
avail = {"available": r["is_available"], "service_id": r["service_id"],
         "tat": r["TAT"], "branches": r["branch_availability"]}
```

### Bonus — result interpretation
`unit`, `normal_range_male`, `normal_range_female`, `normal_range_child`, `clinical_significance`, `who_needs_it`, `test_type`.
**Guardrail:** check the tag before presenting a range as fact:
```python
r = by_id.loc[test_id]
if str(r["normal_range_male"]).startswith("NEEDS_REVIEW") or "AI_GENERATED" in r["data_source"]:
    # do NOT assert a number; say ranges vary and offer to connect to staff
    ...
```

## What to index for fuzzy search
1. **`الكلمات المرادفة.search_term`** — primary name/alias/symptom index (filter or weight by `match_type`).
2. **`الأعراض والتحاليل.symptom_ar`** — symptom router.
3. Optionally embed `فائدة التحليل` + `who_needs_it` + `best_for` for semantic “what test do I need” queries.
Normalize Arabic before indexing (strip diacritics/tatweel, unify أ/إ/آ→ا, ى→ي, ة→ه) — same normalization at query time.

## Caveats for safe answers
- `normal_range_*` is real LIS only for ~31% of tests; the rest are qualitative defaults or common-analyte references — **all flagged**. Never present a flagged range as definitive.
- `package_id` is a **fuzzy** text match from package descriptions — verify before quoting package membership.
- `branch_availability` is empty (NEEDS_BRANCH_DATA) — don’t claim branch availability yet.
- Respect the existing price policy (reveal `السعر` only after phone capture).
