import os
import math
import requests
from typing import Dict, Any, List, Tuple
from datetime import datetime
from .cache import cache_read, cache_write
from .rate_limiter import can_call_api, record_api_call, get_quota_status
from .logger import log_api_call, log_error, log_quota_alert

# TomTom Flow API v4 (absolute, zoom 10)
BASE = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

TOMTOM_QUOTA_PER_HOUR = int(os.getenv("TOMTOM_QUOTA_PER_HOUR", "2500"))

# Estimation/config constants (override via env for reproducibility/calibration)
DEFAULT_DENSITY_VEH_PER_KM = float(os.getenv("TT_DEFAULT_DENSITY_VEH_PER_KM", "25"))
FLOW_VPH_CAP = int(os.getenv("TT_FLOW_VPH_CAP", "6000"))
CONFIDENCE_MIN = float(os.getenv("TT_CONFIDENCE_MIN", "0.5"))
POLYLINE_HALF_WINDOW = int(os.getenv("TT_POLYLINE_HALF_WINDOW", "8"))

# Probe points along Ayalon (lat, lon) - sample list; user can refine
PROBE_POINTS = [
    {"id": "la_guardia", "lat": 32.038, "lon": 34.782},
    {"id": "ha_shalom", "lat": 32.064, "lon": 34.791},
    {"id": "arlozorov", "lat": 32.078, "lon": 34.796},
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return Haversine distance in km between two WGS84 points."""
    R = 6371.0088  # km, mean Earth radius
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _polyline_length_km(coords: List[Dict[str, float]]) -> float:
    """Compute polyline length in km for a list of coordinate dicts."""
    if not isinstance(coords, list) or len(coords) < 2:
        raise ValueError("TomTom v4: coordinates missing or insufficient (<2 points)")
    total = 0.0
    def get_lat_lon(c):
        lat = c.get("latitude") if "latitude" in c else c.get("lat")
        lon = c.get("longitude") if "longitude" in c else c.get("lon") or c.get("lng")
        if lat is None or lon is None:
            raise ValueError("TomTom v4: coordinate missing lat/lon")
        return float(lat), float(lon)
    prev = coords[0]
    for cur in coords[1:]:
        lat1, lon1 = get_lat_lon(prev)
        lat2, lon2 = get_lat_lon(cur)
        total += _haversine_km(lat1, lon1, lat2, lon2)
        prev = cur
    if total <= 0:
        raise ValueError("TomTom v4: computed polyline length is non-positive")
    return total


def _nearest_coord_index(coords: List[Dict[str, float]], lat: float, lon: float) -> int:
    """Return index of coordinate closest to given probe point (Haversine)."""
    if not coords:
        raise ValueError("TomTom v4: coordinates missing for nearest index computation")

    def get_lat_lon(c):
        lat_v = c.get("latitude") if "latitude" in c else c.get("lat")
        lon_v = c.get("longitude") if "longitude" in c else c.get("lon") or c.get("lng")
        if lat_v is None or lon_v is None:
            raise ValueError("TomTom v4: coordinate missing lat/lon")
        return float(lat_v), float(lon_v)

    min_idx = 0
    min_dist = float("inf")
    for idx, c in enumerate(coords):
        c_lat, c_lon = get_lat_lon(c)
        dist = _haversine_km(lat, lon, c_lat, c_lon)
        if dist < min_dist:
            min_dist = dist
            min_idx = idx
    return min_idx


def _windowed_coords(coords: List[Dict[str, float]], center_idx: int, half_window: int = POLYLINE_HALF_WINDOW) -> List[Dict[str, float]]:
    """Return a windowed slice of coordinates around center_idx (inclusive)."""
    if not isinstance(coords, list) or len(coords) < 2:
        raise ValueError("TomTom v4: coordinates missing or insufficient (<2 points)")
    n = len(coords)
    start = max(0, center_idx - half_window)
    end = min(n, center_idx + half_window + 1)
    window = coords[start:end]
    if len(window) < 2:
        # ensure at least two points using nearest neighbors
        start = max(0, min(center_idx, n - 2))
        end = start + 2
        window = coords[start:end]
    if len(window) < 2:
        raise ValueError("TomTom v4: windowed coordinates insufficient (<2 points)")
    return window


def _call_tomtom(api_key: str, lat: float, lon: float, unit: str = "KMPH") -> Tuple[Dict[str, Any], Dict[str, Any], str, int]:
    """Perform TomTom Flow API call, return (json, headers, url_without_key, status_code)."""
    params = {"point": f"{lat},{lon}", "unit": unit, "openLr": "false", "key": api_key}

    start = datetime.utcnow()
    r = requests.get(BASE, params=params, timeout=20)
    status = r.status_code
    # Build URL without key for provenance
    params_no_key = {k: v for k, v in params.items() if k != "key"}
    url_wo_key = f"{BASE}?" + "&".join(f"{k}={v}" for k, v in params_no_key.items())

    elapsed_ms = (datetime.utcnow() - start).total_seconds() * 1000
    log_api_call("tomtom", url_wo_key, status, elapsed_ms)

    if status != 200:
        log_error("tomtom", f"http_{status}", f"endpoint={url_wo_key}")
        raise RuntimeError(f"TomTom v4 fetch failed: status={status} endpoint={url_wo_key}")

    record_api_call("tomtom", quota_per_hour=TOMTOM_QUOTA_PER_HOUR)
    quota = get_quota_status("tomtom", quota_per_hour=TOMTOM_QUOTA_PER_HOUR)
    if quota.get("percent_used", 0) >= 90:
        log_quota_alert("tomtom", quota.get("calls_this_hour", 0), quota.get("quota_per_hour", TOMTOM_QUOTA_PER_HOUR))

    js = r.json()
    return js, dict(r.headers), url_wo_key, status


def _segment_from_probe(p: Dict[str, Any], api_key: str | None, mode: str = "flow") -> Dict[str, Any]:
    """Return canonical segment dict for a probe point with fail-closed validation."""
    fetched_at = datetime.utcnow().isoformat() + "Z"
    if not api_key:
        allow_sample = os.getenv("TT_ALLOW_SAMPLE") == "1" or (mode or "").lower() == "sample"
        if not allow_sample:
            raise RuntimeError("TomTom v4: API key missing and mode='flow'; set TOMTOM_API_KEY or enable sample via TT_ALLOW_SAMPLE=1 or mode='sample'")
        # Explicit sample mode (normalized)
        length_km = 2.0
        observed_travel_time_s = 300.0
        vehicle_count = 1
        seg = {
            "segment_id": p["id"],
            "length_km": length_km,
            "observed_travel_time_s": observed_travel_time_s,
            "vehicle_count": vehicle_count,
            "raw": {
                "response": {"source": "synthetic-sample"},
                "request": {"endpoint": BASE, "point": f"{p['lat']},{p['lon']}", "unit": "KMPH", "openLr": "false"},
            },
            "source_id": "tomtom_flow_v4:sample",
            "fetched_at": fetched_at,
            "vehicle_count_mode": "normalized_per_probe",
        }
        return seg

    js, headers, url_wo_key, _status = _call_tomtom(api_key, p["lat"], p["lon"], unit="KMPH")
    # Validate presence of flowSegmentData
    if "flowSegmentData" not in js or not isinstance(js["flowSegmentData"], dict):
        raise RuntimeError(f"TomTom v4: missing flowSegmentData for segment={p['id']} endpoint={url_wo_key}")
    data = js["flowSegmentData"]

    required_fields = [
        "currentSpeed",
        "currentTravelTime",
        "freeFlowSpeed",
        "freeFlowTravelTime",
        "confidence",
        "roadClosure",
        "coordinates",
    ]
    for fld in required_fields:
        if fld not in data:
            raise RuntimeError(f"TomTom v4: missing field '{fld}' segment={p['id']} endpoint={url_wo_key}")

    # Extract and validate primitives
    speed_kmph = float(data["currentSpeed"])
    travel_time_s = float(data["currentTravelTime"])
    confidence = float(data["confidence"])
    road_closure = bool(data["roadClosure"]) if isinstance(data["roadClosure"], bool) else str(data["roadClosure"]).lower() == "true"
    if confidence < 0.0 or confidence > 1.0:
        raise RuntimeError(f"TomTom v4: confidence out of [0,1] segment={p['id']} endpoint={url_wo_key}")
    if confidence < CONFIDENCE_MIN:
        raise RuntimeError(f"TomTom v4: confidence {confidence} < min {CONFIDENCE_MIN} segment={p['id']} endpoint={url_wo_key}")
    if speed_kmph < 0:
        raise RuntimeError(f"TomTom v4: negative speed segment={p['id']} endpoint={url_wo_key}")
    if travel_time_s <= 0:
        raise RuntimeError(f"TomTom v4: non-positive travel time segment={p['id']} endpoint={url_wo_key}")

    coords_container = data.get("coordinates")
    coords_list = None
    if isinstance(coords_container, dict) and "coordinate" in coords_container:
        coords_list = coords_container["coordinate"]
    elif isinstance(coords_container, list):
        coords_list = coords_container
    else:
        raise RuntimeError(f"TomTom v4: coordinates structure invalid segment={p['id']} endpoint={url_wo_key}")

    half_window = POLYLINE_HALF_WINDOW
    nearest_idx = _nearest_coord_index(coords_list, p["lat"], p["lon"])
    coords_window = _windowed_coords(coords_list, nearest_idx, half_window=half_window)
    length_km = _polyline_length_km(coords_window)

    # Speed/time consistency check disabled in v1.1 to avoid false positives from zoom-shifted coordinates.

    # Vehicle count surrogate: speed * density, capped, roadClosure -> 0
    flow_vph = max(0, min(int(round(speed_kmph * DEFAULT_DENSITY_VEH_PER_KM)), FLOW_VPH_CAP))
    vehicle_count = 0 if road_closure else flow_vph

    tracking_id = headers.get("tracking-id") or headers.get("Tracking-ID")
    seg = {
        "segment_id": p["id"],
        "length_km": length_km,
        "observed_travel_time_s": travel_time_s,
        "vehicle_count": vehicle_count,
        "raw": {
            "response": js,
            "headers": headers,
            "tracking_id": tracking_id,
            "request": {"endpoint": BASE, "point": f"{p['lat']},{p['lon']}", "unit": "KMPH", "openLr": "false"},
            "confidence": confidence,
            "roadClosure": road_closure,
            "polyline_points_total": len(coords_list),
            "polyline_points_used": len(coords_window),
            "polyline_window_half": half_window,
        },
        "source_id": "tomtom_flow_v4",
        "fetched_at": fetched_at,
        "vehicle_count_mode": "flow_estimated",
    }
    return seg


def get_ayalon_segments(api_key: str | None, cache_ttl_s: int = 300, mode: str = "flow") -> Dict[str, Any]:
    """Return canonical segments for Ayalon using TomTom v4.

    Default mode is 'flow' and requires TOMTOM_API_KEY. If no key, raises RuntimeError.
    Explicit sample mode is allowed via mode='sample' or env TT_ALLOW_SAMPLE=1 (returns normalized segments).
    """
    # Aggregate-level cache key includes endpoint style/version
    aggregate_cache_key = f"tomtom_ayalon_v4_abs10_{mode}"
    cached = cache_read(aggregate_cache_key, max_age_s=cache_ttl_s)
    if cached:
        return cached

    results = {
        "source_id": "tomtom_flow_v4" if api_key else "tomtom_flow_v4:sample",
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "vehicle_count_mode": None,
        "segments": [],
    }

    segments: List[Dict[str, Any]] = []
    probes_to_fetch: List[Dict[str, Any]] = []

    # First, reuse any per-probe cache entries.
    for p in PROBE_POINTS:
        probe_cache_key = f"tt_v4_abs10_{mode}_{p['id']}_{p['lat']:.3f}_{p['lon']:.3f}"
        seg_cached = cache_read(probe_cache_key, max_age_s=cache_ttl_s)
        if seg_cached:
            segments.append(seg_cached)
        else:
            probes_to_fetch.append(p)

    # Apply rate limiting once per batch refresh (not per probe).
    # This prevents a single UI refresh from being blocked after the first probe call.
    if probes_to_fetch and api_key:
        allowed, wait_s = can_call_api("tomtom")
        if not allowed:
            raise RuntimeError(f"TomTom v4 rate-limited: retry_after_seconds={wait_s:.1f}")

    for p in probes_to_fetch:
        probe_cache_key = f"tt_v4_abs10_{mode}_{p['id']}_{p['lat']:.3f}_{p['lon']:.3f}"
        seg = _segment_from_probe(p, api_key, mode=mode)
        segments.append(seg)
        cache_write(probe_cache_key, seg)

    results["segments"] = segments
    modes = {seg.get("vehicle_count_mode") for seg in segments}
    if "flow_estimated" in modes:
        results["vehicle_count_mode"] = "flow_estimated"
    else:
        results["vehicle_count_mode"] = "normalized_per_probe"

    cache_write(aggregate_cache_key, results)
    return results
