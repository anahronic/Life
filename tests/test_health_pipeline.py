"""Health/freshness invariants for methodology v2.

  1. Fresh complete cycle -> healthy
  2. Fresh partial cycle -> partial
  3. Newest valid measurement 10 min..2 h old -> stale; older -> no_data
  4. Failed cycles never refresh the measurement age (no cache re-use)
  5. No cycle for 15 min -> collector_down
  6. Health never calls external APIs
"""

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sources.health import compute_traffic_health, get_quick_status
from sources.history_store import HistoryStore


def _iso(offset_s: float, now: float) -> str:
    return datetime.fromtimestamp(now + offset_s, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def store(tmp_path):
    return HistoryStore(db_path=tmp_path / "m.sqlite3")


def _cycle(store, now, offset, status, ok=6, total=6, error=None):
    store.record_cycle({
        "cycle_id": f"c{offset}{status}{time.monotonic_ns()}", "methodology_version": "2.0",
        "started_at_utc": _iso(offset, now), "status": status, "segments_total": total, "segments_ok": ok, "error": error,
    })


def _obs(store, now, offset, seg="ayalon_n_holon_laguardia", status="ok", snap=None):
    t = _iso(offset, now)
    store.insert_observation({
        "cycle_id": "x", "segment_id": seg, "segment_version": 2, "methodology_version": "2.0", "provider": "here_traffic_v7",
        "provider_snapshot": snap or t, "observed_at_utc": t, "fetched_at_utc": t, "processed_at_utc": t, "status": status,
        "travel_time_s": 100.0, "freeflow_time_s": 90.0,
    })


def test_empty_db(store):
    assert compute_traffic_health(str(store.db_path))["status"] == "empty"


def test_missing_db_file(tmp_path):
    assert compute_traffic_health(str(tmp_path / "nope.sqlite3"))["status"] == "empty"


def test_healthy(store):
    now = time.time()
    _obs(store, now, -60)
    _cycle(store, now, -60, "ok")
    h = compute_traffic_health(str(store.db_path), now_ts=now)
    assert h["status"] == "healthy" and h["age_s"] == 60
    assert get_quick_status(str(store.db_path)) == "healthy"


def test_partial(store):
    now = time.time()
    _obs(store, now, -60)
    _cycle(store, now, -60, "partial", ok=3)
    assert compute_traffic_health(str(store.db_path), now_ts=now)["status"] == "partial"


def test_failed_cycles_do_not_refresh_age(store):
    now = time.time()
    _obs(store, now, -3600)
    _cycle(store, now, -3600, "ok")
    for k in range(5):
        _cycle(store, now, -60 * k, "failed", ok=0, error="tomtom_flow_v4: no_coverage")
    h = compute_traffic_health(str(store.db_path), now_ts=now)
    assert h["status"] == "stale"
    assert h["age_s"] == 3600
    assert "no_coverage" in h["last_cycle_error"]


def test_no_data_after_2h(store):
    now = time.time()
    _obs(store, now, -3 * 3600)
    _cycle(store, now, -30, "failed", ok=0)
    assert compute_traffic_health(str(store.db_path), now_ts=now)["status"] == "no_data"


def test_never_measured_but_collector_running(store):
    now = time.time()
    _cycle(store, now, -30, "failed", ok=0)
    h = compute_traffic_health(str(store.db_path), now_ts=now)
    assert h["status"] == "no_data" and h["age_s"] is None


def test_collector_down(store):
    now = time.time()
    _obs(store, now, -1800)
    _cycle(store, now, -1800, "ok")
    assert compute_traffic_health(str(store.db_path), now_ts=now)["status"] == "collector_down"


def test_non_ok_observation_is_not_fresh(store):
    now = time.time()
    _obs(store, now, -30, status="insufficient_coverage")
    _cycle(store, now, -30, "failed", ok=0)
    assert compute_traffic_health(str(store.db_path), now_ts=now)["age_s"] is None


def test_health_has_no_network_code():
    import sources.health as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    for bad in ("import requests", "urllib", "api.tomtom.com", "hereapi"):
        assert bad not in src
