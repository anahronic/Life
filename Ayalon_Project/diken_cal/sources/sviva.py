import requests
from datetime import datetime
from .cache import cache_read, cache_write

BASE = "http://www.svivaaqm.net/api"


def list_stations():
    r = requests.get(f"{BASE}/stations", params={"type": "json"}, timeout=20)
    r.raise_for_status()
    return r.json()


def latest_station(station_id: int):
    r = requests.get(f"{BASE}/stations/{station_id}", params={"getLatestValue": "true", "type": "json"}, timeout=20)
    r.raise_for_status()
    return r.json()


def get_nearby_aq_for_ayalon(cache_ttl_s: int = 600):
    cached = cache_read('sviva_ayalon', max_age_s=cache_ttl_s)
    if cached:
        return cached
    # Simple approach: pick station id 2 as example (user to refine)
    try:
        data = latest_station(2)
        out = {'station_id': 2, 'fetched_at': datetime.utcnow().isoformat() + 'Z', 'data': data}
        cache_write('sviva_ayalon', out)
        return out
    except Exception as e:
        return {'error': str(e)}
