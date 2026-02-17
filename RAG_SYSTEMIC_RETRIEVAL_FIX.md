# RAG Systemic Retrieval Fix – Root Cause & Solution

## Executive Summary

**Problem:** Short queries like "Do you have NIPT?", "Ferritin?", "Vitamin D test?", "HbA1c?", "تحليل nipt" sometimes returned "عذرًا، لا توجد معلومات متاحة حول هذا الطلب في النظام حالياً." even though the tests exist in the knowledge base.

**Root Cause:** Semantic-only retrieval with a 0.75 similarity threshold. Embeddings perform poorly on short, keyword-like queries (acronyms, test names), producing scores below 0.75 and causing all results to be filtered out.

**Solution:** Hybrid retrieval (semantic + lexical). Lexical fuzzy search on test names handles short queries, acronyms, and partial names; semantic search continues to handle conceptual questions.

---

## 1. Execution Flow (Before Fix)

```
User Query (e.g. "Do you have NIPT?")
  → question_router (general, no fixed reply)
  → get_grounded_context()
    → retrieve() [semantic only]
      → get_embedding(query)
      → cosine similarity vs 574 test embeddings
      → filter: keep only score >= 0.75
    → has_sufficient = False (best NIPT score ~0.64)
    → return "", False → NO_INFO_MESSAGE
```

**Failure point:** `retrieve()` in `app/data/rag_pipeline.py` – semantic scores for short test-name queries are below 0.75.

---

## 2. Root Cause Analysis

### 2.1 Why Semantic Search Fails for Short Queries

| Factor | Effect |
|--------|--------|
| **Short input** | "NIPT", "Ferritin", "HbA1c" – few tokens; embedding is noisy |
| **Availability phrasing** | "Do you have X?" vs document text (medical description) – different semantic regions |
| **Acronyms** | "NIPT" as 4 chars vs "Noninvasive prenatal testing (NIPT)" – limited overlap in embedding space |
| **Threshold 0.75** | Strict; valid matches often score 0.55–0.70 |

### 2.2 Components Checked (Not the Cause)

| Component | Status |
|-----------|--------|
| question_router | ✅ Does not block NIPT/test queries |
| Preprocessing | ✅ Minimal (strip only); not altering short queries |
| Embeddings | ✅ Loaded; 574 tests |
| Vector search | ✅ NIPT in top results |
| top_k | ✅ Used correctly |
| Post-filter | ❌ **Effect:** drops results below 0.75 |

---

## 3. Implemented Fix: Hybrid Retrieval

### 3.1 Architecture

**File:** `app/data/rag_pipeline.py`

```
User Query
  → retrieve() [hybrid]
    → Semantic: embedding + cosine similarity (unchanged)
    → Lexical: rapidfuzz partial_ratio + token_set_ratio on analysis_name_ar, analysis_name_en
    → Merge: best score per test from both sources
    → has_sufficient = (semantic >= 0.75) OR (lexical >= 0.55)
```

### 3.2 Key Changes

1. **`_extract_search_terms()`** – Strips common question phrases ("Do you have", "تحليل", "test") to get core terms for lexical search.

2. **`_lexical_retrieve()`** – Fuzzy search on test names:
   - `partial_ratio`: handles "nipt" in "Noninvasive prenatal testing (NIPT)"
   - `token_set_ratio`: improves multi-word queries (e.g. "vitamin d" vs "Vitamine K")
   - Substring boost: query contained in name → score 0.9
   - `LEXICAL_MIN_SCORE = 55` (0–100 scale)

3. **`retrieve()`** – Merges semantic and lexical results:
   - Deduplicates by test
   - Keeps best score per test
   - `has_sufficient` = semantic ≥ 0.75 **or** lexical ≥ 0.55

4. **`get_grounded_context()`** – Accepts results that pass either threshold.

### 3.3 Why This Fixes the Issue Globally

- **No hardcoded keywords** – Works for any test in the KB.
- **Short queries** – Lexical search matches "NIPT", "Ferritin", "HbA1c" directly.
- **Arabic/English** – `normalize_for_matching()` handles Arabic variants.
- **Partial names** – `partial_ratio` finds "nipt" in "Noninvasive prenatal testing (NIPT)".
- **Acronyms** – Exact and fuzzy match on names.

---

## 4. Verification

Run:

```bash
python test_hybrid_retrieval.py
```

Expected (with fix):

- "Do you have NIPT?" → NIPT ✓
- "Ferritin?" → Ferritin ✓
- "Vitamin D test?" → Vitamin D (or related; fuzzy may occasionally match similar names)
- "HbA1c?" → Glycated Haemoglobin (HbA1c) ✓
- "nipt" → NIPT ✓
- "تحليل nipt" → NIPT ✓

---

## 5. Configuration

| Constant | Value | Purpose |
|----------|-------|---------|
| `DEFAULT_SIMILARITY_THRESHOLD` | 0.75 | Semantic threshold |
| `LEXICAL_MIN_SCORE` | 55 | Lexical fuzzy threshold (0–100) |

Adjust `LEXICAL_MIN_SCORE` if needed: lower = more recall, higher = stricter.
