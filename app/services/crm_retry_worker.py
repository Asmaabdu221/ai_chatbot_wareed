from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Dict

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.crm_sync_service import get_retryable_failed_lead_ids, retry_crm_sync

logger = logging.getLogger(__name__)

_WORKER_THREAD: threading.Thread | None = None
_STOP_EVENT = threading.Event()
_LOCK = threading.Lock()


def start_crm_retry_worker() -> None:
    global _WORKER_THREAD
    if SessionLocal is None:
        return
    if not settings.CRM_RETRY_WORKER_ENABLED:
        logger.info("crm_retry_worker | disabled")
        return
    with _LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            return
        _STOP_EVENT.clear()
        _WORKER_THREAD = threading.Thread(
            target=_worker_loop,
            name="crm-retry-worker",
            daemon=True,
        )
        _WORKER_THREAD.start()
        logger.info(
            "crm_retry_worker | started | interval=%ss | batch_size=%s",
            settings.CRM_RETRY_WORKER_INTERVAL_SECONDS,
            settings.CRM_RETRY_BATCH_SIZE,
        )


def stop_crm_retry_worker() -> None:
    global _WORKER_THREAD
    with _LOCK:
        if _WORKER_THREAD is None:
            return
        _STOP_EVENT.set()
        _WORKER_THREAD.join(timeout=5)
        _WORKER_THREAD = None
        logger.info("crm_retry_worker | stopped")


def process_retry_batch() -> Dict[str, int]:
    if SessionLocal is None:
        return {"selected": 0, "processed": 0, "succeeded": 0, "failed": 0}

    db = SessionLocal()
    try:
        lead_ids = get_retryable_failed_lead_ids(
            db,
            now=datetime.now(timezone.utc),
            limit=int(settings.CRM_RETRY_BATCH_SIZE),
        )
        succeeded = 0
        failed = 0
        for lead_id in lead_ids:
            result = retry_crm_sync(lead_id, db)
            if result.get("ok"):
                succeeded += 1
            else:
                failed += 1
        processed = succeeded + failed
        if processed > 0:
            logger.info(
                "crm_retry_worker | batch | selected=%s | succeeded=%s | failed=%s",
                len(lead_ids),
                succeeded,
                failed,
            )
        return {
            "selected": len(lead_ids),
            "processed": processed,
            "succeeded": succeeded,
            "failed": failed,
        }
    except Exception as exc:
        logger.warning("crm_retry_worker | batch_error | %s", exc)
        return {"selected": 0, "processed": 0, "succeeded": 0, "failed": 0}
    finally:
        db.close()


def _worker_loop() -> None:
    interval = max(1, int(settings.CRM_RETRY_WORKER_INTERVAL_SECONDS))
    while not _STOP_EVENT.is_set():
        process_retry_batch()
        _STOP_EVENT.wait(interval)
