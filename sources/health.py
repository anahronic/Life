"""
Health / freshness checks for the Ayalon monitoring pipeline (methodology v2).

Invariants:
  1. Health checks NEVER call any external API.
  2. Traffic freshness is the age of the newest SUCCESSFUL segment
     observation (segment_observations.status = 'ok'), using the time the
     measurement refers to (observed_at_utc), not the time a row was written.
     A cached or re-recorded response can therefore never look fresh.
  3. Collector liveness is judged separately from the newest collection
     cycle of any status.
  4. States: healthy / partial / stale / no_data / collector_down / empty / error.
"""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional

TRAFFIC_FRESH_S = 600        # newest measurement <= 10 min -> current
TRAFFIC_STALE_S = 7200       # <= 2 h -> stale; older -> no_data
COLLECTOR_ALIVE_S = 900      # a cycle (any status) within 15 min -> collector alive


def _default_db_path() -> str:
    return os.environ.get("HISTORY_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "monitor.sqlite3"))


def _utc_now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _parse_iso_ts(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _query(db_path: str, sql: str, args=()) -> Optional[sqlite3.Row]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, args).fetchone()
    finally:
        con.close()


def compute_traffic_health(db_path: str = None, now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Compute traffic health from SQLite only.

    Returns dict: status, age_s (newest valid measurement), last_traffic_ts,
    traffic_source_id, last_cycle_status, last_cycle_ts, last_cycle_error,
    collector_alive, message.
    """
    db_path = db_path or _default_db_path()
    now = now_ts if now_ts is not None else _utc_now_ts()
    out: Dict[str, Any] = {
        "status": "empty", "age_s": None, "last_traffic_ts": None, "traffic_source_id": None,
        "last_cycle_status": None, "last_cycle_ts": None, "last_cycle_error": None,
        "collector_alive": False, "segments_ok": None, "segments_total": None, "message": "",
    }
    try:
        cyc = _query(db_path, "SELECT * FROM collection_cycles ORDER BY started_at_utc DESC LIMIT 1")
        obs = _query(
            db_path,
            "SELECT observed_at_utc, provider FROM segment_observations WHERE status = 'ok' ORDER BY observed_at_utc DESC LIMIT 1",
        )
    except sqlite3.OperationalError as exc:
        # DB missing or not yet migrated to v2
        out["status"] = "empty"
        out["message"] = f"No v2 data: {exc}"
        return out
    except Exception as exc:  # pragma: no cover - defensive
        out["status"] = "error"
        out["message"] = str(exc)[:200]
        return out

    if cyc is not None:
        cts = _parse_iso_ts(cyc["started_at_utc"])
        out.update({
            "last_cycle_status": cyc["status"],
            "last_cycle_ts": cyc["started_at_utc"],
            "last_cycle_error": cyc["error"],
            "segments_ok": cyc["segments_ok"],
            "segments_total": cyc["segments_total"],
            "collector_alive": cts is not None and now - cts <= COLLECTOR_ALIVE_S,
        })

    if obs is not None:
        ts = _parse_iso_ts(obs["observed_at_utc"])
        if ts is None:
            out["status"] = "error"
            out["message"] = f"Cannot parse timestamp: {obs['observed_at_utc']}"
            return out
        out["age_s"] = int(round(now - ts))
        out["last_traffic_ts"] = obs["observed_at_utc"]
        out["traffic_source_id"] = obs["provider"]

    if cyc is None and obs is None:
        out["status"] = "empty"
        out["message"] = "No collection cycles recorded yet"
        return out
    if not out["collector_alive"]:
        out["status"] = "collector_down"
    elif out["age_s"] is None or out["age_s"] > TRAFFIC_STALE_S:
        out["status"] = "no_data"
    elif out["age_s"] > TRAFFIC_FRESH_S:
        out["status"] = "stale"
    elif out["last_cycle_status"] == "ok":
        out["status"] = "healthy"
    else:
        out["status"] = "partial"
    out["message"] = (
        f"status={out['status']} newest_measurement_age_s={out['age_s']} "
        f"last_cycle={out['last_cycle_status']} ({out['segments_ok']}/{out['segments_total']})"
    )
    return out


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


def get_health_status(db_path: str = None) -> Dict[str, Any]:
    """Full health check — SQLite + cache, NO external API calls."""
    traffic = compute_traffic_health(db_path)
    cache = check_cache_status()
    return {
        "status": traffic["status"],
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "checks": {"traffic_freshness": traffic, "cache": cache},
    }


def get_quick_status(db_path: str = None) -> str:
    """One-word status. NEVER calls any external API."""
    return compute_traffic_health(db_path or _default_db_path())["status"]


def get_quick_status_readonly(db_path: str = None) -> str:
    """Alias kept for backward compatibility."""
    return get_quick_status(db_path)
