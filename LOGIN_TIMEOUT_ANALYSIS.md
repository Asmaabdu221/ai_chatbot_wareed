# Login Timeout Analysis — "timeout of 15000ms exceeded"

## Step-by-Step Technical Analysis

### 1) Is the backend not receiving the request?

**Unlikely.** If the backend were unreachable, the error would typically be:
- `ECONNREFUSED` / "Network Error"
- `ERR_CONNECTION_REFUSED`

A **timeout** means the request was sent and the client waited 15 seconds without receiving a response. The request likely reaches the backend.

---

### 2) Is the API baseURL or endpoint incorrect?

**No.**
- Development: `baseURL = ""` (proxy forwards to `http://127.0.0.1:8000`)
- Endpoint: `POST /api/auth/login`
- `package.json` proxy: `"proxy": "http://127.0.0.1:8000"`

The proxy forwards `/api/*` to the backend. Configuration is correct.

---

### 3) Is there a CORS configuration issue?

**No.** CORS blocks the *response* from being read by the browser. You would see a CORS error in the console, not a timeout. CORS origins include `http://localhost:3000` and `http://127.0.0.1:3000`.

---

### 4) Is the endpoint failing to return a response?

**Yes — this is the symptom.** The endpoint does not return within 15 seconds.

---

### 5) Is there a long-running blocking process exceeding 15 seconds?

**Yes — most likely root cause.**

The login endpoint uses `Depends(get_db)`. The `get_db` dependency does:

```python
db = SessionLocal()  # ← SYNCHRONOUS, BLOCKING
```

`SessionLocal()` obtains a connection from the SQLAlchemy pool. If the pool is empty, it opens a **new TCP connection to PostgreSQL**.

If PostgreSQL is:
- Not running
- On a different host/port
- Blocked by firewall
- Unreachable

the connection attempt can **block for the system TCP timeout** (often 60–120+ seconds). This runs in the main thread and **blocks the asyncio event loop**, so no response is sent until the connection fails or succeeds.

---

### 6) Is there a missing "await" in an async FastAPI endpoint?

**No.** The login endpoint is `async` and uses `await run_in_threadpool(_login_sync)`. The DB work runs in a thread pool. The blocking occurs earlier, in `get_db` → `SessionLocal()`.

---

### 7) Is an exception occurring without returning a response?

**No.** An unhandled exception would produce a 500 response. A timeout means no response at all — the request is still waiting.

---

## Most Likely Root Cause

**Database connection blocking.**

- `DATABASE_URL` points to `localhost:5434` (PostgreSQL).
- If PostgreSQL is not running on port 5434, or the connection is slow/unreachable, `SessionLocal()` blocks when creating a new connection.
- There is no `connect_timeout`, so the attempt can hang for the default TCP timeout.
- The frontend times out after 15 seconds before the backend responds.

---

## Fixes

### Fix 1: Add `connect_timeout` to DATABASE_URL (recommended)

Makes connection attempts fail quickly instead of hanging:

```
postgresql+psycopg2://chat_local:chat1234@localhost:5434/wareed_db?connect_timeout=5
```

### Fix 2: Increase login timeout on the frontend

Auth requests may need more time on slow networks. Increase the timeout for auth calls.

### Fix 3: Verify PostgreSQL

Ensure PostgreSQL is running and listening on port 5434:

```powershell
# Check if something is listening on 5434
netstat -an | findstr 5434
```
