import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests

from .cache import cache_read, cache_write
from . import sviva


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _get_default_point() -> Tuple[float, float]:
    # Ayalon (approx): Arlozorov interchange
    lat = float(os.getenv("AQ_LAT", "32.078"))
    lon = float(os.getenv("AQ_LON", "34.796"))
    return lat, lon


def _open_meteo_air_quality(lat: float, lon: float, timeout_s: int = 20) -> Dict[str, Any]:
    """Fetch air quality from Open-Meteo (no API key)."""
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    hourly = "pm10,pm2_5,nitrogen_dioxide,ozone,us_aqi"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": hourly,
        "timezone": "UTC",
    }
    r = requests.get(url, params=params, timeout=timeout_s)
    r.raise_for_status()
    js = r.json()

    hourly_obj = js.get("hourly") or {}
    times = hourly_obj.get("time") or []
    if not isinstance(times, list) or not times:
        raise RuntimeError("Open-Meteo AQ: missing hourly.time")

    # Take last available hour
    idx = len(times) - 1

    def pick(name: str) -> Optional[float]:
        values = hourly_obj.get(name)
        if not isinstance(values, list) or len(values) <= idx:
            return None
        v = values[idx]
        try:
            return float(v) if v is not None else None
        except Exception:
            return None

    return {
        "source_id": "open-meteo:air-quality",
        "fetched_at": _utc_now_iso(),
        "point": {"lat": lat, "lon": lon},
        "data_timestamp_utc": str(times[idx]) + "Z" if isinstance(times[idx], str) and not str(times[idx]).endswith("Z") else str(times[idx]),
        "metrics": {
            "pm2_5_ug_m3": pick("pm2_5"),
            "pm10_ug_m3": pick("pm10"),
            "no2_ug_m3": pick("nitrogen_dioxide"),
            "o3_ug_m3": pick("ozone"),
            "us_aqi": pick("us_aqi"),
        },
        "raw": {"provider": "open-meteo", "response": js},
    }


def get_air_quality_for_ayalon(cache_ttl_s: int = 600) -> Dict[str, Any]:
    """Air quality feed with fallback.

    Priority:
      1) Sviva (measured stations) if reachable and safe
      2) Open-Meteo AQ (modeled/aggregated), no key

    Returns a stable schema:
      source_id, fetched_at, data_timestamp_utc, metrics, raw, error?
    """
    cached = cache_read("air_quality_ayalon", max_age_s=cache_ttl_s)
    if cached:
        return cached

    # 1) Try Sviva (if configured / reachable)
    sv = sviva.get_nearby_aq_for_ayalon(cache_ttl_s=0)
    if isinstance(sv, dict) and not sv.get("error") and sv.get("fetched_at"):
        out = {
            "source_id": sv.get("source_id") or "sviva:station",
            "fetched_at": sv.get("fetched_at"),
            "data_timestamp_utc": sv.get("fetched_at"),
            "metrics": {"station_id": sv.get("station_id")},
            "raw": {"provider": "sviva", "response": sv.get("data")},
        }
        cache_write("air_quality_ayalon", out)
        return out

    # 2) Fallback: Open-Meteo
    lat, lon = _get_default_point()
    try:
        out = _open_meteo_air_quality(lat, lon)
        cache_write("air_quality_ayalon", out)
        return out
    except Exception as e:
        return {
            "source_id": "air-quality:error",
            "fetched_at": None,
            "data_timestamp_utc": None,
            "metrics": {},
            "raw": {},
            "error": str(e),
        }


def get_cached_air_quality(max_age_s: int = 24 * 3600) -> Dict[str, Any] | None:
    """Return last cached air quality payload even if stale (for resilience/UI fallback)."""
    return cache_read("air_quality_ayalon", max_age_s=max_age_s)
