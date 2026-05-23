# Wareed AI — Improvement Roadmap

_Companion to `PROJECT_ANALYSIS_REPORT.md` · 2026-05-22._
_Priorities: 🔴 fix immediately · 🟡 this sprint · 🟢 future · 💡 new features._

---

## 🔴 Critical — fix immediately

These are security / data-loss / trust risks. Order matters.

1. **Rotate and purge `wareed_key.pem`.**
   It is committed to git (`-----BEGIN PRIVATE KEY-----`). Treat the key as compromised: generate a new key/cert, replace it wherever it's used, remove the file from the repo, add `*.pem` to `.gitignore`, and scrub it from git history (`git filter-repo` / BFG). Rotate anything that key protected.

2. **Make internal auth fail _closed_.**
   In `app/core/permissions.py`, `_api_key_ok()` returns `True` when `INTERNAL_LEADS_API_KEY` is empty. Change the default to **deny** in production (allow the open path only when `DEBUG=True`). Otherwise a missing env var silently exposes all customer-lead PII on `/api/internal/leads*` and `/api/internal/analytics/*`.

3. **Stop sending credentials in URL query strings.**
   The SSE stream accepts `?api_key=` / `?token=`. Prefer a short-lived, single-purpose SSE token minted by an authenticated POST, or move realtime to a transport that supports headers. At minimum, never log full URLs with query strings and don't use the long-lived internal API key as a query param from the browser.

4. **Rotate the secrets currently sitting in the working tree.**
   `.env` / `.env.local` contain a live `OPENAI_API_KEY`, DB password, and internal API key inside a OneDrive-synced folder. Rotate them, confirm they're only in untracked files, and consider a secrets manager for production.

5. **Add rate limiting + lockout to `/api/auth/login`.**
   Reuse the existing sliding-window limiter (keyed by IP + email) and add exponential backoff / temporary lockout to stop credential stuffing.

6. **Hard-fail on the default `SECRET_KEY` in production.**
   Refuse to start if `SECRET_KEY == "change-me-..."` and `DEBUG` is false, so JWTs can never be signed with the public default.

---

## 🟡 High priority — this sprint

7. **Fix the cost dashboard.** `OpenAIService.generate_response` computes cost with gpt-3.5 pricing while running `gpt-4`; correct the per-model rates so token/cost tracking is real.

8. **Resolve the temperature contradiction.** `min(0.1, OPENAI_TEMPERATURE)` overrides the configured `0.7`. Decide intentionally and make config + comment + code agree.

9. **Delete dead code (low-risk, high-clarity win).** Remove the orphaned `app/knowledge_engine/` v2 pipeline + `runtime_loader_v2.py` (imported only by tests), the superseded `web_kb_cleaner_hard_{impl,v2,v3}.py`, redundant `knowledge_base*.json` (keep only the loaded `_with_faq` + fallback), the 19.6 MB `rag_embeddings.json`, and `embedding_stub.py`. Update/retire the tests that keep them alive.

10. **Purge repo clutter & add `.gitignore` rules.** Remove the 33 root throwaway scripts, 184 `pytest-cache-files-*` dirs, `venv/` + `venv2/`, committed `*.log`, `~$*.xlsx`, and `Untitled`. Add `pytest-cache-files-*/`, `*.pem`, `.env.local` patterns.

11. **Establish one source of truth for lab data.** Collapse `analyses_main` / `analysis_file` / `analyses_with_prices` into a single maintained catalog (the new `lab_tests_analytics_FRESH.xlsx` is a starting point) and document which file the runtime loads.

12. **Move rate-limit + cache state to Redis.** Redis is already a dependency for conversation state; in-memory limiter/cache don't coordinate across Render workers.

13. **Finish or hide the voice feature.** Either implement server-side STT for `/api/chat/voice` (remove the TODO) or disable the entry points so it doesn't appear functional.

14. **Add a smoke-test CI gate.** Even a thin pytest + lint (black/flake8 are already in requirements) run on push would catch regressions in the god-files.

---

## 🟢 Nice to have — future

15. **Break up the god-files.** Incrementally extract `message_service.py`, `runtime_router.py`, `packages_resolver.py`, and `api/chat.py` into focused modules with unit tests around the seams.
16. **Real role differentiation.** admin/supervisor/staff are identical today; implement least-privilege (e.g. only supervisors close/CRM-retry) and replace the web email-allowlist admin gate with the backend `role`.
17. **Refresh-token rotation + revocation list** (and move web tokens out of `localStorage` toward in-memory + httpOnly refresh).
18. **Frontend cleanup:** strip `console.*`, remove triplicated widgets/preview duplicates and the disabled SpeechRecognition block; add a few component tests.
19. **Observability:** structured request IDs, error tracking (e.g. Sentry), and a real per-model token/cost metric feeding the existing dashboard.
20. **Unify the category taxonomy** (Arabic clinical categories vs. billing "unit" groups) into one scheme used by both the catalog and retrieval.

---

## 💡 Feature suggestions (to make this the best version)

1. **Per-test reference ranges & units in the bot.** _What:_ fill the Normal Range/Unit gap and let the assistant explain "what's normal" per analyte (with age/sex variants). _Value:_ the single biggest content gap; directly improves answer quality and customer trust. _Complexity:_ Medium (data sourcing is the work, not code).

2. **Per-test turnaround time (TAT).** _What:_ structured TAT per test so the bot answers "when will my result be ready?" precisely instead of "12–24 h". _Value:_ a top customer question; reduces call-center load. _Complexity:_ Low–Medium.

3. **Result-PDF interpreter.** _What:_ extend the existing OCR + GPT-4o vision path to read a customer's result report and explain (not diagnose) each value against reference ranges. _Value:_ high differentiation; deepens the OCR investment already built. _Complexity:_ High (safety guardrails + ranges required).

4. **Online booking / home-sample scheduling.** _What:_ turn a captured lead into an actual appointment or home-collection booking with branch + slot selection. _Value:_ converts intent to revenue inside the chat; natural next step after lead capture. _Complexity:_ High (scheduling backend + branch integration).

5. **Smart package recommender.** _What:_ given symptoms/goals, suggest the most relevant health package (data already in `PAKAGE1.xlsx` + semantic index). _Value:_ higher basket size, better UX. _Complexity:_ Medium.

6. **Price-quote workflow (policy-gated).** _What:_ since prices are deliberately disabled in chat, offer an opt-in "send me a quote" that emails/SMSs an itemized estimate instead of the phone redirect. _Value:_ keeps the no-price-in-chat policy while still serving the most common question. _Complexity:_ Medium.

7. **WhatsApp / channel expansion.** _What:_ expose the same engine over WhatsApp Business (huge in KSA). _Value:_ meets customers where they are; reuses all backend logic. _Complexity:_ Medium–High (provider integration).

8. **Staff lead-quality scoring & analytics.** _What:_ score/segment captured leads (intent strength, test value) and enrich the analytics dashboard with conversion funnels. _Value:_ helps the sales team prioritize; leverages existing lead/CRM data. _Complexity:_ Medium.

9. **Branch-aware answers with maps & live hours.** _What:_ use `branches.xlsx` to answer "nearest open branch" with map links and 24-h flags. _Value:_ practical, frequently asked, data already present. _Complexity:_ Low.

10. **Admin content console for the knowledge base.** _What:_ a small UI to edit tests/FAQs/packages and trigger the existing KB auto-reload, replacing manual Excel/JSON edits. _Value:_ lets non-engineers maintain the catalog (closes the "single source of truth" loop). _Complexity:_ Medium.

---

### Suggested execution order

Do **🔴 #1–#6 now** (a focused security pass, mostly hours not days). Then in the sprint, pair the **cleanup (#9–#11)** with the **two data wins (features #1–#2 / Normal Range, Unit, TAT)** — together they remove most risk and close the biggest quality gap. Larger bets (result interpreter, booking, WhatsApp) follow once the foundation is clean.
