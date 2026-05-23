# Render Deployment Checklist — Wareed AI (Lab RAG v2)

_Audit date: 2026-05-23. Do NOT deploy from here — this documents what to do in your Render dashboard / local git._

## Recommendation: ChromaDB persistence — **Option B (rebuild on startup if empty)**

**Why B over A/C, given this codebase:**
- There is **no `render.yaml`/`Procfile`** — the service is configured in the Render dashboard. Option A would require introducing a blueprint *and* a paid persistent disk (single-instance only).
- The app **already** rebuilds its other vector indexes on startup (`_deferred_semantic_startup_after_healthy` in `main.py`), so B matches the established pattern — zero new infra.
- The lab index is tiny/cheap to build (574 docs, ~138k tokens, **~$0.003**, one batch, ~30s) and the engine **degrades gracefully** to Layers 1+3 while it builds.

**Implemented (already in code):**
- `main.py` → `_deferred_lab_vector_build()` runs in the background after startup (guarded by `USE_LAB_RAG_V2` and skipped when `EMBEDDING_BACKEND=none`). It's **idempotent** (skips already-indexed tests) and refreshes the engine's vector retriever when done.
- The Chroma path is now **env-overridable** (`CHROMA_PERSIST_PATH`) — so you can later switch to **Option A** (persistent disk) with *no code change*: just set `CHROMA_PERSIST_PATH=/data/chromadb` and mount a disk there.
- `EMBEDDING_BACKEND=none` cleanly disables the vector layer (**Option C** fallback) — Layers 1 (27,364 synonym terms) + 3 (808 symptom rows) keep working.

---

## [ ] 1. Environment variables (Render dashboard → Environment)

| Variable | Value | Status |
|---|---|---|
| `OPENAI_API_KEY` | (your key) | exists in `.env` — **confirm it's set in Render** |
| `USE_LAB_RAG_V2` | `true` | **NEW** — required to enable the new pipeline |
| `EMBEDDING_BACKEND` | `openai` | **NEW** (`openai` \| `local` \| `none`) |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | **NEW** (has a code default; set to be explicit) |
| `CHROMA_PERSIST_PATH` | *(leave empty for Option B)* | **NEW** — set to `/data/chromadb` only if using a persistent disk |
| `SECRET_KEY` | (strong random) | required already — confirm set (login breaks on the insecure default) |
| `DATABASE_URL` | (Postgres URL) | required already |
| `REDIS_URL` | (managed Redis) | required already (shared conversation state) |
| `INTERNAL_LEADS_API_KEY` | (strong key) | required already — **must be set** (internal endpoints now fail closed) |

All four NEW vars are documented in `.env.example`.

## [ ] 2. render.yaml / start command

- **Option B (recommended): no `render.yaml` needed.** Keep the dashboard start command, e.g.:
  ```
  gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 1 -b 0.0.0.0:$PORT --timeout 120
  ```
  Use **`-w 1` (one web worker)** so the startup index build runs once (multiple workers would each call OpenAI — wasteful + racey). Scale via instances, not workers, or use Option A.
- **Option A (only if you want persistence):** add a `render.yaml` with a disk and set `CHROMA_PERSIST_PATH`:
  ```yaml
  services:
    - type: web
      name: wareed-ai
      env: python
      disk:
        name: chromadb-data
        mountPath: /data/chromadb
        sizeGB: 1
  ```
  then set env `CHROMA_PERSIST_PATH=/data/chromadb`. (Disks pin the service to a single instance.)

## [ ] 3. Git — commit the new files (they are currently UNTRACKED)

These are not yet in git and **won't reach Render** until committed:
```
git add app/data/sources/excel/tests_REBUILT.xlsx
git add app/utils/arabic_normalizer.py app/data/lab_data_loader.py \
        app/services/intent_classifier.py app/services/prompt_factory.py \
        app/services/lab_retrieval_engine.py app/services/context_builder.py \
        app/services/lab_rag_integration.py app/scripts/__init__.py \
        app/scripts/build_vector_index.py tests/test_rag_pipeline.py
git add app/core/config.py app/main.py app/api/chat.py app/services/ocr_service.py \
        requirements.txt .env.example .gitignore RAG_INTEGRATION_NOTES.md
# Stop committing rebuilt vector indexes (30 stale files are currently tracked):
git rm -r --cached app/data/runtime/chroma 2>/dev/null || true
```
> Reminder: the stale `.git/index.lock` from the earlier history-rewrite must be deleted on Windows first, or git commands here will fail.

## [ ] 4. Verify after deploy (Render Shell)

```bash
pip install -r requirements.txt          # ensures slowapi, tiktoken, etc.
python -m app.scripts.build_vector_index --dry-run   # 574 docs, ~138k tokens, 1 batch, ~$0.003
# Option B auto-builds on startup; to build manually / force:
python -m app.scripts.build_vector_index             # idempotent
python -m app.scripts.build_vector_index --rebuild   # drop + re-index
```

## [ ] 5. Smoke tests (hit after deploy)

```
GET  https://<app>/                         -> {"status":"running"}
GET  https://<app>/api/health               -> {"api_status":"healthy","openai_configured":true}
POST https://<app>/api/auth/login  x6       -> 6th returns 429 (rate limit works)
POST https://<app>/api/chat   {"message":"كم سعر تحليل CBC"}     -> grounded reply (price gated)
POST https://<app>/api/chat   {"message":"عندي تعب وخمول وشحوب"} -> symptom-based tests + lead CTA
POST https://<app>/api/chat   {"message":"أريد تحليل حديد"}      -> clarifying question (disambiguation)
```
Watch logs for: `Lab RAG v2 engine warmed up` then `Lab RAG v2 vector index ready`.

---

## Memory & startup (measured)

- Lab engine warm-up: **~6.6s**, **~121 MB RSS** (pandas + lab data; this runs synchronously in startup but *after* `is_healthy=True`).
- Background vector build (Option B): **~30s**, non-blocking, **~$0.003** per cold start (ephemeral disk → every restart; persistent disk → once).
- The full app also loads the existing KB + (lazily) `chromadb` + `sentence-transformers` (runtime semantic search). **Plan: 512 MB is the floor; 1 GB recommended** given two vector stacks + pandas.

## Other deployment fixes applied in code

- **Tesseract path** (`ocr_service.py`) was hardcoded to a Windows path (`C:\Program Files\...`) — it would break OCR on Linux. Now resolves cross-platform: `TESSERACT_CMD` env → Windows install (on Windows) → `which tesseract` → `tesseract`. On Render, ensure the tesseract binary is available (it's an apt package; add a build step or buildpack if OCR is used).
- All new RAG paths use `pathlib`/`PROJECT_ROOT` — no Windows/absolute paths. (`build_style_system.py` has a `C:\...` only inside a docstring example — harmless.)

## Manual actions summary (not code)
1. Set the 4 NEW env vars (+ confirm existing required ones) in Render.
2. Set start command to 1 web worker (or adopt Option A disk for multi-instance).
3. Commit the untracked new files + `tests_REBUILT.xlsx`; un-track `app/data/runtime/chroma`.
4. Ensure `tesseract` is installed on the Render instance if OCR is used.
