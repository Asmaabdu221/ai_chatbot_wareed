"""
Usage Monitoring & Cost Tracker
================================
Tracks chat requests by model (openai/cache/router), tokens, and estimated cost
for dashboard and cost control.
"""

import logging
import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Approx GPT-3.5-turbo: $0.0005/1K input, $0.0015/1K output → ~$0.001/1K blended
COST_PER_1K_TOKENS = 0.001
MODELS_WITH_COST = ("gpt-3.5-turbo", "gpt-4", "gpt-4-turbo", "openai")


def _estimate_cost_usd(model: str, tokens_used: int) -> float:
    if tokens_used <= 0:
        return 0.0
    if any(m in model.lower() for m in ("gpt-4", "gpt-4-turbo")):
        return tokens_used * (30.0 / 1_000_000)  # rough GPT-4 input blend
    return tokens_used * (COST_PER_1K_TOKENS / 1000.0)


class UsageTracker:
    """Thread-safe usage and cost tracker."""

    def __init__(self):
        self._lock = threading.RLock()
        self._total_requests = 0
        self._total_tokens = 0
        self._total_cost_usd = 0.0
        self._by_model: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "tokens": 0, "cost_usd": 0.0}
        )
        # Last 24h: list of (ts, model, tokens) for hourly breakdown
        self._recent: List[Dict[str, Any]] = []
        self._recent_max = 50000

    def record(self, model: str, tokens_used: int = 0) -> None:
        model = model or "unknown"
        cost = _estimate_cost_usd(model, tokens_used) if tokens_used else 0.0
        ts = time.time()
        with self._lock:
            self._total_requests += 1
            self._total_tokens += tokens_used
            self._total_cost_usd += cost
            self._by_model[model]["count"] += 1
            self._by_model[model]["tokens"] += tokens_used
            self._by_model[model]["cost_usd"] += cost
            self._recent.append({"ts": ts, "model": model, "tokens": tokens_used})
            if len(self._recent) > self._recent_max:
                self._recent = self._recent[-self._recent_max :]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            by_model = {
                k: {"count": v["count"], "tokens": v["tokens"], "cost_usd": round(v["cost_usd"], 6)}
                for k, v in self._by_model.items()
            }
            return {
                "total_requests": self._total_requests,
                "total_tokens": self._total_tokens,
                "total_cost_usd": round(self._total_cost_usd, 4),
                "by_model": by_model,
            }

    def get_dashboard(self) -> Dict[str, Any]:
        """Stats for dashboard: totals, by_model, last 24h hourly counts."""
        now = time.time()
        cutoff_24h = now - (24 * 3600)
        with self._lock:
            by_model = {
                k: {"count": v["count"], "tokens": v["tokens"], "cost_usd": round(v["cost_usd"], 6)}
                for k, v in self._by_model.items()
            }
            last_24h = [e for e in self._recent if e["ts"] >= cutoff_24h]
            # Hourly buckets (last 24 hours)
            hourly: Dict[int, int] = defaultdict(int)
            for e in last_24h:
                hour_ago = int((now - e["ts"]) / 3600)
                if 0 <= hour_ago < 24:
                    hourly[hour_ago] += 1
            requests_last_24h = [
                {"hours_ago": i, "requests": hourly[i]}
                for i in range(24)
            ]
            requests_last_24h.sort(key=lambda x: x["hours_ago"])
        return {
            "total_requests": self._total_requests,
            "total_tokens": self._total_tokens,
            "total_cost_usd": round(self._total_cost_usd, 4),
            "by_model": by_model,
            "requests_last_24h": requests_last_24h,
            "requests_in_last_24h": len(last_24h),
        }


_tracker: Optional[UsageTracker] = None


def get_usage_tracker() -> UsageTracker:
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker
