"""Ayalon headless collector (methodology v2) — the ONLY path that calls traffic APIs.

Invariants:
  1. Traffic providers are called only from _fetch_traffic() in this module.
  2. Only fresh provider responses become observations.  A cached or failed
     fetch is never written as a measurement (v1 re-recorded a 24 h cache).
  3. Every reference segment gets its own status; a cycle is 'ok' only when
     all segments were measured, 'partial' when some were, 'failed' otherwise.
  4. The same provider snapshot can be stored only once per segment
     (UNIQUE(segment_id, segment_version, provider, provider_snapshot)).
  5. Fetch time, provider data time, processing time and DB write time are
     stored separately.
  6. One structured JSON summary per cycle on stdout (journald); API keys are
     never logged.
  7. At most one collector instance runs at a time (file lock).
"""

import argparse
import json
import os
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from methodology_v2 import METHODOLOGY_VERSION, delay_per_vehicle_s
from sources.air_quality import get_air_quality_for_ayalon, get_cached_air_quality
from sources.fuel_govil import (
    fetch_current_fuel_price_ils_per_l as fetch_current_fuel_price,
    get_cached_fuel_price,
)
from sources.history_store import HistoryStore
from sources.rate_limiter import get_quota_status, record_api_call
from sources.secure_config import SecureConfig
from sources.segment_matcher import load_reference_segments, match_all
from sources.traffic_providers import PROVIDERS, ProviderResult, configured_provider_order

RAW_RETENTION_DAYS = int(os.getenv("RAW_RETENTION_DAYS", "30"))
DAILY_QUOTA = {
    "here": int(os.getenv("HERE_QUOTA_PER_DAY", "1000")),
    "tomtom": int(os.getenv("TOMTOM_QUOTA_PER_DAY", os.getenv("TOMTOM_QUOTA_PER_HOUR", "2500"))),
}
LOCK_PATH = Path(os.getenv("COLLECTOR_LOCK_PATH", str(Path(__file__).resolve().parent / "data" / "collector.lock")))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _log(level: str, event: str, **kw: Any) -> None:
    """Emit a structured JSON log line (collected by journald)."""
    entry = {"ts": _utc_now_iso(), "level": level, "event": event, **{k: v for k, v in kw.items() if v is not None}}
    print(json.dumps(entry, default=str, ensure_ascii=False), flush=True)


@contextmanager
def _single_instance(path: Path):
    """Non-blocking exclusive lock; yields False if another collector holds it."""
    try:
        import fcntl
    except ImportError:  # Windows development machines
        yield True
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _provider_key(name: str) -> Optional[str]:
    if name == "here":
        return SecureConfig.get_here_api_key()
    if name == "tomtom":
        return SecureConfig.get_tomtom_api_key()
    return None


def _fetch_traffic(refs) -> tuple[Optional[ProviderResult], list]:
    """Try providers in configured order; return (first ok result or last result, attempt summaries)."""
    tried = []
    last = None
    for name in configured_provider_order():
        key = _provider_key(name)
        if not key:
            tried.append({"provider": name, "status": "not_configured"})
            continue
        quota = get_quota_status(name, quota_per_day=DAILY_QUOTA[name])
        if quota.get("remaining", 1) <= 0:
            tried.append({"provider": name, "status": "quota_exhausted", "calls_today": quota.get("calls_today")})
            continue
        fetch = PROVIDERS[name][1]
        res = fetch(key, refs)
        for a in res.attempts:
            if a.status is not None:
                record_api_call(name, quota_per_day=DAILY_QUOTA[name])
        tried.append(res.summary())
        last = res
        if res.status == "ok":
            return res, tried
    return last, tried


def _fetch_fuel() -> Dict[str, Any]:
    try:
        return fetch_current_fuel_price()
    except Exception as exc:
        _log("WARN", "fuel_fetch_failed", error=str(exc)[:200])
        cached = get_cached_fuel_price(max_age_s=14 * 86400)
        if cached:
            out = dict(cached)
            out["source_id"] = str(out.get("source_id", "fuel")) + ":cached"
            return out
        return {}


def _fetch_air() -> Dict[str, Any]:
    try:
        return get_air_quality_for_ayalon(cache_ttl_s=600)
    except Exception as exc:
        _log("WARN", "air_quality_fetch_failed", error=str(exc)[:200])
        return get_cached_air_quality(max_age_s=24 * 3600) or {}


def collect_once(store: Optional[HistoryStore] = None, refs=None, fetcher=None) -> Dict[str, Any]:
    """Run one collection cycle and return its summary (also written to collection_cycles)."""
    started = _utc_now_iso()
    cycle_id = str(uuid.uuid4())
    store = store or HistoryStore()
    refs = refs if refs is not None else load_reference_segments()
    result, tried = (fetcher or _fetch_traffic)(refs)

    statuses: Dict[str, str] = {}
    segments_ok = segments_new = 0
    provider = result.provider if result else None
    if result is not None and result.status == "ok":
        store.store_raw(result.raw_sha256, result.provider, result.fetched_at, result.raw_gz)
        processed = _utc_now_iso()
        observed_at = result.source_updated or result.fetched_at
        snapshot = result.source_updated or result.response_id or result.raw_sha256
        for m in match_all(refs, result.pieces):
            statuses[m.segment_id] = m.status
            if m.status == "ok":
                segments_ok += 1
            inserted = store.insert_observation({
                "cycle_id": cycle_id,
                "segment_id": m.segment_id,
                "segment_version": m.segment_version,
                "methodology_version": METHODOLOGY_VERSION,
                "provider": result.provider,
                "provider_snapshot": snapshot,
                "observed_at_utc": observed_at,
                "source_updated_utc": result.source_updated,
                "fetched_at_utc": result.fetched_at,
                "processed_at_utc": processed,
                "status": m.status,
                "coverage": m.coverage,
                "length_m": m.length_m,
                "travel_time_s": m.travel_time_s,
                "freeflow_time_s": m.freeflow_time_s,
                "delay_s": delay_per_vehicle_s(m.travel_time_s, m.freeflow_time_s),
                "speed_kmh": m.speed_kmh,
                "freeflow_kmh": m.freeflow_kmh,
                "confidence": m.confidence,
                "jam_factor": m.jam_factor,
                "mean_offset_m": m.mean_offset_m,
                "max_offset_m": m.max_offset_m,
                "piece_ids": json.dumps(m.piece_ids),
                "raw_sha256": result.raw_sha256,
            })
            if inserted and m.status == "ok":
                segments_new += 1
            elif not inserted:
                statuses[m.segment_id] = m.status + ":snapshot_already_recorded"
    else:
        for r in refs:
            statuses[r.segment_id] = "provider_" + (result.status if result else "unavailable")

    total = len(refs)
    status = "ok" if segments_ok == total else ("partial" if segments_ok > 0 else "failed")

    fuel = _fetch_fuel()
    air = _fetch_air()
    error = None
    if result is None:
        error = "no traffic provider configured: " + ", ".join(t["provider"] + "=" + t["status"] for t in tried)
    elif result.status != "ok":
        error = f"{result.provider}: {result.status}: {result.error or ''}"[:500]

    cycle = {
        "cycle_id": cycle_id,
        "methodology_version": METHODOLOGY_VERSION,
        "started_at_utc": started,
        "finished_at_utc": _utc_now_iso(),
        "provider": provider,
        "provider_status": result.status if result else "not_configured",
        "status": status,
        "segments_total": total,
        "segments_ok": segments_ok,
        "segments_new": segments_new,
        "source_updated_utc": result.source_updated if result else None,
        "fetched_at_utc": result.fetched_at if result else None,
        "response_id": result.response_id if result else None,
        "raw_sha256": result.raw_sha256 if result else None,
        "error": error,
        "diagnostics_json": json.dumps({"providers": tried, "segments": statuses}, default=str)[:20000],
        "fuel_price_ils_per_l": fuel.get("price_ils_per_l"),
        "fuel_source_id": fuel.get("source_id"),
        "fuel_fetched_at_utc": fuel.get("fetched_at_utc") or fuel.get("fetched_at"),
        "air_source_id": air.get("source_id"),
        "air_fetched_at_utc": air.get("fetched_at"),
    }
    store.record_cycle(cycle)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=RAW_RETENTION_DAYS)).isoformat().replace("+00:00", "Z")
    store.prune_raw(cutoff)

    summary = {k: cycle[k] for k in ("cycle_id", "status", "provider", "provider_status", "segments_total",
                                     "segments_ok", "segments_new", "source_updated_utc", "fetched_at_utc", "error")}
    summary["segments"] = statuses
    summary["providers_tried"] = [{k: t.get(k) for k in ("provider", "status", "error")} for t in tried]
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description="Ayalon monitor: headless collector (methodology v2)")
    p.add_argument("--once", action="store_true", help="Run one collection cycle")
    p.add_argument("--migrate-only", action="store_true", help="Apply DB migration (with backup) and exit")
    args = p.parse_args()

    if args.migrate_only:
        info = HistoryStore(migrate=False).migrate()
        _log("INFO", "migration", result=info or "already_current")
        return 0
    if not args.once:
        p.error("Only --once is supported. Use systemd timer/cron for scheduling.")

    t0 = time.monotonic()
    with _single_instance(LOCK_PATH) as acquired:
        if not acquired:
            _log("WARN", "collector_already_running")
            return 0
        try:
            out = collect_once()
        except Exception as exc:
            _log("ERROR", "cycle_crashed", error=str(exc)[:300], traceback=traceback.format_exc()[-800:])
            return 1
    level = {"ok": "INFO", "partial": "WARN"}.get(out["status"], "ERROR")
    _log(level, "cycle_complete", duration_s=round(time.monotonic() - t0, 2), **out)
    return 0 if out["status"] in ("ok", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
