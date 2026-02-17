"""
Database Session Management
Handles database connection, session lifecycle, and pooling
"""

import logging
from typing import Generator
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from app.core.config import settings

logger = logging.getLogger(__name__)


def create_database_engine():
    """
    Create SQLAlchemy engine with production-ready configuration
    
    Connection pooling is enabled for PostgreSQL to manage concurrent connections efficiently.
    For production, this prevents connection exhaustion and improves performance.
    
    Returns:
        SQLAlchemy engine instance, or None if DATABASE_URL is not set
    """
    database_url = (settings.DATABASE_URL or "").strip()
    if not database_url:
        logger.info("⚠️ DATABASE_URL not set - database disabled (demo mode)")
        return None

    # Production configuration for PostgreSQL
    engine_kwargs = {
        "echo": settings.DEBUG,  # Log SQL queries in debug mode
        "future": True,  # Use SQLAlchemy 2.0 style
    }

    # Connection pooling configuration for PostgreSQL
    if database_url.startswith("postgresql"):
        engine_kwargs.update({
            "poolclass": QueuePool,
            "pool_size": getattr(settings, "DB_POOL_SIZE", 5),
            "max_overflow": getattr(settings, "DB_MAX_OVERFLOW", 10),
            "pool_timeout": getattr(settings, "DB_POOL_TIMEOUT", 30),
            "pool_recycle": getattr(settings, "DB_POOL_RECYCLE", 3600),
            "pool_pre_ping": True,  # Test connections before using (handles disconnects)
            "connect_args": {"connect_timeout": 10},  # Fail fast if DB unreachable (prevents login timeout)
        })
        logger.info("🔗 PostgreSQL connection pooling configured (size=5, max_overflow=10)")

    try:
        engine = create_engine(database_url, **engine_kwargs)
        logger.info("✅ Database engine created: %s", database_url.split("@")[-1] if "@" in database_url else "local")
        return engine
    except Exception as e:
        logger.error("❌ Failed to create database engine: %s", e)
        raise


# Create engine instance (None if DATABASE_URL not set)
engine = create_database_engine()

# Create session factory (only if engine exists)
SessionLocal = (
    sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,  # Prevent lazy loading issues after commit
        future=True,  # SQLAlchemy 2.0 style
    )
    if engine is not None
    else None
)


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI endpoints to get database session.
    When DATABASE_URL is not set, yields None (callers must handle).
    """
    if SessionLocal is None:
        yield None
        return
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """
    Initialize database connection and validate connectivity.
    No-op if DATABASE_URL is not set (demo mode).
    """
    if engine is None:
        logger.info("⚠️ Database disabled - DATABASE_URL not set (demo mode)")
        return
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ Database connection validated successfully")
    except Exception as e:
        error_msg = f"Failed to connect to database: {str(e)}"
        logger.error("❌ %s", error_msg)
        logger.error("⚠️ Ensure PostgreSQL is running and DATABASE_URL is correct")
        raise RuntimeError(error_msg) from e


# Event listeners (only when engine exists)
if engine is not None:
    @event.listens_for(engine, "connect")
    def _receive_connect(dbapi_conn, connection_record):
        logger.debug("🔌 New database connection established")

    @event.listens_for(engine, "checkout")
    def _receive_checkout(dbapi_conn, connection_record, connection_proxy):
        logger.debug("📤 Connection checked out from pool")
