# TomTom Traffic Flow API v4 Integration — Report (Ayalon PTL v1.1)

Frozen on: 2026-01-08
Scope: Highway 20 (Ayalon), Israel

## 1. Code Changes (sources/tomtom.py)

- Added `BASE = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"` (v4 absolute, zoom 10)
- New helpers:
  - `_haversine_km(lat1, lon1, lat2, lon2) -> float`
  - `_polyline_length_km(coords: List[Dict[str, float]]) -> float`
  - `_call_tomtom(api_key, lat, lon, unit="KMPH") -> (json, headers, url_without_key, status_code)`
- Updated `_segment_from_probe(p, api_key)` to:
  - Perform v4 fetch via `_call_tomtom`
  - Fail-closed validations (fields, confidence, speed/time, coordinates)
  - Compute `length_km` by polyline
  - Compute surrogate `vehicle_count` (flow_estimated)
  - Return canonical segment dict with source-level fields
- Updated `get_ayalon_segments(api_key, cache_ttl_s)` to:
  - Use per-probe cache keys `tt_v4_abs10_{segment_id}_{lat}_{lon}` and aggregate cache `tomtom_ayalon_v4_abs10`
  - Set top-level `source_id = "tomtom_flow_v4"` (or `":sample"`)
  - Derive top-level `vehicle_count_mode`

Invocation points:
- `run_reproduce.py` calls `sources.tomtom.get_ayalon_segments()`
- `traffic_app.py` calls `sources.tomtom.get_ayalon_segments()` and displays provenance
- `methodology.py` consumes canonical `segments` (unchanged interface)

## 2. Canonical Output Example (one segment)

```json
{
  "segment_id": "ha_shalom",
  "length_km": 0.14,
  "observed_travel_time_s": 120.0,
  "vehicle_count": 1500,
  "raw": {
    "response": { "flowSegmentData": { "currentSpeed": 60.0, "currentTravelTime": 120.0, "freeFlowSpeed": 90.0, "freeFlowTravelTime": 80.0, "confidence": 0.9, "roadClosure": false, "coordinates": {"coordinate": [{"latitude": 32.064, "longitude": 34.791},{"latitude": 32.065, "longitude": 34.792}] } } },
    "headers": { "X-Traffic-Tracking-Id": "abc-123" },
    "tracking_id": "abc-123",
    "request": { "endpoint": "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json", "point": "32.064,34.791", "unit": "KMPH", "openLr": "false" },
    "confidence": 0.9,
    "roadClosure": false
  },
  "source_id": "tomtom_flow_v4",
  "fetched_at": "2026-01-08T12:00:00Z",
  "vehicle_count_mode": "flow_estimated"
}
```

## 3. `length_km` Computation

- Function: `_polyline_length_km(coords)` in `sources/tomtom.py`
- Method: Sum Haversine distances across successive points in `flowSegmentData.coordinates.coordinate` (supports keys `latitude`/`longitude` or `lat`/`lon`/`lng`).
- Windowed: length is computed on a windowed polyline centered on the nearest coordinate to the probe point; default `half_window=8` (env override `TT_POLYLINE_HALF_WINDOW`). Raw diagnostics: `polyline_points_total`, `polyline_points_used`, `polyline_window_half`.

## 4. `vehicle_count` Computation (surrogate)

- Formula: `flow_vph = round(currentSpeed_kmph * DEFAULT_DENSITY_VEH_PER_KM)`, then `vehicle_count = clamp(flow_vph, 0..FLOW_VPH_CAP)`; if `roadClosure` is true → `vehicle_count = 0`.
- Parameters:
  - `DEFAULT_DENSITY_VEH_PER_KM` (default 25; env `TT_DEFAULT_DENSITY_VEH_PER_KM`)
  - `FLOW_VPH_CAP` (default 6000; env `TT_FLOW_VPH_CAP`)
  - `CONFIDENCE_MIN` (default 0.5; env `TT_CONFIDENCE_MIN`)
- Mode: `vehicle_count_mode = "flow_estimated"` (explicitly marked)

## 5. Fail-Closed Checks

- HTTP status != 200 → `RuntimeError`
- Missing `flowSegmentData` → `RuntimeError`
- Missing fields: `currentSpeed`, `currentTravelTime`, `freeFlowSpeed`, `freeFlowTravelTime`, `confidence`, `roadClosure`, `coordinates` → `RuntimeError`
- `confidence` not in [0,1] or `< CONFIDENCE_MIN` → `RuntimeError`
- `currentSpeed < 0` or `currentTravelTime <= 0` → `RuntimeError`
- `coordinates` absent or <2 points → `ValueError/RuntimeError`
- Speed/time consistency check: Disabled in v1.1 to avoid false positives from zoom-shifted coordinates (policy change)
- Error messages include: `segment_id`, endpoint URL without key, short cause
- `raw` includes full response JSON and tracking-id header

## 6. Caching

- TTL: 300s via `sources/cache.py`
- Per-probe cache key: `tt_v4_abs10_{segment_id}_{lat}_{lon}`
- Aggregate cache key: `tomtom_ayalon_v4_abs10`
  - Includes mode: `tomtom_ayalon_v4_abs10_{mode}` to separate `flow` vs `sample`

## 7. Ayalon Segments (current configuration)

- `la_guardia` → point(32.038, 34.782)
- `ha_shalom` → point(32.064, 34.791)
- `arlozorov` → point(32.078, 34.796)
- Polyline/shape: sourced from TomTom response `flowSegmentData.coordinates.coordinate` per probe call; not stored separately

## 8. Local Verification Commands

- One request (Python snippet):
```python
from sources import tomtom
print(tomtom.get_ayalon_segments(api_key="<YOUR_KEY>", cache_ttl_s=0, mode="flow"))
# Explicit sample fallback:
print(tomtom.get_ayalon_segments(api_key=None, cache_ttl_s=0, mode="sample"))
```

- Run tests:
```bash
pytest -q
# Expected: TomTom v4 tests pass with mocked responses
```

- Streamlit monitor:
```bash
streamlit run traffic_app.py
# Traffic source shows 'tomtom_flow_v4' and vehicle_count_mode
```

## 9. TODO

- Calibrate `DEFAULT_DENSITY_VEH_PER_KM` using observed flows or lane-based density models
- Add parameterized zoom/style if needed (currently fixed to absolute/10)
- Expand probes list and segmentization to cover full Ayalon corridor shapes
- Consider persisting polyline shapes for richer UI overlays

---

## Policy Updates (v1.1)

- Fail-closed default: `mode="flow"` requires `TOMTOM_API_KEY`; if missing, raises `RuntimeError` (no silent normalized fallback).
- Sample fallback allowed only when explicitly requested (`mode="sample"`) or `TT_ALLOW_SAMPLE=1`.
- Tracking header extraction: `tracking_id = headers.get("tracking-id") or headers.get("Tracking-ID")` stored in `raw["tracking_id"]`.
- Speed/time consistency check disabled to avoid false positives.

## Code Excerpts (around changes)

### get_ayalon_segments(...)

```python
def get_ayalon_segments(api_key: str | None, cache_ttl_s: int = 300, mode: str = "flow") -> Dict[str, Any]:
  aggregate_cache_key = f"tomtom_ayalon_v4_abs10_{mode}"
  ...
  for p in PROBE_POINTS:
    probe_cache_key = f"tt_v4_abs10_{mode}_{p['id']}_{p['lat']:.3f}_{p['lon']:.3f}"
    seg = _segment_from_probe(p, api_key, mode=mode)
    ...
```

### _call_tomtom(...)

```python
def _call_tomtom(api_key: str, lat: float, lon: float, unit: str = "KMPH") -> Tuple[Dict[str, Any], Dict[str, Any], str, int]:
  r = requests.get(BASE, params=...)
  url_wo_key = ...  # endpoint without key
  if r.status_code != 200:
    raise RuntimeError(f"TomTom v4 fetch failed: status={status} endpoint={url_wo_key}")
  return r.json(), dict(r.headers), url_wo_key, r.status_code
```

### _segment_from_probe(...)

```python
def _segment_from_probe(p: Dict[str, Any], api_key: str | None, mode: str = "flow") -> Dict[str, Any]:
  if not api_key:
    allow_sample = os.getenv("TT_ALLOW_SAMPLE") == "1" or (mode or "").lower() == "sample"
    if not allow_sample:
      raise RuntimeError("TomTom v4: API key missing and mode='flow' ...")
    # explicit normalized sample
  ...
  tracking_id = headers.get("tracking-id") or headers.get("Tracking-ID")
  seg = { ... , "raw": { "tracking_id": tracking_id, ... } }
```
