"""
Official congestion benchmark source.

Provides the "hours lost per person per year" figure used to compare the
real-time Ayalon model output against government-published statistics.

Configuration is env-first (no mandatory Streamlit secrets dependency):
  OFFICIAL_STATS_SOURCE_MODE = auto | url | static | disabled   (default: auto)
  OFFICIAL_STATS_JSON_URL    = URL returning JSON benchmark payload
  OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR = numeric fallback
  OFFICIAL_SOURCE_LABEL      = human-readable source label

In ``auto`` mode the adapter tries URL first, then static env, then
returns an "unconfigured" stub (instead of an error).
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from .cache import cache_read, cache_write

logger = logging.getLogger(__name__)

CACHE_KEY = "official_congestion_benchmark"


# -- Env helpers --------------------------------------------------------------

def _env(key: str) -> Optional[str]:
    """Read a config value from environment only."""
    v = os.getenv(key)
    if v is not None and str(v).strip():
        return str(v).strip()
    return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# -- Adapters -----------------------------------------------------------------

def _fetch_from_url(source_url: str) -> Dict[str, Any]:
    """Fetch benchmark from a JSON URL."""
    r = requests.get(source_url, timeout=20)
    r.raise_for_status()
    js = r.json()

    hours = (
        js.get("hours_lost_per_person_per_year")
        or js.get("hours_lost_per_capita_per_year")
        or js.get("hours_per_person_per_year")
    )
    if hours is None:
        raise ValueError("JSON response missing hours_lost_per_person_per_year field")

    return {
        "source_id": "official:benchmark:url",
        "fetched_at": _utc_now_iso(),
        "hours_lost_per_person_per_year": float(hours),
        "source_label": str(
            js.get("source") or js.get("source_label") or "Official benchmark"
        ),
        "source_url": source_url,
        "raw": js,
    }


def _fetch_from_static_env() -> Optional[Dict[str, Any]]:
    """Read benchmark value from env vars."""
    hours_env = _env("OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR")
    if not hours_env:
        return None
    return {
        "source_id": "official:benchmark:env",
        "fetched_at": _utc_now_iso(),
        "hours_lost_per_person_per_year": float(hours_env),
        "source_label": _env("OFFICIAL_SOURCE_LABEL") or "Official benchmark (env)",
        "source_url": None,
        "raw": {"env": True},
    }


def _unconfigured_stub() -> Dict[str, Any]:
    """Return a benign 'unconfigured' result instead of raising."""
    return {
        "source_id": "official:benchmark:unconfigured",
        "fetched_at": None,
        "hours_lost_per_person_per_year": None,
        "source_label": "Official benchmark (unconfigured)",
        "source_url": None,
        "raw": {},
        "error": (
            "Set OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR or "
            "OFFICIAL_STATS_JSON_URL in env to enable."
        ),
    }


# -- Public interface ---------------------------------------------------------

def fetch_official_congestion_benchmark(
    cache_ttl_s: int = 24 * 3600,
) -> Dict[str, Any]:
    """Fetch official congestion benchmark (env-first, no secrets required).

    Source mode (OFFICIAL_STATS_SOURCE_MODE):
      auto     — try URL, then static env, then return unconfigured stub
      url      — JSON URL only (fail on error)
      static   — env var only
      disabled — always return unconfigured stub

    Returns stable schema:
      source_id, fetched_at, hours_lost_per_person_per_year,
      source_label, source_url?, error?, raw?
    """
    cached = cache_read(CACHE_KEY, max_age_s=cache_ttl_s)
    if cached:
        return cached

    mode = (_env("OFFICIAL_STATS_SOURCE_MODE") or "auto").lower()

    if mode == "disabled":
        return _unconfigured_stub()

    # -- URL path --
    source_url = _env("OFFICIAL_STATS_JSON_URL")
    if mode in ("auto", "url") and source_url:
        try:
            out = _fetch_from_url(source_url)
            cache_write(CACHE_KEY, out)
            return out
        except Exception as e:
            logger.warning("Official benchmark URL fetch failed: %s", e)
            if mode == "url":
                return {
                    "source_id": "official:benchmark:error",
                    "fetched_at": None,
                    "hours_lost_per_person_per_year": None,
                    "source_label": _env("OFFICIAL_SOURCE_LABEL") or "Official benchmark",
                    "source_url": source_url,
                    "error": str(e),
                    "raw": {},
                }

    # -- Static env path --
    if mode in ("auto", "static"):
        static = _fetch_from_static_env()
        if static:
            cache_write(CACHE_KEY, static)
            return static

    # -- Nothing configured --
    return _unconfigured_stub()


# -- Streamlit secret / env helper --------------------------------------------

def _get_secret_or_env(key: str):
    """Read from Streamlit secrets with env fallback (safe even outside Streamlit)."""
    try:
        import streamlit as st  # type: ignore
        v = st.secrets.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    except Exception:
        pass
    return _env(key)


# -- Official reference card (used by the read-only UI) -----------------------

def fetch_official_reference_card(cache_ttl_s=24 * 3600):
    """Return an official reference card (context-only) if configured.

    Configuration (Streamlit secrets or env):
      OFFICIAL_SOURCE_LABEL, OFFICIAL_REPORT_YEAR, OFFICIAL_REPORT_URL,
      OFFICIAL_METRIC_LABEL, OFFICIAL_VALUE, OFFICIAL_UNIT,
      OFFICIAL_VALUE_YEAR (optional).
    """
    cached = cache_read("official_reference_card_v1", max_age_s=cache_ttl_s)
    if cached:
        return cached

    source_label = _get_secret_or_env("OFFICIAL_SOURCE_LABEL")
    report_year_s = _get_secret_or_env("OFFICIAL_REPORT_YEAR")
    report_url = _get_secret_or_env("OFFICIAL_REPORT_URL")
    metric_label = _get_secret_or_env("OFFICIAL_METRIC_LABEL")
    value_s = _get_secret_or_env("OFFICIAL_VALUE")
    unit = _get_secret_or_env("OFFICIAL_UNIT")

    required = [source_label, report_year_s, report_url, metric_label, value_s, unit]
    if any(v is None for v in required):
        return {
            "configured": False,
            "fetched_at": None,
            "source_label": source_label,
            "report_year": None,
            "report_url": report_url,
            "metric_label": metric_label,
            "value": None,
            "unit": unit,
            "value_year": None,
            "error": "OFFICIAL_* reference not configured",
        }

    try:
        report_year = int(str(report_year_s))
        value = float(str(value_s))
        value_year_s = _get_secret_or_env("OFFICIAL_VALUE_YEAR")
        value_year = int(value_year_s) if value_year_s is not None else None

        out = {
            "configured": True,
            "fetched_at": _utc_now_iso(),
            "source_label": str(source_label),
            "report_year": report_year,
            "report_url": str(report_url),
            "metric_label": str(metric_label),
            "value": value,
            "unit": str(unit),
            "value_year": value_year,
            "error": None,
        }
        cache_write("official_reference_card_v1", out)
        return out
    except Exception as e:
        return {
            "configured": False,
            "fetched_at": None,
            "source_label": source_label,
            "report_year": None,
            "report_url": report_url,
            "metric_label": metric_label,
            "value": None,
            "unit": unit,
            "value_year": None,
            "error": str(e),
        }
