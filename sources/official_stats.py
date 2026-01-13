import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from .cache import cache_read, cache_write
from .secure_config import SecureConfig


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_secret_or_env(key: str) -> Optional[str]:
    # Prefer SecureConfig secrets/env behavior if available
    try:
        v = SecureConfig._get_value(key)  # type: ignore[attr-defined]
    except Exception:
        v = os.getenv(key)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def fetch_official_congestion_benchmark(cache_ttl_s: int = 24 * 3600) -> Dict[str, Any]:
    """Fetch official congestion benchmark (Gov.il or other official URL) if configured.

    This is intentionally flexible because official publications change formats.

    Supported configuration:
    - OFFICIAL_STATS_JSON_URL: URL returning JSON with at least:
        {"hours_lost_per_person_per_year": <number>, "source": <string>, "updated_at": <string optional>}
      Any extra fields are kept under `raw`.

    Fallback configuration:
    - OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR: numeric string
    - OFFICIAL_SOURCE_LABEL: text

    Returns stable schema:
      source_id, fetched_at, hours_lost_per_person_per_year, source_label, source_url?, error?, raw?
    """
    cached = cache_read("official_congestion_benchmark", max_age_s=cache_ttl_s)
    if cached:
        return cached

    source_url = _get_secret_or_env("OFFICIAL_STATS_JSON_URL")
    if source_url:
        try:
            r = requests.get(source_url, timeout=20)
            r.raise_for_status()
            js = r.json()
            hours = js.get("hours_lost_per_person_per_year")
            if hours is None:
                hours = js.get("hours_lost_per_capita_per_year")
            if hours is None:
                hours = js.get("hours_per_person_per_year")
            hours_f = float(hours)

            out = {
                "source_id": "official:benchmark",
                "fetched_at": _utc_now_iso(),
                "hours_lost_per_person_per_year": hours_f,
                "source_label": str(js.get("source") or js.get("source_label") or "Official benchmark"),
                "source_url": source_url,
                "raw": js,
            }
            cache_write("official_congestion_benchmark", out)
            return out
        except Exception as e:
            return {
                "source_id": "official:benchmark:error",
                "fetched_at": None,
                "hours_lost_per_person_per_year": None,
                "source_label": _get_secret_or_env("OFFICIAL_SOURCE_LABEL") or "Official benchmark",
                "source_url": source_url,
                "error": str(e),
                "raw": {},
            }

    hours_env = _get_secret_or_env("OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR")
    if hours_env:
        try:
            out = {
                "source_id": "official:benchmark:env",
                "fetched_at": _utc_now_iso(),
                "hours_lost_per_person_per_year": float(hours_env),
                "source_label": _get_secret_or_env("OFFICIAL_SOURCE_LABEL") or "Official benchmark (env)",
                "source_url": None,
                "raw": {"env": True},
            }
            cache_write("official_congestion_benchmark", out)
            return out
        except Exception as e:
            return {
                "source_id": "official:benchmark:error",
                "fetched_at": None,
                "hours_lost_per_person_per_year": None,
                "source_label": _get_secret_or_env("OFFICIAL_SOURCE_LABEL") or "Official benchmark",
                "source_url": None,
                "error": str(e),
                "raw": {"env": True},
            }

    return {
        "source_id": "official:benchmark:unconfigured",
        "fetched_at": None,
        "hours_lost_per_person_per_year": None,
        "source_label": "Official benchmark (unconfigured)",
        "source_url": None,
        "raw": {},
        "error": "OFFICIAL_STATS_JSON_URL or OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR not set",
    }
