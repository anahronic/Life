import os
from datetime import datetime
from urllib.parse import urlparse

import requests

from .cache import cache_read, cache_write

# Prefer HTTPS. Some environments may redirect HTTP to unrelated domains; we block that.
BASE = "https://www.svivaaqm.net/api"
_ALLOWED_HOSTS = {"www.svivaaqm.net", "svivaaqm.net"}


def _safe_get(url: str, *, params: dict, timeout: int = 20):
    r = requests.get(url, params=params, timeout=timeout, allow_redirects=False)
    if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
        loc = r.headers.get("Location", "")
        host = urlparse(loc).hostname
        if host and host not in _ALLOWED_HOSTS:
            raise RuntimeError(f"Sviva redirect blocked: {url} -> {loc}")
        raise RuntimeError(f"Sviva unexpected redirect: {url} -> {loc}")
    r.raise_for_status()
    return r


def list_stations():
    r = _safe_get(f"{BASE}/stations", params={"type": "json"}, timeout=20)
    return r.json()


def latest_station(station_id: int):
    r = _safe_get(
        f"{BASE}/stations/{station_id}",
        params={"getLatestValue": "true", "type": "json"},
        timeout=20,
    )
    return r.json()


def get_nearby_aq_for_ayalon(cache_ttl_s: int = 600):
    cached = cache_read('sviva_ayalon', max_age_s=cache_ttl_s)
    if cached:
        return cached
    fetched_at = datetime.utcnow().isoformat() + 'Z'
    # Simple approach: station id 2 as example (override via env)
    station_id = int(os.getenv("SVIVA_STATION_ID", "2"))
    try:
        data = latest_station(station_id)
        out = {
            'source_id': f'sviva:station_{station_id}',
            'station_id': station_id,
            'fetched_at': fetched_at,
            'data': data,
        }
        cache_write('sviva_ayalon', out)
        return out
    except Exception as e:
        # Keep a stable schema for UI; don't cache errors.
        return {
            'source_id': 'sviva:error',
            'station_id': station_id,
            'fetched_at': None,
            'error': str(e),
        }
