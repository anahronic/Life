"""Ayalon headless collector — the ONLY authorised path that calls TomTom.

Invariants:
  1. TomTom is called exclusively from _fetch_traffic() in this module.
  2. A failed or empty fetch never overwrites the last-known-good snapshot.
  3. Each cycle writes a structured diagnostic summary to stdout/journald.
  4. Rate-limit / quota exhaustion is detected early and logged — no retry storm.
"""

import argparse
import json
import os
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from methodology import AyalonModel
from sources import tomtom
from sources.air_quality import get_air_quality_for_ayalon, get_cached_air_quality
from sources.fuel_govil import (
    fetch_current_fuel_price_ils_per_l as fetch_current_fuel_price,
    get_cached_fuel_price,
)
from sources.history_store import HistoryStore
from sources.rate_limiter import get_quota_status
from sources.secure_config import SecureConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso_to_ts(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _log(level: str, event: str, **kw: Any) -> None:
    """Emit a structured JSON log line (collected by journald)."""
    entry = {
        "ts": _utc_now_iso(),
        "level": level,
        "event": event,
        **{k: v for k, v in kw.items() if v is not None},
    }
    print(json.dumps(entry, default=str), flush=True)


# ---------------------------------------------------------------------------
# Data fetchers (each handles its own fallback)
# ---------------------------------------------------------------------------

def _fetch_traffic(api_key: Optional[str], traffic_mode: str) -> Dict[str, Any]:
    """Fetch traffic from TomTom (or cache fallback).

    Returns the payload dict.  On failure falls back to the most recent
    *validated* cached aggregate; if even that is absent, raises.
    """
    cache_ttl_s = _env_int("CACHE_TTL_SECONDS", 300)

    # Early check: skip TomTom call if daily quota is exhausted
    if api_key and traffic_mode == "flow":
        quota = get_quota_status("tomtom")
        if quota.get("remaining", 1) <= 0:
            _log("WARN", "quota_exhausted", service="tomtom",
                 calls_today=quota.get("calls_today"),
                 quota_per_day=quota.get("quota_per_day"))
            cached = tomtom.get_cached_ayalon_segments(mode=traffic_mode, max_age_s=24 * 3600)
            if cached:
                out = dict(cached)
                out["errors"] = ["Daily TomTom quota exhausted — serving cached data"]
                out["_fetch_status"] = "quota_exhausted"
                return out
            raise RuntimeError("TomTom quota exhausted and no cached data available")

    try:
        result = tomtom.get_ayalon_segments(api_key, cache_ttl_s=cache_ttl_s, mode=traffic_mode)
        result["_fetch_status"] = "ok"
        return result
    except Exception as exc:
        exc_msg = str(exc)
        _log("WARN", "traffic_fetch_failed", error=exc_msg[:200])

        # Classify the failure
        fetch_status = "fetch_error"
        if "rate-limited" in exc_msg.lower() or "429" in exc_msg:
            fetch_status = "rate_limited"
        elif "403" in exc_msg or "401" in exc_msg or "forbidden" in exc_msg.lower():
            fetch_status = "auth_error"

        cached = tomtom.get_cached_ayalon_segments(mode=traffic_mode, max_age_s=24 * 3600)
        if cached:
            out = dict(cached)
            out["errors"] = [f"Using cached traffic due to: {exc_msg[:120]}"]
            out["_fetch_status"] = fetch_status
            return out
        raise


def _fetch_air_quality() -> Dict[str, Any]:
    try:
        return get_air_quality_for_ayalon(cache_ttl_s=600)
    except Exception as exc:
        _log("WARN", "air_quality_fetch_failed", error=str(exc)[:200])
        cached = get_cached_air_quality(max_age_s=24 * 3600)
        if cached:
            out = dict(cached)
            out["error"] = out.get("error") or "Using cached air quality due to live fetch failure"
            return out
        raise


def _fetch_fuel_price() -> Dict[str, Any]:
    try:
        return fetch_current_fuel_price()
    except Exception as exc:
        _log("WARN", "fuel_fetch_failed", error=str(exc)[:200])
        cached = get_cached_fuel_price(max_age_s=14 * 86400)
        if cached:
            out = dict(cached)
            out["source_id"] = str(out.get("source_id", "fuel")) + ":cached"
            return out
        raise


# ---------------------------------------------------------------------------
# Main collection cycle
# ---------------------------------------------------------------------------

def collect_once() -> Dict[str, Any]:
    """Run one full collection cycle.

    Returns a diagnostic summary dict.
    """
    cycle_start = _utc_now_iso()
    _log("INFO", "cycle_start")

    history = HistoryStore()
    model = AyalonModel()

    api_key = SecureConfig.get_tomtom_api_key()

    traffic_mode = os.getenv("TRAFFIC_MODE")
    if not traffic_mode:
        traffic_mode = "flow" if api_key else "sample"
    if traffic_mode == "flow" and not api_key:
        _log("WARN", "no_api_key_fallback_sample")
        traffic_mode = "sample"

    # ── Fetch all three sources ──
    tomtom_data = _fetch_traffic(api_key, traffic_mode)
    aq_data = _fetch_air_quality()
    fuel_data = _fetch_fuel_price()

    fetch_status = tomtom_data.pop("_fetch_status", "ok")

    now_ts = time.time()
    tomtom_ts = _parse_iso_to_ts(tomtom_data.get("fetched_at"))
    tomtom_age_s = (now_ts - tomtom_ts) if tomtom_ts else None

    segments = tomtom_data.get("segments") or []
    price = fuel_data.get("price_ils_per_l")

    if not segments or price is None:
        _log("ERROR", "insufficient_inputs",
             segments_count=len(segments),
             fuel_price=price)
        raise RuntimeError("collector: insufficient inputs (traffic segments or fuel price missing)")

    src_ids = {
        "traffic": tomtom_data.get("source_id"),
        "air": aq_data.get("source_id"),
        "fuel": fuel_data.get("source_id"),
    }

    results = model.run_model(
        segments,
        data_timestamp_utc=tomtom_data.get("fetched_at"),
        source_ids=src_ids,
        p_fuel_ils_per_l=float(price),
        vehicle_count_mode=tomtom_data.get("vehicle_count_mode"),
    )

    history.record_run(
        results=results,
        tomtom_data=tomtom_data,
        aq_data=aq_data,
        fuel_data=fuel_data,
        tomtom_age_s=tomtom_age_s,
    )

    summary = {
        "collected_at_utc": _utc_now_iso(),
        "cycle_start": cycle_start,
        "traffic_mode": traffic_mode,
        "traffic_fetch_status": fetch_status,
        "tomtom_age_s": round(tomtom_age_s, 1) if tomtom_age_s is not None else None,
        "segments_count": len(segments),
        "sources": src_ids,
        "pipeline_run_id": results.get("pipeline_run_id"),
        "delta_T_total_h": results.get("delta_T_total_h"),
        "leakage_ils": results.get("leakage_ils"),
        "db_write": "ok",
    }

    _log("INFO", "cycle_complete", **summary)
    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Ayalon monitor: headless collector")
    p.add_argument("--once", action="store_true", help="Run one collection cycle")
    args = p.parse_args()

    if not args.once:
        p.error("Only --once is supported. Use systemd timer/cron for scheduling.")

    try:
        out = collect_once()
        # Human-readable one-liner for journalctl quick scan
        print(f"OK  mode={out['traffic_mode']}  fetch={out['traffic_fetch_status']}  "
              f"age={out.get('tomtom_age_s', '?')}s  segs={out['segments_count']}  "
              f"run={out['pipeline_run_id']}", flush=True)
        return 0
    except Exception as exc:
        _log("ERROR", "cycle_failed", error=str(exc)[:300],
             traceback=traceback.format_exc()[-500:])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
