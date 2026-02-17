"""
Knowledge Base Auto-Reload
==========================
Background thread that checks the KB file modification time and reloads
the knowledge base when the file changes. Clears context cache on reload.
"""

import logging
import threading
import time
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_stop_event: Optional[threading.Event] = None
_thread: Optional[threading.Thread] = None
_last_mtime: Optional[float] = None


def _run_watcher() -> None:
    global _last_mtime
    interval = max(15, getattr(settings, "KB_AUTO_RELOAD_INTERVAL_SECONDS", 60))
    while _stop_event and not _stop_event.is_set():
        _stop_event.wait(timeout=interval)
        if _stop_event.is_set():
            break
        try:
            from app.data.knowledge_loader_v2 import get_kb_file_mtime, reload_knowledge_base
            mtime = get_kb_file_mtime()
            if mtime is None:
                continue
            if _last_mtime is not None and mtime > _last_mtime:
                logger.info("📁 Knowledge base file changed, reloading...")
                if reload_knowledge_base():
                    _last_mtime = mtime
            elif _last_mtime is None:
                _last_mtime = mtime
        except Exception as e:
            logger.debug("KB auto-reload check: %s", e)


def start_kb_auto_reload() -> bool:
    """
    Start background thread that periodically checks KB file and reloads if changed.
    Returns True if started, False if disabled or already running.
    """
    global _stop_event, _thread, _last_mtime
    if not getattr(settings, "KB_AUTO_RELOAD_ENABLED", True):
        logger.info("Knowledge base auto-reload is disabled (KB_AUTO_RELOAD_ENABLED=false)")
        return False
    if _thread is not None and _thread.is_alive():
        return False
    try:
        from app.data.knowledge_loader_v2 import get_kb_file_mtime
        _last_mtime = get_kb_file_mtime()
    except Exception:
        _last_mtime = None
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_run_watcher, daemon=True, name="kb-auto-reload")
    _thread.start()
    interval = getattr(settings, "KB_AUTO_RELOAD_INTERVAL_SECONDS", 60)
    logger.info("🔄 Knowledge base auto-reload started (interval=%ss)", interval)
    return True


def stop_kb_auto_reload() -> None:
    """Signal the watcher thread to stop (e.g. on app shutdown)."""
    global _stop_event
    if _stop_event:
        _stop_event.set()
