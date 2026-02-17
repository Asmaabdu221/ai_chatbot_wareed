"""
Database Base Module
Defines the declarative base and common model functionality
"""

from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Base class for all database models
    Provides common fields and functionality for all tables
    """
    pass


class TimestampMixin:
    """
    Mixin that adds created_at timestamp to models
    Uses database-level timezone-aware timestamps
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="Record creation timestamp (UTC)"
    )


class UpdateTimestampMixin(TimestampMixin):
    """
    Mixin that adds both created_at and updated_at timestamps
    Updated_at automatically updates on record modification
    """
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Record last update timestamp (UTC)"
    )
