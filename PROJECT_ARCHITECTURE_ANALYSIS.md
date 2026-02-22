# PROJECT_ARCHITECTURE_ANALYSIS

## Scope and Method
- This analysis is based on static inspection of the current repository at `C:\Users\asmaa\OneDrive\Documents\work\ai_chatbot_wareed`.
- No runtime behavior was changed and no application code was modified.
- Focused primarily on active runtime paths under `app/`, `frontend-react/`, and `mobile-app/`.

## 1) Technology Identification

### Framework(s)
- Backend framework: FastAPI (`app/main.py:81`, router registration at `app/main.py:124` to `app/main.py:127`).
- Frontend web framework: React (Create React App) (`frontend-react/package.json`).
- Mobile framework: React Native + Expo (`mobile-app/package.json`, `MOBILE_APP_README.md`).

### Programming language(s)
- Backend: Python 3.x (`app/**/*.py`, `requirements.txt`).
- Web frontend: JavaScript (`frontend-react/src/**/*.js`).
- Mobile frontend: TypeScript (`mobile-app/src/**/*.ts`, `mobile-app/src/**/*.tsx`).

### Database system + ORM
- Database: PostgreSQL (production target via `DATABASE_URL`) (`app/db/session.py`).
- ORM: SQLAlchemy ORM 2.x with declarative models (`app/db/models.py`, `app/db/session.py`).
- Migrations: Alembic (`alembic/`, `alembic.ini`).
- Session mode: synchronous SQLAlchemy sessions (`sessionmaker` in `app/db/session.py:65`).

### How OpenAI is called (SDK version, wrappers, sync/async)
- SDK version pinned: `openai==1.59.6` (`requirements.txt`).
- Main wrapper: `OpenAIService` in `app/services/openai_service.py`.
  - System prompt builder: `_build_system_prompt()` (`app/services/openai_service.py:35`).
  - Chat completions call: `self.client.chat.completions.create(...)` (`app/services/openai_service.py:109`).
- Additional OpenAI call sites:
  - Voice transcription (Whisper): `client.audio.transcriptions.create(...)` (`app/api/chat.py:930`).
  - Vision prescription extraction: `client.chat.completions.create(...)` (`app/services/prescription_vision_service.py:127`).
  - Embeddings API: `client.embeddings.create(...)` (`app/services/embeddings_service.py`).
- Sync/async pattern:
  - OpenAI SDK calls are synchronous.
  - They are invoked from async endpoints (for example `chat_endpoint` in `app/api/chat.py:173`) and from sync service functions.
  - OCR document/image endpoints run heavy work via `run_in_threadpool` (`app/api/ocr.py`).

### Whether RAG is implemented (vector DB? local embeddings? which modules?)
- RAG is implemented.
- No external vector DB is used.
- Vector storage is local JSON files:
  - Knowledge: `app/data/rag_knowledge_base.json`
  - Embeddings: `app/data/rag_embeddings.json`
- Core RAG module: `app/data/rag_pipeline.py`.
  - Hybrid retrieval: semantic + lexical (`retrieve()` at `app/data/rag_pipeline.py:217`).
  - Context generation: `get_grounded_context()` (`app/data/rag_pipeline.py:294`).
  - Readiness check: `is_rag_ready()` (`app/data/rag_pipeline.py:101`).
- Embedding generation uses OpenAI embedding model from settings (`app/services/embeddings_service.py`, `app/core/config.py`).
- Build pipeline: `app/data/build_rag_system.py`.

### Caching system (Redis/in-memory/custom)
- No Redis detected.
- In-memory custom caches:
  - Smart Q/A cache: `SmartCache` (`app/services/smart_cache.py:41`).
  - RAG context cache: `ContextCache` (`app/services/context_cache.py:37`).
  - In-memory rate limiter: `RateLimiter` (`app/services/rate_limiter.py:20`).

### OCR/PDF extraction tools
- OCR (image): `pytesseract` + OpenCV + Pillow (`app/services/ocr_service.py`).
- Prescription image understanding (VLM): OpenAI Vision in `app/services/prescription_vision_service.py`.
- PDF extraction: `pypdf` (`app/services/document_extract_service.py`).
- DOCX extraction: `python-docx` (`app/services/document_extract_service.py`).

### Authentication system (JWT/sessions)
- JWT Bearer auth (no server-side session/cookie auth):
  - Token creation/validation in `app/core/security.py`.
  - Bearer dependency in `app/core/deps.py` (uses `HTTPBearer`).
  - Auth endpoints in `app/api/auth.py` (`/api/auth/register`, `/api/auth/login`, `/api/auth/refresh`, `/api/auth/me`).

### Testing framework (pytest/unittest)
- Pytest dependencies present: `pytest`, `pytest-asyncio` (`requirements.txt`).
- Existing test-like files in repo root (`test_*.py`) are mostly script-style integration checks using direct `requests`/prints, not structured pytest test suites.
- No central `tests/` package or pytest config file was found in active paths scanned.

### Code quality tools (formatters/linters)
- Backend tools in requirements: `black`, `flake8` (`requirements.txt`).
- Web frontend linting: CRA ESLint config (`frontend-react/package.json` with `"extends": ["react-app"]`).
- No dedicated backend config files for black/flake8 were found in the inspected root set.

## 2) End-to-End Request Flow Mapping

### Primary authenticated flow (Web/Mobile): `Frontend -> /api/conversations/{id}/messages`
1. Frontend/UI trigger
- Web: `frontend-react/src/App.js:200` calls `sendConversationMessage(...)`.
- Mobile: `mobile-app/src/screens/ChatScreen.tsx:198` calls `sendConversationMessage(...)`.

2. Frontend API layer
- Web API client sends POST to `/api/conversations/{conversationId}/messages` in `frontend-react/src/services/api.js:237`.
- Mobile API client sends same endpoint in `mobile-app/src/services/api.ts:124`.

3. Backend router
- Endpoint: `app/api/conversations.py:164` (`send_message`).
- Auth dependency: `get_current_user` from `app/core/deps.py`.

4. Service layer
- Calls `msg_svc.send_message_with_ai(...)` (`app/api/conversations.py:180`, implementation in `app/services/message_service.py:122`).

5. Routing/cache/RAG
- Question router: `route_question(...)` (`app/services/message_service.py:156`, from `app/services/question_router.py`).
- RAG check + context: `is_rag_ready()`, `get_grounded_context(...)` (`app/services/message_service.py:166`, `app/services/message_service.py:169`).
- Note: this flow does not use `SmartCache` for full-response reuse.

6. OpenAI call
- `openai_service.generate_response(...)` (`app/services/message_service.py:203` -> `app/services/openai_service.py:69`).

7. Database persistence
- User and assistant messages persisted in `messages` table via SQLAlchemy (`app/services/message_service.py`).

8. Response back
- API returns `SendMessageResponse` with `{ user_message, assistant_message }` (`app/api/conversations.py`).

### Legacy chat flow (Web fallback): `Frontend -> /api/chat`
1. Trigger
- `frontend-react/src/components/ChatWindow.js:45` calls `sendChatMessage(...)` (legacy path).

2. Frontend API call
- POST `/api/chat` (`frontend-react/src/services/api.js:162`).

3. Backend router
- Endpoint `app/api/chat.py:173` (`chat_endpoint`).

4. Processing pipeline inside endpoint
- Rate limit (`app/services/rate_limiter.py`).
- DB create/load user/conversation + save user message (if DB enabled).
- Question routing: `route_question(...)` (`app/api/chat.py:245`).
- Smart cache lookup: `get_smart_cache().get(...)` (`app/api/chat.py:270`).
- RAG retrieval: `get_grounded_context(...)` (`app/api/chat.py:312`).
- OpenAI call (only when needed): `openai_service.generate_response(...)` (`app/api/chat.py:360`).
- Save assistant message to DB and return `ChatResponse` (`app/api/chat.py:391`, `app/api/chat.py:416`).

### Voice flow: `Frontend -> /api/chat/voice`
- Frontend API: `frontend-react/src/services/api.js:332`.
- Endpoint: `app/api/chat.py:696`.
- STT: Whisper transcription call at `app/api/chat.py:930`.
- Then similar branching: router -> cache -> RAG -> OpenAI -> response dict.

### OCR/document flow (separate from chat response generation)
- `/api/extract-text` in `app/api/ocr.py` -> `process_prescription_image(...)` in `app/services/prescription_vision_service.py`.
- `/api/extract-document` in `app/api/ocr.py` -> `extract_text_from_document(...)` in `app/services/document_extract_service.py`.
- Output may then be saved as conversation messages via `savePrescriptionMessages(...)` frontend path (`frontend-react/src/App.js:225` -> backend `app/api/conversations.py:195`).

## 3) Required Locations

### Where the System Prompt is built
- Main chat system prompt: `app/services/openai_service.py:35` (`_build_system_prompt`).
- Vision-specific extraction prompt: `VISION_PROMPT` in `app/services/prescription_vision_service.py:27`.

### Where OpenAI is called
- Main chat completion: `app/services/openai_service.py:109`.
- Connection test completion: `app/services/openai_service.py:168`.
- Vision extraction completion: `app/services/prescription_vision_service.py:127`.
- Whisper transcription: `app/api/chat.py:930`.
- Embeddings: `app/services/embeddings_service.py`.

### Where the final response is returned
- Legacy chat returns `ChatResponse` in `app/api/chat.py` (`return ChatResponse(...)` at multiple branches including `app/api/chat.py:257`, `app/api/chat.py:391`, `app/api/chat.py:416`).
- Conversations API returns `SendMessageResponse` in `app/api/conversations.py:186`.
- Voice chat returns plain dict in `app/api/chat.py` (inside `/chat/voice` handler).
- OCR/document endpoints return plain dicts in `app/api/ocr.py`.

### Whether multiple response paths exist
- Yes, multiple paths exist in both `/api/chat` and `/api/conversations/{id}/messages`:
  - Price-route short-circuit (no OpenAI).
  - Cache-hit short-circuit (no OpenAI).
  - RAG no-match short-circuit (no OpenAI).
  - RAG-not-ready short-circuit (no OpenAI).
  - OpenAI success path.
  - OpenAI error/fallback path.
  - Explicit test endpoint `/api/chat/test` bypasses OpenAI.
  - Prescription-save endpoint bypasses OpenAI (`/api/conversations/{id}/messages/prescription`).

## 4) Technical Risk Analysis

### A) Response paths bypassing a central formatter
Risk level: Medium
- There is no single response formatter layer across all chat surfaces.
- Evidence:
  - `/api/chat` uses `ChatResponse` model (`app/api/chat.py`).
  - `/api/conversations/{id}/messages` uses different schema `SendMessageResponse` (`app/api/conversations.py`).
  - `/api/chat/voice` returns raw dicts directly (`app/api/chat.py`).
  - `/api/extract-text` and `/api/extract-document` return custom dicts (`app/api/ocr.py`).
- Impact:
  - Inconsistent response contracts and metadata fields across paths.
  - Higher frontend branching complexity and potential regressions.

### B) Response paths bypassing OpenAI
Risk level: Low to Medium (intentional but broad)
- Bypass paths are intentional for cost/safety/performance but are numerous and distributed.
- Bypass locations:
  - Price routing: `app/services/question_router.py`, used in `app/api/chat.py` and `app/services/message_service.py`.
  - Smart cache hit: `app/api/chat.py`.
  - RAG no-match/not-ready: `app/api/chat.py`, `app/services/message_service.py`.
  - `/api/chat/test`: explicit no-AI endpoint.
  - Prescription-save endpoint: no-AI write path in `app/api/conversations.py`.
- Impact:
  - Behavior differences between legacy `/api/chat` and conversation API can diverge over time.

### C) Logic duplication
Risk level: High
- Core chat orchestration is duplicated in two separate implementations:
  - `app/api/chat.py` (`chat_endpoint`) and
  - `app/services/message_service.py` (`send_message_with_ai`).
- Duplicated concerns include:
  - Price router checks.
  - RAG readiness/threshold handling.
  - OpenAI invocation and fallback messaging.
  - Assistant message persistence.
- Impact:
  - Higher chance of inconsistent behavior and partial fixes.
  - Increased maintenance/testing burden.

### D) Safety gaps (including emergency filter layer)
Risk level: High
- No dedicated pre- or post-generation safety moderation layer was found.
- No explicit emergency escalation filter (for crisis/self-harm/chest-pain emergency patterns) in active request pipelines.
- Safety is currently mostly prompt-instruction based in `_build_system_prompt`.
- Impact:
  - Prompt-only controls are weaker than deterministic filtering/guard rails.
  - Edge-case harmful outputs are harder to systematically prevent.

### E) Additional architectural risks observed
Risk level: Medium
- Sync OpenAI calls are used from async endpoints (for example `app/api/chat.py:173` -> sync `generate_response`), which can limit concurrency under load.
- `admin.py` router exists but is not mounted in `app/main.py`, creating potential confusion/dead API surface.
- Mixed old/new RAG artifacts (`knowledge_loader_v2` legacy semantic/fuzzy path and `rag_pipeline` path) increase conceptual complexity.

## 5) Concise Architecture Summary
- Backend is FastAPI + SQLAlchemy (PostgreSQL), with JWT Bearer auth and two chat API styles: legacy `/api/chat` and authenticated conversations `/api/conversations/*`.
- OpenAI integration is centralized partially (`openai_service`) but additional direct calls exist (Vision, Whisper, Embeddings).
- RAG is local-file based (JSON knowledge + JSON embeddings), hybrid semantic/lexical retrieval, no external vector DB.
- Caching and rate limiting are custom in-memory components (no Redis).
- Main architectural concern is duplicated chat orchestration logic and lack of a unified response formatting + safety filter layer.

---
Report generated without modifying runtime code paths.
