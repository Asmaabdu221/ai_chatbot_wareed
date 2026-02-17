# NIPT Retrieval Failure – Technical Root Cause Analysis

## Executive Summary

**Root Cause:** The similarity scores for NIPT-related queries are **all below the 0.75 threshold**. Retrieval finds NIPT correctly (it appears in the top results), but the strict threshold filter discards all results, leading to the "no information available" response.

---

## 1. Execution Flow Trace

### Step 1: `question_router.py`

**File:** `app/services/question_router.py`

**Behavior:** Routes only price/offer questions. Neither "Do you have NIPT test?" nor "هل لديكم تحليل nipt" contain any `PRICE_KEYWORDS` (سعر، كم، cost، etc.).

**Result:** `route_type = "general"`, `fixed_reply = None` → Query proceeds to RAG.

**Conclusion:** question_router is **not** the cause.

---

### Step 2: Chat API (`app/api/chat.py`)

**Flow:**
1. `route_question()` → general (no fixed reply)
2. Smart cache check → miss (first time)
3. `is_rag_ready()` → True
4. `get_grounded_context(user_message, max_tests=3, similarity_threshold=0.75)`

**Conclusion:** Retrieval **is** executed.

---

### Step 3: RAG Pipeline (`app/data/rag_pipeline.py`)

#### 3.1 `get_grounded_context()`

- Calls `retrieve(user_message, max_results=3, similarity_threshold=0.75)`
- No query preprocessing: raw `user_message` is passed through
- No token filtering or normalization before embedding

#### 3.2 `retrieve()`

```python
q_emb = get_embedding(query)  # query passed as-is
for i, emb in enumerate(test_embeddings):
    sim = _cosine_similarity(q_emb, emb)
    scored.append((i, sim))
scored.sort(key=lambda x: x[1], reverse=True)
# ...
has_sufficient = any(score >= 0.75 for score in scored[:max_results])
```

- Query is embedded as-is (no preprocessing)
- Cosine similarity is computed against all 574 test embeddings
- `has_sufficient` is True only if at least one score ≥ 0.75

#### 3.3 Post-filter in `get_grounded_context()`

```python
above_threshold = [r for r in results if r["score"] >= similarity_threshold]
if not above_threshold:
    return "", False  # → triggers NO_INFO_MESSAGE
```

**Conclusion:** The 0.75 threshold is the filter that removes all NIPT results.

---

### Step 4: Embeddings Service (`app/services/embeddings_service.py`)

```python
text = (text or "").strip()
# No other preprocessing
response = client.embeddings.create(model=..., input=text)
```

- Only `.strip()` is applied
- No normalization, token filtering, or cleaning

---

## 2. Actual Similarity Scores (from `diagnose_nipt_retrieval.py`)

| Query | Best NIPT Score | Threshold 0.75 | NIPT Rank |
|-------|-----------------|----------------|-----------|
| "Do you have NIPT test?" | **0.5860** | ❌ Below | #1 |
| "هل لديكم تحليل nipt" | **0.4865** | ❌ Below | #2–3 |
| "هل لديكم تحليل NIPT" | **0.5955** | ❌ Below | #1–2 |
| "NIPT" | **0.6204** | ❌ Below | #1 |
| "nipt" (lowercase) | **0.3349** | ❌ Below | #2–3 |
| "الفحص قبل الولادة غير الغازي" | **0.6440** | ❌ Below | #1–2 |
| "Noninvasive prenatal testing" | **0.6013** | ❌ Below | #1–2 |

**Highest score observed:** 0.6440 (still below 0.75).

---

## 3. Why Scores Are Below 0.75

### 3.1 Semantic Mismatch

- **"Do you have NIPT test?"** → availability / service question
- **Document text** → medical description (name, description, symptoms, etc.)

Embeddings capture meaning, not exact wording. Availability questions and medical descriptions sit in different regions of the embedding space, so similarity stays moderate.

### 3.2 Short Query "nipt"

- Very short query (4 characters)
- Embedding for "nipt" alone is weak and can match unrelated tokens (e.g. "NIFTY", "NT", "Troponin")
- NIFTY® Gender (0.3795) ranks above NIPT (0.3349) for the query "nipt"

### 3.3 Document Construction

Documents are built from:

```python
parts = [analysis_name_ar, analysis_name_en, description, symptoms, 
         category, sample_type, preparation, complementary_tests]
```

NIPT documents are long and cover many concepts. The query "NIPT" or "Do you have NIPT?" overlaps only a small part, which limits cosine similarity.

---

## 4. Components Checked

| Component | Status | Notes |
|-----------|--------|------|
| question_router | ✅ Not the cause | Does not match NIPT queries |
| Retrieval execution | ✅ Runs | NIPT is retrieved |
| Preprocessing | ✅ Minimal | Only `.strip()` on query |
| Embeddings | ✅ Loaded | 574 tests, no mismatch |
| Vector search | ✅ Works | NIPT in top results |
| Similarity threshold | ❌ **Root cause** | 0.75 filters out all NIPT results |
| Post-filter | ❌ **Effect** | Drops results below 0.75 |

---

## 5. Recommended Fixes

### Option A: Lower the threshold (simplest)

- Reduce `RAG_SIMILARITY_THRESHOLD` from 0.75 to **0.58** or **0.60**
- NIPT and similar availability queries would pass
- Trade-off: more risk of irrelevant matches

### Option B: Hybrid retrieval (recommended)

- Add a **keyword/fuzzy** path for known acronyms (e.g. NIPT, CBC, TSH)
- If query contains a known term → run keyword match first
- If match found → include in context even when embedding score < 0.75
- Keeps semantic search for general questions

### Option C: Query expansion

- Expand "Do you have NIPT?" to something like "NIPT test Noninvasive prenatal testing"
- Improves embedding similarity
- Requires extra logic and maintenance

---

## 6. Verification

Run the diagnostic script:

```bash
python diagnose_nipt_retrieval.py
```

Results are written to `diagnose_nipt_results.txt`.
