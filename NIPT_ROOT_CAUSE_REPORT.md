# NIPT Retrieval – Root Cause Analysis Report

## Executive Summary

**Query:** "هل لديكم تحليل nipt"  
**Observed Response:** "عذراً، لا تتوفر لدي معلومات عن تحليل NIPT حالياً."  
**Expected:** NIPT analysis information from knowledge base

**Root Cause:** The authenticated conversations API (`POST /api/conversations/{id}/messages`) uses a **different code path** than the chat API. It calls `message_service.send_message_with_ai` which uses **`get_knowledge_context`** (legacy) instead of **`get_grounded_context`** (RAG pipeline). The legacy path does not use hybrid retrieval and may not find NIPT for short queries.

---

## Execution Path Trace

### Step 1: Frontend Routing

| User State | API Called | Handler |
|------------|------------|---------|
| **Logged in** (authenticated) | `POST /api/conversations/{id}/messages` | `conversations.send_message` → `message_service.send_message_with_ai` |
| **Not logged in** (demo) | `POST /api/chat` | `chat.chat_endpoint` → `get_grounded_context` |

**File:** `frontend-react/src/App.js` line 200  
**Logic:** When user is authenticated, `handleSendMessage` calls `sendConversationMessage`, which hits the conversations API.

---

### Step 2: question_router

**File:** `app/services/question_router.py`  
**Result for "هل لديكم تحليل nipt":** `("general", None)` ✓

The query does not contain price keywords (سعر، اسعار، etc.), so it proceeds to knowledge/API.

---

### Step 3: Knowledge Context – THE FAILURE POINT

#### Path A: POST /api/chat (RAG – works)

**File:** `app/api/chat.py` lines 306–316

```python
if use_rag:
    knowledge_context, has_relevant = get_grounded_context(
        user_message=request.message,
        max_tests=3,
        similarity_threshold=threshold,
        include_prices=True,
    )
    if not has_relevant:
        return NO_INFO_MESSAGE  # Early return, no OpenAI call
```

- Uses `rag_knowledge_base.json` + hybrid retrieval (semantic + lexical)
- For "هل لديكم تحليل nipt": lexical extracts "nipt", matches "Noninvasive prenatal testing (NIPT)", score 1.0
- **Result:** NIPT returned ✓

#### Path B: POST /api/conversations/{id}/messages (Legacy – fails)

**File:** `app/services/message_service.py` lines 157–167

```python
knowledge_context = get_knowledge_context(
    user_message=content,
    max_tests=3,
    max_faqs=2,
    include_prices=True,
)
```

**File:** `app/data/knowledge_loader_v2.py` – `get_knowledge_context`

- Uses `knowledge_base_with_faq.json` (different from RAG)
- Uses `semantic_search` or `kb.smart_search` (fuzzy)
- **No hybrid lexical retrieval** for short queries like "nipt"
- When no results: returns `"⚠️ لم يتم العثور على معلومات محددة في قاعدة المعرفة..."` and still calls OpenAI
- OpenAI sees weak/empty context and generates: "عذراً، لا تتوفر لدي معلومات عن تحليل NIPT حالياً."

---

### Step 4: Why the Response Differs from NO_INFO_MESSAGE

| Source | Exact Text |
|--------|------------|
| **Standard NO_INFO_MESSAGE** (chat.py early return) | "عذراً، لا تتوفر لدي معلومات عن ذلك حالياً." |
| **User's observed response** | "عذراً، لا تتوفر لدي معلومات عن تحليل NIPT حالياً." |

The presence of "تحليل NIPT" shows the response comes from **OpenAI**, not from the fixed NO_INFO_MESSAGE. The model paraphrases the system prompt using the user's question.

---

## Summary Table

| Component | Chat API (/api/chat) | Conversations API (/conversations/.../messages) |
|----------|----------------------|--------------------------------------------------|
| **question_router** | ✓ general | ✓ general |
| **Knowledge source** | `rag_knowledge_base.json` | `knowledge_base_with_faq.json` |
| **Retrieval** | Hybrid (semantic + lexical) | Semantic or fuzzy only |
| **has_sufficient / no-info** | Yes, early return | No – always calls OpenAI |
| **NIPT for "هل لديكم تحليل nipt"** | ✓ Found (lexical) | ✗ Often not found |

---

## Architectural Fix (Implemented)

**File:** `app/services/message_service.py`

**Change:** Use the same RAG pipeline as chat.py when RAG is ready:

1. When `is_rag_ready()`: call `get_grounded_context` (RAG pipeline).
2. When `not has_relevant`: return `NO_INFO_MESSAGE` without calling OpenAI.
3. When RAG not built: fall back to `get_knowledge_context` and handle no-match by returning `NO_INFO_MESSAGE` instead of calling OpenAI with weak context.

This unifies behavior across both APIs and ensures NIPT and similar short queries are retrieved correctly for authenticated users.
