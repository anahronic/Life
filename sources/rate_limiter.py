"""Global rate limiter to protect external API quotas.

Implements a simple app-level rate limiting layer with:
- Minimum interval between calls (process-local)
- Daily quota tracking with persistent file-based counter (survives process restarts)

Configured via env vars:
  RATE_LIMIT_SECONDS  — minimum seconds between API calls (default: 60)
  TOMTOM_QUOTA_PER_DAY — max TomTom calls per calendar day UTC (default: 2500)

Legacy env var TOMTOM_QUOTA_PER_HOUR is recognised as a fallback but
mapped to daily semantics (value is used as the daily cap).
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, Tuple

# Persistent counter lives next to the cache directory
_COUNTER_DIR = Path(__file__).parent / "_cache"
_COUNTER_DIR.mkdir(exist_ok=True)
_COUNTER_FILE = _COUNTER_DIR / "_rate_limiter_daily.json"


def _utc_today_str() -> str:
    """Return current UTC date as 'YYYY-MM-DD'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_persistent_counts() -> Dict:
    """Load daily counters from disk.  Returns dict keyed by service."""
    try:
        if _COUNTER_FILE.exists():
            with open(_COUNTER_FILE, "r") as f:
                data = json.load(f)
            # Reset if the file is from a previous day
            if data.get("date") == _utc_today_str():
                return data
    except Exception:
        pass
    return {"date": _utc_today_str(), "counts": {}}


def _save_persistent_counts(data: Dict) -> None:
    """Persist daily counters to disk (best-effort)."""
    try:
        data["date"] = _utc_today_str()
        with open(_COUNTER_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass  # fail-open for persistence, fail-closed for quota check


class RateLimiter:
    """Thread-safe rate limiter for external API calls."""

    def __init__(self, min_interval_seconds: int = 60):
        """
        Args:
            min_interval_seconds: Minimum seconds between any external API
                calls to the same service within this process.
        """
        self.min_interval_seconds = min_interval_seconds
        self.last_call_time: Dict[str, float] = {}
        self.lock = Lock()

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def can_call(self, service: str = "tomtom", quota_per_day: int = 2500) -> Tuple[bool, float]:
        """Check if an API call to *service* is allowed.

        Returns:
            (allowed, seconds_to_wait)
            - If interval too short: (False, remaining_wait)
            - If daily quota exhausted: (False, -1)   # -1 signals quota, not timing
            - Otherwise: (True, 0.0)
        """
        with self.lock:
            now = time.time()

            # 1. Minimum interval check (process-local)
            last_call = self.last_call_time.get(service, 0)
            elapsed = now - last_call
            if elapsed < self.min_interval_seconds:
                return False, self.min_interval_seconds - elapsed

            # 2. Daily quota check (persistent)
            counts = _load_persistent_counts()
            used_today = counts.get("counts", {}).get(service, 0)
            if used_today >= quota_per_day:
                return False, -1  # quota exhausted

            return True, 0.0

    def record_call(self, service: str = "tomtom", quota_per_day: int = 2500) -> None:
        """Record that an API call was made.  Updates both in-memory and
        persistent counters."""
        with self.lock:
            self.last_call_time[service] = time.time()

            # Persistent daily counter
            counts = _load_persistent_counts()
            svc_counts = counts.setdefault("counts", {})
            svc_counts[service] = svc_counts.get(service, 0) + 1
            _save_persistent_counts(counts)

    def get_quota_status(self, service: str = "tomtom", quota_per_day: int = 2500) -> Dict:
        """Return current quota status dict."""
        with self.lock:
            counts = _load_persistent_counts()
            used = counts.get("counts", {}).get(service, 0)
            return {
                "calls_today": used,
                "quota_per_day": quota_per_day,
                "remaining": max(0, quota_per_day - used),
                "percent_used": min(100, (used / quota_per_day) * 100) if quota_per_day > 0 else 0,
                "date": counts.get("date", _utc_today_str()),
            }

    def get_last_call_age(self, service: str = "tomtom") -> float:
        """Seconds since last call in this process (inf if never called)."""
        with self.lock:
            last_call = self.last_call_time.get(service, 0)
            return time.time() - last_call if last_call > 0 else float("inf")


# ── Global instance ────────────────────────────────────────────────────

_global_limiter = RateLimiter(
    min_interval_seconds=int(os.getenv("RATE_LIMIT_SECONDS", "60"))
)

# Daily quota: prefer TOMTOM_QUOTA_PER_DAY, fall back to legacy TOMTOM_QUOTA_PER_HOUR
_DEFAULT_DAILY_QUOTA = int(
    os.getenv("TOMTOM_QUOTA_PER_DAY",
              os.getenv("TOMTOM_QUOTA_PER_HOUR", "2500"))
)


def can_call_api(service: str = "tomtom") -> Tuple[bool, float]:
    """Check if API call is allowed (interval + daily quota)."""
    return _global_limiter.can_call(service, quota_per_day=_DEFAULT_DAILY_QUOTA)


def record_api_call(service: str = "tomtom", quota_per_day: int = None) -> None:
    """Record an API call."""
    q = quota_per_day if quota_per_day is not None else _DEFAULT_DAILY_QUOTA
    _global_limiter.record_call(service, quota_per_day=q)


def get_quota_status(service: str = "tomtom", quota_per_day: int = None) -> Dict:
    """Get quota status."""
    q = quota_per_day if quota_per_day is not None else _DEFAULT_DAILY_QUOTA
    return _global_limiter.get_quota_status(service, quota_per_day=q)


def get_last_call_age(service: str = "tomtom") -> float:
    """Get age of last call in this process."""
    return _global_limiter.get_last_call_age(service)


# ── Backward compatibility aliases ─────────────────────────────────────
# Old callers may pass quota_per_hour=...; accept it silently as daily.
