"""
Analysis Usage Tracker
======================
Tracks how many times each medical test/analysis was used in RAG context
(delivered to the user). Used for dashboard and chat insights.
"""

import logging
import threading
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AnalysisUsageTracker:
    """Thread-safe counter: analysis key -> count."""

    def __init__(self):
        self._counts: Dict[str, int] = defaultdict(int)
        self._names: Dict[str, Dict[str, str]] = {}  # key -> { name_ar, name_en }
        self._lock = threading.RLock()

    def _key(self, name_ar: str, name_en: str) -> str:
        """Stable key for an analysis (prefer Arabic name)."""
        ar = (name_ar or "").strip()
        en = (name_en or "").strip()
        if ar:
            return f"ar:{ar}"
        if en:
            return f"en:{en}"
        return "unknown"

    def record(self, name_ar: str = "", name_en: str = "") -> None:
        """Record one usage of an analysis (e.g. when included in RAG context)."""
        key = self._key(name_ar, name_en)
        with self._lock:
            self._counts[key] += 1
            if key not in self._names:
                self._names[key] = {
                    "name_ar": (name_ar or "").strip() or "—",
                    "name_en": (name_en or "").strip() or "—",
                }

    def get_stats(self) -> Dict[str, Any]:
        """Return usage per analysis, sorted by count descending."""
        with self._lock:
            items = [
                {
                    "name_ar": self._names.get(k, {}).get("name_ar", "—"),
                    "name_en": self._names.get(k, {}).get("name_en", "—"),
                    "count": c,
                }
                for k, c in self._counts.items()
            ]
        items.sort(key=lambda x: x["count"], reverse=True)
        total_uses = sum(x["count"] for x in items)
        return {
            "by_analysis": items,
            "total_analyses_used": len(items),
            "total_uses": total_uses,
        }

    def get_top(self, n: int = 20) -> List[Dict[str, Any]]:
        """Top N most used analyses (for chat or widget)."""
        stats = self.get_stats()
        return (stats.get("by_analysis") or [])[:n]

    def clear(self) -> None:
        """Reset all counts (e.g. for testing)."""
        with self._lock:
            self._counts.clear()
            self._names.clear()
        logger.info("Analysis usage tracker cleared.")


_tracker: Optional[AnalysisUsageTracker] = None


def get_analysis_usage_tracker() -> AnalysisUsageTracker:
    global _tracker
    if _tracker is None:
        _tracker = AnalysisUsageTracker()
    return _tracker
