import argparse
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from methodology import AyalonModel
from sources import tomtom
from sources.air_quality import get_air_quality_for_ayalon, get_cached_air_quality
from sources.fuel_govil import fetch_current_fuel_price_ils_per_l as fetch_current_fuel_price, get_cached_fuel_price
from sources.history_store import HistoryStore
from sources.secure_config import SecureConfig


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


def _fetch_traffic(api_key: Optional[str], traffic_mode: str) -> Dict[str, Any]:
    cache_ttl_s = _env_int("CACHE_TTL_SECONDS", 300)
    try:
        return tomtom.get_ayalon_segments(api_key, cache_ttl_s=cache_ttl_s, mode=traffic_mode)
    except Exception:
        cached = tomtom.get_cached_ayalon_segments(mode=traffic_mode, max_age_s=24 * 3600)
        if cached:
            out = dict(cached)
            out["errors"] = ["Using cached traffic due to live fetch failure"]
            return out
        raise


def _fetch_air_quality() -> Dict[str, Any]:
    try:
        return get_air_quality_for_ayalon(cache_ttl_s=600)
    except Exception:
        cached = get_cached_air_quality(max_age_s=24 * 3600)
        if cached:
            out = dict(cached)
            out["error"] = out.get("error") or "Using cached air quality due to live fetch failure"
            return out
        raise


def _fetch_fuel_price() -> Dict[str, Any]:
    try:
        return fetch_current_fuel_price()
    except Exception:
        cached = get_cached_fuel_price(max_age_s=14 * 86400)
        if cached:
            out = dict(cached)
            out["source_id"] = str(out.get("source_id", "fuel")) + ":cached"
            return out
        raise


def collect_once() -> Dict[str, Any]:
    history = HistoryStore()
    model = AyalonModel()

    api_key = SecureConfig.get_tomtom_api_key()

    traffic_mode = os.getenv("TRAFFIC_MODE")
    if not traffic_mode:
        traffic_mode = "flow" if api_key else "sample"

    if traffic_mode == "flow" and not api_key:
        traffic_mode = "sample"  # fail-safe: still collect synthetic data

    tomtom_data = _fetch_traffic(api_key, traffic_mode)
    aq_data = _fetch_air_quality()
    fuel_data = _fetch_fuel_price()

    now_ts = time.time()
    tomtom_ts = _parse_iso_to_ts(tomtom_data.get("fetched_at"))
    tomtom_age_s = (now_ts - tomtom_ts) if tomtom_ts else None

    segments = tomtom_data.get("segments") or []
    price = fuel_data.get("price_ils_per_l")
    if not segments or price is None:
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

    return {
        "collected_at_utc": _utc_now_iso(),
        "traffic_mode": traffic_mode,
        "sources": src_ids,
        "pipeline_run_id": results.get("pipeline_run_id"),
        "delta_T_total_h": results.get("delta_T_total_h"),
        "leakage_ils": results.get("leakage_ils"),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Ayalon monitor: headless collector")
    p.add_argument("--once", action="store_true", help="Run one collection cycle")
    args = p.parse_args()

    if not args.once:
        p.error("Only --once is supported. Use systemd timer/cron for scheduling.")

    out = collect_once()
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
