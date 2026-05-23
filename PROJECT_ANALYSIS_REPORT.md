# Wareed AI — Deep Project Analysis Report

_Generated: 2026-05-22 · Scope: full repository at `ai_chatbot_wareed/` (FastAPI backend, React web app, Expo mobile app, RAG knowledge engine, lab data)._

> This report is the result of reading the configuration, the database models, the API and core security layers, the RAG/knowledge pipeline, the data files, and surveying the web and mobile clients. Where a claim is about runtime behaviour it was verified against the actual code, not the project's own (numerous) markdown summaries.

---

## Phase 1 — Project Discovery & Architecture

### Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI 0.128, Uvicorn/Gunicorn/Waitress |
| Data validation | Pydantic 2.12, pydantic-settings |
| AI | OpenAI (`gpt-4` chat, `gpt-4o` vision, `text-embedding-3-small`), sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`), ChromaDB |
| Database | PostgreSQL (SQLAlchemy 2.0, Alembic, psycopg2 + asyncpg) |
| Cache / state | Redis (shared conversation state), in-process caches |
| Auth | JWT Bearer (PyJWT), passlib Argon2 + bcrypt |
| OCR / docs | pytesseract, OpenCV, Pillow, pypdf, python-docx |
| Web client | React 18 (Create React App), react-router 6, axios, hand-rolled CSS, RTL/Arabic |
| Mobile client | Expo / React Native 0.81, React 19, React Navigation 7, expo-secure-store |
| Hosting | Render (`*.onrender.com`), Plesk-managed PostgreSQL at `chat.wareed.com.sa` |

### High-level architecture

```
                 ┌──────────────┐   ┌──────────────┐
                 │  React web   │   │ Expo mobile  │
                 └──────┬───────┘   └──────┬───────┘
                        │  HTTPS (JWT Bearer)
                        ▼
        ┌────────────────────────────────────────────┐
        │              FastAPI (app/main.py)           │
        │  /api/auth  /api/chat  /api/conversations    │
        │  /api/ocr   /api/internal/leads  /analytics  │
        └───────┬───────────────┬───────────────┬──────┘
                │               │               │
        ┌───────▼──────┐  ┌─────▼───────┐  ┌────▼─────────┐
        │ Message      │  │ RAG /        │  │ Lead / CRM   │
        │ runtime      │  │ knowledge    │  │ pipeline +   │
        │ orchestrator │  │ (lexical +   │  │ SSE events   │
        │ + routers    │  │ semantic)    │  │ + retry wkr  │
        └───────┬──────┘  └─────┬───────┘  └────┬─────────┘
                │               │               │
        ┌───────▼───────────────▼───────────────▼─────────┐
        │  PostgreSQL (users, conversations, messages,     │
        │  leads)   ·   Redis (conversation state)         │
        │  Excel/JSON knowledge base (app/data/)           │
        └──────────────────────────────────────────────────┘
```

### Database schema (`app/db/models.py`)

Four tables, UUID primary keys, sensible composite indexes and soft-delete flags:

- **users** — `email`/`password_hash` nullable (anonymous chat users allowed), `role` (admin/supervisor/staff, NULL = customer), `is_active`, profile fields. Cascade-deletes conversations.
- **conversations** — belongs to user, `title`, `is_archived` (soft delete), composite index `(user_id, is_archived)`.
- **messages** — role enum (user/assistant/system), `content`, `token_count` (cost tracking), `deleted_at` soft delete, index `(conversation_id, created_at)`.
- **leads** — captured when a customer shares a phone number; full CRM-sync lifecycle (`crm_status`, retries, external id, error fields), `status` enum (new/delivered/failed/closed), `metadata_json`.

Migrations are managed by Alembic (7 versions, initial schema → auth → profile → leads → roles → CRM fields → lead summary).

### API surface

`/api/auth` (register, login, refresh, me, profile, avatar) · `/api/chat` + `/api/chat/voice` + a dozen `/chat/*` stats/admin endpoints · `/api/conversations` (CRUD + messages + prescription upload) · `/api/ocr` (extract-text, extract-document) · `/api/internal/leads` (list, SSE stream, get, close, CRM retry) · `/api/internal/analytics/leads` · health/dashboard.

---

## Phase 2 — Goal & Purpose

**1. What does it do?** Wareed AI is an Arabic-first medical-lab assistant chatbot for **Wareed Medical Laboratories** (Saudi Arabia). Customers ask — in Saudi-dialect Arabic — about lab tests, symptoms, sample types, test preparation, packages, and branches. The bot answers **only** from a curated knowledge base (RAG, retrieval-grounded, no medical diagnosis), and when a customer shows buying intent it captures their phone number as a **sales lead** and pushes it to staff (realtime dashboard + CRM sync). It also reads uploaded prescriptions/medical documents via OCR + GPT-4o vision.

**2. Target users.** Two audiences: (a) **Wareed customers/patients** (web widget + mobile app), and (b) **Wareed internal staff** (leads dashboard, analytics) gated by role.

**3. Problem solved.** Deflects repetitive pre-sales questions, converts chat interest into qualified leads, and provides 24/7 Arabic self-service for a lab — without giving medical advice or, by current policy, prices (price answers are deliberately redirected to a phone number).

**4. Current state — Production, actively iterated, but cluttered.** It is deployed (Render + production Postgres), has auth, migrations, rate limiting, caching, CRM retry workers, and a dozen "PRODUCTION_READY / FINAL / PHASE_5" status docs. It is **not** an MVP — it's a maturing product carrying heavy development debris (see Phase 3). The mobile app and voice features are the least finished parts.

**5. Main data flow.**
```
User message ─▶ /api/chat ─▶ rate limiter ─▶ (anon user created if none)
   ─▶ message_runtime_orchestrator ─▶ question_router (intent: test / symptom /
      price / package / branch / FAQ / followup)
   ─▶ knowledge retrieval:  lexical match (rag_pipeline.retrieve) + semantic
      search (ChromaDB + multilingual MiniLM) over tests/packages/FAQ
   ─▶ openai_service.generate_response (system prompt = "Wareed", grounded only
      in retrieved context, Arabic, prices disabled)
   ─▶ persist messages (+ token_count) ─▶ if buying intent & phone present:
      create Lead ─▶ emit SSE event ─▶ CRM sync (+ retry worker)
   ─▶ response to client
```

---

## Phase 3 — Problem Detection

### 🔴 Security

1. **Private key committed to git.** `wareed_key.pem` (`-----BEGIN PRIVATE KEY-----`) is tracked (`git ls-files`). Anyone with repo access has the key. **Must be rotated and purged from history.**
2. **Internal endpoints fail _open_ by default.** `app/core/permissions.py:_api_key_ok()` returns `True` when `INTERNAL_LEADS_API_KEY` is empty ("dev mode → open"). If that env var is ever unset in production, **all `/api/internal/leads` and `/analytics` endpoints — customer phone numbers, conversation summaries, lead PII — become world-readable** with no credential. A safe default would deny.
3. **Credentials in URL query strings.** The SSE auth (`require_internal_access_sse`) accepts `?api_key=` and `?token=` query params. These leak into server/proxy access logs, browser history, and `Referer` headers. The web client passes the internal API key this way (per the frontend survey).
4. **`SECRET_KEY` has a usable insecure default** (`"change-me-in-production-use-long-random-secret"` in `config.py`). If unset in an environment, JWTs are forgeable. It is currently set in `.env`, but the default should hard-fail in production rather than silently sign tokens.
5. **No rate limiting on `/api/auth/login`.** The sliding-window limiter is applied to `/chat` and `/chat/voice` only — login is open to credential brute-force/stuffing.
6. **JWT in `localStorage` on web** (XSS-exposable) and **refresh tokens never rotated/revoked** — a leaked refresh token is valid for its full 7-day life; the web client doesn't even use the refresh endpoint (a 401 just logs the user out).
7. **Email enumeration** on `/register` ("البريد الإلكتروني مسجّل مسبقاً") lets an attacker probe which emails exist.
8. **Working tree holds live secrets** (`.env`, `.env.local` with real `OPENAI_API_KEY`, DB password, internal API key). These are correctly git-ignored, but the populated files sit in a OneDrive-synced folder — treat as sensitive.

_Positive:_ no `eval`/`exec`/`subprocess`/`os.system`, no string-built SQL — all DB access is parameterized SQLAlchemy ORM, so **no SQL/command-injection surface** was found. Passwords use Argon2 (with bcrypt fallback) and proper length validation. CORS is a fixed allow-list (though hardcoded in `main.py`, bypassing the `CORS_ORIGINS` setting which is therefore dead config).

### 🟠 Architecture

- **God-files.** `message_service.py` (~154 KB), `runtime/runtime_router.py` (~104 KB), `runtime/packages_resolver.py` (~96 KB), `api/chat.py` (~84 KB), `data/rag_pipeline.py` (~68 KB). These are very hard to test, review, or change safely and concentrate most of the project's risk.
- **Two parallel knowledge stacks, one of them dead.** The live runtime uses `app/data/knowledge_loader_v2.py` + `rag_pipeline.py` + `app/services/runtime/*_semantic_search.py`. The entire `app/knowledge_engine/` "v2 pipeline" is imported **only by the test suite**, and `runtime_loader_v2.py` has **zero importers anywhere** — it's an orphaned experiment.
- **Dead config / split sources of truth.** `settings.CORS_ORIGINS` is unused (real list hardcoded in `main.py`). Test data exists in three near-identical files (`analyses_main.xlsx`, `analysis_file.xlsx`, `analyses_with_prices.xlsx`) plus `praacise.xlsx` and a separate billing master — no single authoritative catalog.
- **In-memory rate limiter & caches** won't coordinate across multiple Render workers/instances (the project already moved conversation state to Redis for exactly this reason — rate limiting and smart-cache have the same multi-worker gap).

### 🟡 Code quality

- **`OpenAIService.generate_response` cost math is wrong/misleading**: it logs cost using "gpt-3.5-turbo pricing" constants while the configured model is `gpt-4`, so the cost dashboard under-reports by ~20–40×.
- **Temperature is silently clamped**: `self.temperature = min(0.1, OPENAI_TEMPERATURE)` forces temperature ≤ 0.1 regardless of the configured `0.7`. Intentional (deterministic answers) but contradicts config and comments — confusing.
- **Stub feature shipped**: `/api/chat/voice` has `# TODO: Implement speech-to-text conversion` — voice is accepted but not transcribed server-side. The mobile app's speech recognition is also a deliberate no-op outside dev builds.
- **Cleaner version sprawl**: `web_kb_cleaner_hard_impl / _v2 / _v3 / _v31` (~50 KB of superseded near-duplicates); `knowledge_base*.json` ×~10 (~600 KB each, only `_with_faq` is loaded); a 19.6 MB orphaned `rag_embeddings.json`; a fake hash-based `embedding_stub.py` used only by the dead pipeline.
- **Massive repository clutter**: 33 throwaway scripts in the repo root (`.tmp_*.py`, `_tmp_*.py`, `tmp_*.py`, `_patch_routing_v2.py`, `diagnose_*.py`, `_verify.py`), **184 `pytest-cache-files-*` directories**, two virtualenvs (`venv/`, `venv2/`), large committed runtime logs, an Excel lock file (`~$analyses_with_prices.xlsx`), and an `Untitled` file.
- **Frontend debris**: ~30 `console.*` left in (including unconditional base-URL logging), triplicated chat-widget components (V1/V2/V3, only V3 used), duplicated preview files, and a permanently-disabled SpeechRecognition block.
- **No automated tests on the clients** (web and mobile both have zero tests); the backend has a large pytest suite, but it is what keeps the *dead* knowledge_engine alive.

### 🟢 Performance

- ORM relationships use `lazy="selectin"` (avoids N+1 on conversation→messages) and there are good composite indexes — **no obvious N+1 in the data model**.
- Connection pooling is configured with `pool_pre_ping` and fast `connect_timeout` — solid.
- Semantic indexing is deferred to after health-check (good cold-start behaviour).
- Watch-outs: KB auto-reload polls file mtimes every 60 s; per-process in-memory caches duplicate work across workers; the giant resolver/router modules do a lot of synchronous Python work per request.

### Missing / incomplete features

Server-side speech-to-text (stubbed); web token-refresh flow (endpoint exists, client unused); per-test **Normal Range, Unit, and TAT** data (absent everywhere — see Phase 4); a real CRM provider (`CRM_PROVIDER=dummy`); role differentiation (admin/supervisor/staff are intentionally identical today); backend `is_admin`/role gating on the web admin (currently an email-allowlist stopgap).

---

## Phase 4 — Lab Test Analytics

**Deliverable:** `lab_tests_analytics_FRESH.xlsx` (in the project root). It consolidates the scattered lab data into one clean, RTL, Arabic-first workbook with the requested column structure and **zero formula errors** (verified via LibreOffice recalculation).

### Source files found (`app/data/`)

| File | Rows | Content |
|---|---|---|
| `analyses_with_prices.xlsx` | 574 | Clinical detail (benefit, sample type, category, symptoms, prep) + matched price — **richest catalog** |
| `praacise.xlsx` | 574 | Clean Arabic + English name + price |
| `analyses_main.xlsx` / `analysis_file.xlsx` | 574 | Near-duplicates of the clinical catalog |
| `analyses_prices.xls` | 1,808 | **Billing master** — Service Id, Service Type, Clinical Group, Fee, Active flag |
| `PAKAGE1.xlsx` | 122 | Specialised health packages |
| `branches.xlsx` | 119 | Riyadh-region branches, hours, map links |
| `faq.xlsx` | 18 | Customer Q&A |
| `LINKS.xlsx` | 312 | Source URLs from wareed.com.sa |

### What's tracked vs. missing

Tracked: Arabic/English test name, category, sample type, price, clinical benefit, preparation, complementary/alternative tests, and (in the billing master) test code + clinical group + active status.

**Gaps (absent in every source):** **Normal Range**, **Unit**, and per-test **Turnaround Time (TAT)** — the FAQ only gives a generic "12–24 h". These three are essential for result interpretation and are the highest-value data to add next.

### The fresh workbook (8 sheets)

`README` · `Lab Tests (Catalog)` — 574 tests: Test Name (AR/EN) | Test Code | Category | **Normal Range\*** | **Unit\*** | Sample Type | Price (SAR) | **TAT\*** | Status | Notes · `Billing Master (Ref)` — all 1,808 services · `Packages` · `Branches` · `FAQ` · `Data Gaps` · `Summary` (live formulas). Gap columns (\*) are highlighted yellow for manual entry. Test Code/Category/Fee were best-effort fuzzy-matched (token-sort ≥ 88) from the billing master — **535 of 574 (93%)** tests received a code; 475 carry a price; 18 categories; average price ≈ 691 SAR.

---

## Summary judgment

Wareed AI is a **genuinely capable, production-deployed Arabic medical-lab assistant** with a thoughtful, retrieval-grounded design, real lead-capture/CRM value, and a sound database schema. Its biggest liabilities are not its features but its **hygiene and a few sharp security defaults**: a committed private key, internal endpoints that fail open, credentials in URLs, and a repository buried under abandoned experiments and throwaway files. Cleaning those up — and filling the Normal Range/Unit/TAT data gap — would move it from "works in production" to "maintainable and trustworthy in production." See `IMPROVEMENT_ROADMAP.md` for the prioritized plan.
