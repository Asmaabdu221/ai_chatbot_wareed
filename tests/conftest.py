"""
Shared pytest fixtures for the Wareed AI test suite.

Provides a module-scoped in-memory SQLite engine and a function-scoped
Session for tests that need DB access without a live PostgreSQL instance.

SQLite quirk: PostgreSQL ENUM types are patched to String(20) for
compatibility.  The patch is applied once before create_all() and
restored after the module-scope engine is torn down.
"""

from __future__ import annotations

from typing import Generator

import pytest
from sqlalchemy import String, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Lead, LeadStatus


@pytest.fixture(scope="session")
def sqlite_engine():
    """One in-memory SQLite engine for the whole test session."""
    engine = create_engine("sqlite:///:memory:", future=True)

    # Swap PostgreSQL ENUM column to plain String so SQLite is happy
    Lead.__table__.c.status.type = String(20)

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)

    # Restore ORM column type so other imports see the original Enum
    from sqlalchemy import Enum as SAEnum
    Lead.__table__.c.status.type = SAEnum(
        LeadStatus,
        name="lead_status",
        create_type=False,
        values_callable=lambda x: [e.value for e in x],
    )


@pytest.fixture()
def db(sqlite_engine) -> Generator[Session, None, None]:
    """Fresh session per test; rolls back after each test."""
    SessionLocal = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()
