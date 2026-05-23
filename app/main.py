import asyncio
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from app.api.chat import router as chat_router
from app.api import conversations
from app.api.auth import router as auth_router
from app.api.ocr import router as ocr_router
from app.api.internal_leads import router as internal_leads_router
from app.api.internal_analytics import router as internal_analytics_router
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.limiter import limiter
from app.db import init_db

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Initialize logging (console only, level from .env)
configure_logging()
logger = logging.getLogger(__name__)


async def _deferred_semantic_startup_after_healthy(app: FastAPI) -> None:
    """Start semantic background indexing only after app is marked healthy."""
    try:
        while not bool(getattr(app.state, "is_healthy", False)):
            await asyncio.sleep(0.25)

        await asyncio.sleep(0.5)
        from app.services.runtime.tests_resolver import load_tests_records
        from app.services.runtime.tests_semantic_search import get_tests_semantic_search
        from app.services.runtime.packages_resolver import load_packages_records
        from app.services.runtime.packages_semantic_search import get_packages_semantic_search

        tests = [r for r in load_tests_records() if isinstance(r, dict) and bool(r.get("is_active", True))]
        packages = [r for r in load_packages_records() if isinstance(r, dict) and bool(r.get("is_active", True))]

        if tests:
            get_tests_semantic_search().build_or_refresh(tests)
        if packages:
            get_packages_semantic_search().build_or_refresh(packages)
    except Exception as exc:
        logger.warning("deferred semantic startup skipped | reason=%s", exc.__class__.__name__)


async def _deferred_lab_vector_build() -> None:
    """(Re)build the Lab RAG v2 OpenAI vector index in the background when empty.

    Idempotent (skips already-indexed tests) and non-blocking. After building,
    the engine's vector retriever is refreshed so vectors are used without a restart.
    """
    try:
        from app.scripts.build_vector_index import build_index
        from app.services.lab_retrieval_engine import get_lab_retrieval_engine, VectorRetriever
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, build_index)
        get_lab_retrieval_engine().vector_retriever = VectorRetriever()
        logger.info("✅ Lab RAG v2 vector index ready")
    except Exception as exc:
        logger.warning("Lab RAG v2 vector build skipped | reason=%s", exc.__class__.__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager
    Handles startup and shutdown events
    """
    # Application startup
    logger.info("Application startup")
    try:
        logger.info("Starting WAREED Medical AI Chatbot")
        
        # Initialize and validate database connection
        init_db()
        logger.info("✅ Database connection initialized successfully")
        
        # Initialize Knowledge Base V2 with RAG support
        logger.info("📚 Loading Knowledge Base...")
        from app.data.knowledge_loader_v2 import get_knowledge_base, get_test_statistics
        
        kb = get_knowledge_base()
        stats = get_test_statistics()
        
        logger.info("✅ Knowledge Base loaded successfully:")
        logger.info(f"   📊 Tests: {stats['total_tests']}")
        logger.info(f"   ❓ FAQs: {stats['total_faqs']}")
        logger.info(f"   💵 Tests with prices: {stats['tests_with_price']}")
        logger.info(f"   📂 Categories: {stats['categories']}")
        logger.info(f"   💰 Price range: {stats['price_range']['min']:.0f} - {stats['price_range']['max']:.0f} SAR")
        logger.info(f"   🔖 Version: {stats['version']}")
        
        # Smart Cache: clear on startup to avoid stale "no info" responses after retrieval fixes
        logger.info("📦 Preloading Smart Cache with FAQs...")
        from app.services.smart_cache import get_smart_cache
        cache = get_smart_cache()
        cache.clear()
        preloaded = cache.preload_from_faqs(kb.faqs)
        logger.info(f"   ✅ Cache preloaded with {preloaded} FAQ entries")

        # Start Knowledge Base auto-reload (reload when JSON file changes)
        from app.services.kb_auto_reload import start_kb_auto_reload
        start_kb_auto_reload()

        # Register running event loop with the lead event bus (enables SSE broadcasts)
        from app.services.lead_events import lead_event_bus
        lead_event_bus.set_event_loop(asyncio.get_event_loop())
        logger.info("✅ Lead event bus ready (SSE stream: /api/internal/leads/stream)")
        from app.services.crm_retry_worker import start_crm_retry_worker
        start_crm_retry_worker()

        # Mark app healthy first, then trigger semantic indexing in background.
        app.state.is_healthy = True
        asyncio.create_task(_deferred_semantic_startup_after_healthy(app))

        # Lab RAG v2 warm-up (guarded by USE_LAB_RAG_V2; default off -> no-op).
        if getattr(settings, "USE_LAB_RAG_V2", False):
            try:
                from app.services.lab_rag_integration import warm_up as _lab_warm
                _lab_warm()
                logger.info("✅ Lab RAG v2 engine warmed up")
            except Exception as _lab_e:
                logger.warning("Lab RAG v2 warm-up skipped: %s", _lab_e)
            # Option B: rebuild the OpenAI vector index in the background if empty
            # (Render disk is ephemeral). Deferred so it never blocks health checks.
            if str(getattr(settings, "EMBEDDING_BACKEND", "openai")).strip().lower() != "none":
                asyncio.create_task(_deferred_lab_vector_build())
        
    except Exception as e:
        logger.error("Failed to initialize application: %s", str(e))
        raise
    
    yield
    
    # Application shutdown
    try:
        from app.services.kb_auto_reload import stop_kb_auto_reload
        stop_kb_auto_reload()
    except Exception:
        pass
    try:
        from app.services.crm_retry_worker import stop_crm_retry_worker
        stop_crm_retry_worker()
    except Exception:
        pass
    logger.info("Application shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    lifespan=lifespan
)
app.state.is_healthy = False

# Rate limiting (slowapi): register the shared limiter and its 429 handler.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log unhandled exceptions (no sensitive data)."""
    logger.error("Unhandled exception: %s", str(exc), exc_info=True)
    from fastapi.responses import JSONResponse
    detail = str(exc) if settings.DEBUG else "Internal server error"
    return JSONResponse(status_code=500, content={"detail": detail})

# Request logging middleware: method, path, status, duration (ms)
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    logger.info("Incoming request %s %s", request.method, request.url.path)
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info("Response %s %s - %s - %.2f ms", request.method, request.url.path, response.status_code, duration_ms)
    return response

allow_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://ai-chatbot-wareed.onrender.com",
    "https://ai-chatbot-wareed-1.onrender.com",
    "https://wareed-ai-preview.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files: profile avatars
_uploads_dir = Path(__file__).resolve().parent.parent / "static" / "uploads"
if _uploads_dir.exists():
    app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")

# Media files: public user-uploaded content (/media/*)
_media_dir = Path(__file__).resolve().parent.parent / "media"
_media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_media_dir)), name="media")

# Include routers
app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(conversations.router, prefix="/api", tags=["Conversations"])
app.include_router(chat_router, prefix="/api", tags=["Chat"])
app.include_router(ocr_router, prefix="/api", tags=["OCR"])
app.include_router(internal_leads_router, prefix="/api", tags=["Internal Leads"])
app.include_router(internal_analytics_router, prefix="/api", tags=["Internal Analytics"])

@app.get("/")
def health_check():
    return {
        "status": "running",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION
    }

@app.get("/api/health")
def api_health_check():
    return {
        "api_status": "healthy",
        "openai_configured": bool(settings.OPENAI_API_KEY)
    }


# شاشة مراقبة الاستهلاك (Usage Dashboard)
_dashboard_path = Path(__file__).resolve().parent.parent / "static" / "usage-dashboard.html"


@app.get("/dashboard", include_in_schema=False)
def usage_dashboard():
    """شاشة مراقبة استهلاك الشات والتكلفة."""
    if _dashboard_path.exists():
        return FileResponse(_dashboard_path, media_type="text/html; charset=utf-8")
    return {"error": "Dashboard file not found. Ensure static/usage-dashboard.html exists."}
