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
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.db import init_db

# Initialize logging (console only, level from .env)
configure_logging()
logger = logging.getLogger(__name__)


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
    logger.info("Application shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    lifespan=lifespan
)


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://wareed-ai-preview.onrender.com",
        "https://ai-chatbot-wareed-1.onrender.com",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
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
