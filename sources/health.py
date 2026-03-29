"""
Health / freshness checks for the Ayalon monitoring pipeline.

Invariants:
  1. Health checks NEVER call TomTom or any external API.
  2. Traffic freshness is determined solely by the last SUCCESSFUL
     traffic run in SQLite (filtered by traffic_source_id).
  3. Fuel pipeline data cannot influence traffic health status.
  4. States are explicit and distinguishable: healthy / degraded / stale /
     collector_down / empty / error.
"""

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


# ── Thresholds (seconds) ────────────────────────────────────────────────
#  Collector fires every 5 min.  Allow some slack.
TRAFFIC_FRESH_S = 600        # ≤ 10 min → healthy
TRAFFIC_DEGRADED_S = 1800    # ≤ 30 min → degraded  (a few missed cycles)
TRAFFIC_STALE_S = 7200       # ≤  2 h   → stale     (collector likely down)
# >2 h → collector_down


def _default_db_path() -> str:
    return os.environ.get("HISTORY_DB_PATH", "data/monitor.sqlite3")


def _utc_now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _parse_iso_ts(s: Optional[str]) -> Optional[float]:
    """Parse an ISO-8601 timestamp string to Unix epoch, or None."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


# ── Core: last successful traffic snapshot ──────────────────────────────

def _last_successful_traffic_run(db_path: str) -> Optional[Dict[str, Any]]:
    """Return the most recent run row that has a valid traffic_source_id
    and non-null traffic timestamp.  This is the single source of truth
    for traffic freshness.

    Returns dict with keys: recorded_at_utc, tomtom_fetched_at, traffic_source_id,
    tomtom_age_s, data_timestamp_utc — or None if no valid traffic run exists.
    """
    try:
        con = sqlite3.connect(db_path, timeout=10)
        con.row_factory = sqlite3.Row
        row = con.execute(
            """
            SELECT recorded_at_utc, tomtom_fetched_at, traffic_source_id,
                   tomtom_age_s, data_timestamp_utc
            FROM runs
            WHERE traffic_source_id IS NOT NULL
              AND traffic_source_id NOT LIKE '%:error%'
              AND tomtom_fetched_at IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        con.close()
        return dict(row) if row else None
    except Exception:
        return None


# ── Health state computation ────────────────────────────────────────────

def compute_traffic_health(db_path: str = None) -> Dict[str, Any]:
    """Compute the full traffic health status from SQLite only.

    Returns a dict with:
      status   — one of: healthy, degraded, stale, collector_down, empty, error
      age_s    — seconds since the last valid traffic snapshot (or None)
      message  — human-readable explanation
      last_traffic_ts — ISO timestamp of last valid traffic snaphot
      traffic_source_id — e.g. 'tomtom_flow_v4'
    """
    if db_path is None:
        db_path = _default_db_path()

    run = _last_successful_traffic_run(db_path)

    if run is None:
        return {
            "status": "empty",
            "age_s": None,
            "message": "No valid traffic runs found in database",
            "last_traffic_ts": None,
            "traffic_source_id": None,
        }

    # Prefer tomtom_fetched_at (actual data time), fall back to recorded_at_utc
    ts_str = run.get("tomtom_fetched_at") or run.get("recorded_at_utc")
    ts = _parse_iso_ts(ts_str)
    if ts is None:
        return {
            "status": "error",
            "age_s": None,
            "message": f"Cannot parse timestamp: {ts_str}",
            "last_traffic_ts": ts_str,
            "traffic_source_id": run.get("traffic_source_id"),
        }

    age_s = _utc_now_ts() - ts

    if age_s < TRAFFIC_FRESH_S:
        status = "healthy"
    elif age_s < TRAFFIC_DEGRADED_S:
        status = "degraded"
    elif age_s < TRAFFIC_STALE_S:
        status = "stale"
    else:
        status = "collector_down"

    return {
        "status": status,
        "age_s": int(age_s),
        "message": f"Last valid traffic snapshot {int(age_s)}s ago ({status})",
        "last_traffic_ts": ts_str,
        "traffic_source_id": run.get("traffic_source_id"),
    }


# ── Cache layer status (informational, no external calls) ──────────────

def check_cache_status() -> Dict[str, Any]:
    """Check cache directory presence and size — purely filesystem."""
    cache_dir = os.path.join(os.path.dirname(__file__), "_cache")
    cache_ok = os.path.isdir(cache_dir)
    file_count = 0
    if cache_ok:
        try:
            file_count = len(os.listdir(cache_dir))
        except Exception:
            pass
    return {
        "status": "ok" if cache_ok else "missing",
        "cache_dir": cache_dir,
        "file_count": file_count,
        "writable": cache_ok and os.access(cache_dir, os.W_OK),
    }


# ── Aggregated health (replaces old full_health_check) ──────────────────

def get_health_status(db_path: str = None) -> Dict[str, Any]:
    """Full health check — SQLite + cache, NO external API calls."""
    traffic = compute_traffic_health(db_path)
    cache = check_cache_status()
    return {
        "status": traffic["status"],
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "checks": {
            "traffic_freshness": traffic,
            "cache": cache,
        },
    }


# ── One-word quick helpers ──────────────────────────────────────────────

def get_quick_status(db_path: str = None) -> str:
    """Return one-word status: healthy / degraded / stale / collector_down / empty / error.

    NEVER calls TomTom or any external API.
    """
    return compute_traffic_health(db_path or _default_db_path())["status"]


def get_quick_status_readonly(db_path: str = None) -> str:
    """Alias kept for backward compatibility with traffic_app.py."""
    return get_quick_status(db_path)
