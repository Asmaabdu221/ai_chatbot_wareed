"""
Central logging configuration. Python built-in logging only.
Console output (stdout). Log level from .env via settings.
No file logging (per task scope).
"""

import logging
import sys

from app.core.config import settings


# Required format: Timestamp | Level | Module name | Message
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> None:
    """
    Configure root logger: console only, level from LOG_LEVEL.
    Safe to call once at app startup.
    """
    level_name = (getattr(settings, "LOG_LEVEL", "INFO") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FMT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(level)

    root = logging.getLogger()
    root.setLevel(level)
    # Remove any existing handlers to avoid duplicates
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(console)


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given module (dependency-safe)."""
    return logging.getLogger(name)
