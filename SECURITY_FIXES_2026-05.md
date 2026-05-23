# Security Fixes — May 2026

Status of the four critical issues. Three are fully applied in code; the git-history
purge is prepared and 90% done but must be finalized from your Windows terminal
(the cloud sandbox can't complete it — see "Why" below).

---

## ✅ #2 — Internal API key now fails CLOSED
`app/core/permissions.py` → `_api_key_ok()` no longer grants access when
`INTERNAL_LEADS_API_KEY` is unset. Open access is allowed **only** when
`DEBUG=True` (local dev); in production a missing key now **denies** access.
Also switched to a constant-time comparison (`secrets.compare_digest`).

## ✅ #3 — Login rate limiting (slowapi), 5/min per IP
- `slowapi==0.1.9` added to `requirements.txt`
- `app/core/limiter.py` (new) — shared limiter keyed by client IP (uses
  `RATE_LIMIT_STORAGE_URI`/`REDIS_URL` if set, else in-memory)
- `app/main.py` — registers `app.state.limiter` + the 429 handler
- `app/api/auth.py` — `@limiter.limit("5/minute")` on `/auth/login`
- Verified: 5 requests return 200, the 6th returns **429**.

> Run `pip install -r requirements.txt` to install slowapi before next deploy.

## ✅ #4 — API keys moved out of URL query params → Authorization headers
- Backend `require_internal_access_sse` no longer accepts `?token=` / `?api_key=`;
  SSE auth is **header-only** (`Authorization: Bearer …` or `X-Internal-Api-Key`).
- Frontend `InternalLeadsDashboard.js` — the realtime stream no longer uses
  `EventSource` with a key in the URL. It now uses a `fetch` + `ReadableStream`
  reader that sends credentials in headers. (Verified: parses as valid JSX; no
  `stream?token=` / `stream?api_key=` remain anywhere in `src/`.)
- Stale docstrings in `internal_leads.py` updated to match.

## ⏳ #1 — Purge `wareed_key.pem` from git history (FINALIZE ON WINDOWS)

**What's already done for you:**
- `git filter-repo` was run (on a fast local copy) and the rewritten, **pem-free**
  history was loaded into your repo as the branch **`_cleaned_main`**
  (commit `d21a8b2…`). Verified: `wareed_key.pem` is absent from every commit there.
- `*.pem` was added to `.gitignore`.
- Your real `main` is **untouched** (still `b6f7cc5…`) and all your uncommitted
  work is intact — nothing was lost.

**Why I couldn't finish from here:** this folder is a OneDrive-backed mount that
refuses file *unlinks* (`rm` → "Operation not permitted"). Git can't finish an
index/ref update without deleting its own lock files, so the final `reset` failed
and left some stale `.lock` files behind.

### Step 1 — Delete the stale lock files (PowerShell, in the repo folder)
```powershell
Remove-Item .git\index.lock -Force -ErrorAction SilentlyContinue
Remove-Item .git\objects\maintenance.lock -Force -ErrorAction SilentlyContinue
Remove-Item .git\refs\heads\_locktest.lock -Force -ErrorAction SilentlyContinue
Remove-Item _pre_filter_backup.bundle.lock -Force -ErrorAction SilentlyContinue
```
(The `index.lock` one is important — until it's gone, normal git commands here
will say "Another git process seems to be running".)

### Step 2 — Point `main` at the cleaned history (keeps your working changes)
```powershell
git reset --mixed _cleaned_main      # moves main to pem-free history; working tree untouched
git branch -D _cleaned_main          # remove the temp branch
del wareed_key.pem                   # remove the key file from disk
```

### Step 3 — Fully purge the old objects locally (optional but recommended)
```powershell
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git log --all --oneline -- wareed_key.pem   # should print NOTHING
```

### Step 4 — Update the remote (rewrites GitHub history)
```powershell
git push --force origin main
```
> All collaborators must re-clone (or hard-reset) after this — old clones still
> contain the key.

### Step 5 — ROTATE THE KEY (most important)
History rewriting does **not** make the leaked key safe — assume it's compromised.
Generate a new key/cert, replace it everywhere it's used, and revoke the old one.
The key was also exposed on GitHub, so treat it as public.

---

## Verifying the code fixes
```bash
pip install -r requirements.txt
python -c "import app.main"          # imports cleanly
# (the rate-limit + auth changes are covered by app/core/limiter.py and app/api/auth.py)
```

## Files changed in this pass
```
app/core/permissions.py          (#2 fail-closed, #4 header-only SSE)
app/core/limiter.py   (new)      (#3 shared limiter)
app/main.py                      (#3 limiter wiring)
app/api/auth.py                  (#3 5/min on /login)
app/api/internal_leads.py        (#4 docstring accuracy)
requirements.txt                 (#3 slowapi)
frontend-react/src/components/InternalLeadsDashboard.js   (#4 header-based SSE)
.gitignore                       (*.pem)
```
