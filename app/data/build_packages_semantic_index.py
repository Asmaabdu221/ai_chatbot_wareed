"""Build Chroma semantic index for packages domain.

Usage:
    python -m app.data.build_packages_semantic_index
"""

from __future__ import annotations

import logging

from app.services.runtime.packages_resolver import load_packages_records
from app.services.runtime.packages_semantic_search import get_packages_semantic_search

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s - %(message)s")
    records = load_packages_records()
    if not records:
        logger.error("No package records loaded. Aborting.")
        return 1

    active_records = [r for r in records if bool(r.get("is_active", True))]
    if active_records:
        records = active_records

    service = get_packages_semantic_search()
    service.build_or_refresh(records)
    if not service.available:
        logger.error("Semantic index build unavailable: %s", service.unavailable_reason)
        return 2

    logger.info("Packages semantic index is ready | records=%d", len(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

