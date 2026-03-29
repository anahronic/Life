"""Tests for the health/freshness pipeline invariants.

Covers scenarios from the TZ:
  1. Successful traffic fetch → healthy
  2. One failed fetch after good snapshot → good snapshot preserved
  3. Several missed cycles → degraded/stale by time
  4. Rate-limit response → no corruption of last-known-good
  5. Fuel update does not change traffic freshness
  6. UI reads only pre-computed local data
  7. Status recovers automatically after new successful fetch
"""

import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pytest


# ── Helpers ─────────────────────────────────────────────────────────────

def _utc_iso(delta_s: float = 0) -> str:
    """Return an ISO-8601 UTC timestamp, optionally shifted by delta_s."""
    dt = datetime.now(timezone.utc) + timedelta(seconds=delta_s)
    return dt.isoformat().replace("+00:00", "Z")


def _create_test_db(path: str) -> None:
    """Create the runs table matching history_store schema."""
    con = sqlite3.connect(path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at_utc TEXT NOT NULL,
            data_timestamp_utc TEXT,
            pipeline_run_id TEXT,
            traffic_source_id TEXT,
            air_source_id TEXT,
            fuel_source_id TEXT,
            vehicle_count_mode TEXT,
            delta_T_total_h REAL,
            co2_emissions_kg REAL,
            fuel_excess_L REAL,
            leakage_ils REAL,
            tomtom_fetched_at TEXT,
            tomtom_age_s REAL,
            air_fetched_at TEXT,
            fuel_fetched_at TEXT,
            UNIQUE(pipeline_run_id)
        )
    """)
    con.commit()
    con.close()


def _insert_run(
    db_path: str,
    *,
    traffic_source_id: str = "tomtom_flow_v4",
    tomtom_fetched_at: Optional[str] = None,
    recorded_at_utc: Optional[str] = None,
    pipeline_run_id: Optional[str] = None,
    delta_T: float = 1.23,
    leakage: float = 45.67,
) -> None:
    """Insert a run row into the test database."""
    now_iso = recorded_at_utc or _utc_iso()
    fetched = tomtom_fetched_at or now_iso
    run_id = pipeline_run_id or f"test-{time.monotonic_ns()}"
    con = sqlite3.connect(db_path)
    con.execute(
        """
        INSERT INTO runs (
            recorded_at_utc, data_timestamp_utc, pipeline_run_id,
            traffic_source_id, air_source_id, fuel_source_id,
            vehicle_count_mode, delta_T_total_h, co2_emissions_kg,
            fuel_excess_L, leakage_ils, tomtom_fetched_at, tomtom_age_s,
            air_fetched_at, fuel_fetched_at
        ) VALUES (?,?,?, ?,?,?, ?,?,?, ?,?,?,?, ?,?)
        """,
        (
            now_iso, now_iso, run_id,
            traffic_source_id, "air:test", "fuel:test",
            "flow_estimated", delta_T, 0.5,
            0.3, leakage, fetched, 1.0,
            now_iso, now_iso,
        ),
    )
    con.commit()
    con.close()


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database and return its path as str."""
    db_path = str(tmp_path / "test_monitor.sqlite3")
    _create_test_db(db_path)
    return db_path


# ── Import the modules under test ──────────────────────────────────────

from sources.health import (
    compute_traffic_health,
    get_quick_status,
    TRAFFIC_FRESH_S,
    TRAFFIC_DEGRADED_S,
    TRAFFIC_STALE_S,
)

from sources.history_store import HistoryStore


# ═══════════════════════════════════════════════════════════════════════
# Test Scenarios
# ═══════════════════════════════════════════════════════════════════════


class TestHealthyAfterGoodFetch:
    """Scenario 1: successful traffic fetch → status healthy."""

    def test_recent_run_is_healthy(self, tmp_db):
        _insert_run(tmp_db, tomtom_fetched_at=_utc_iso(-30))  # 30 s ago
        h = compute_traffic_health(tmp_db)
        assert h["status"] == "healthy"
        assert h["age_s"] is not None and h["age_s"] < TRAFFIC_FRESH_S

    def test_quick_status_returns_healthy(self, tmp_db):
        _insert_run(tmp_db, tomtom_fetched_at=_utc_iso(-10))
        assert get_quick_status(tmp_db) == "healthy"


class TestGoodSnapshotPreserved:
    """Scenario 2: failed fetch after good snapshot → good snapshot survives."""

    def test_error_row_does_not_override_good_snapshot(self, tmp_db):
        # Good run 2 min ago
        _insert_run(tmp_db, traffic_source_id="tomtom_flow_v4",
                     tomtom_fetched_at=_utc_iso(-120))
        # Bad run 10 s ago (error source)
        _insert_run(tmp_db, traffic_source_id="tomtom:error",
                     tomtom_fetched_at=None,
                     pipeline_run_id="bad-run")
        h = compute_traffic_health(tmp_db)
        assert h["status"] == "healthy"
        assert h["traffic_source_id"] == "tomtom_flow_v4"


class TestDegradedStaleByTime:
    """Scenario 3: missed collector cycles → status degrades by age."""

    def test_degraded_after_10_min(self, tmp_db):
        _insert_run(tmp_db, tomtom_fetched_at=_utc_iso(-700))  # ~12 min
        h = compute_traffic_health(tmp_db)
        assert h["status"] == "degraded"

    def test_stale_after_30_min(self, tmp_db):
        _insert_run(tmp_db, tomtom_fetched_at=_utc_iso(-2000))  # ~33 min
        h = compute_traffic_health(tmp_db)
        assert h["status"] == "stale"

    def test_collector_down_after_2h(self, tmp_db):
        _insert_run(tmp_db, tomtom_fetched_at=_utc_iso(-8000))  # ~2.2 h
        h = compute_traffic_health(tmp_db)
        assert h["status"] == "collector_down"


class TestRateLimitDoesNotCorrupt:
    """Scenario 4: rate-limit row does not affect last-known-good."""

    def test_rate_limited_row_ignored(self, tmp_db):
        _insert_run(tmp_db, traffic_source_id="tomtom_flow_v4",
                     tomtom_fetched_at=_utc_iso(-60))
        # Simulate a rate-limited error row
        _insert_run(tmp_db, traffic_source_id="tomtom:error",
                     tomtom_fetched_at=None,
                     pipeline_run_id="rate-limited-run")
        h = compute_traffic_health(tmp_db)
        assert h["status"] == "healthy"
        assert "error" not in h.get("traffic_source_id", "")


class TestFuelDoesNotAffectTraffic:
    """Scenario 5: fuel update does not change traffic freshness."""

    def test_fuel_only_row_not_counted_as_traffic(self, tmp_db):
        # Old traffic run (35 min ago → stale)
        _insert_run(tmp_db, traffic_source_id="tomtom_flow_v4",
                     tomtom_fetched_at=_utc_iso(-2100))
        # Recent fuel-only run (but has NULL traffic fields):
        con = sqlite3.connect(tmp_db)
        con.execute("""
            INSERT INTO runs (recorded_at_utc, traffic_source_id,
                              tomtom_fetched_at, air_source_id,
                              fuel_source_id, pipeline_run_id)
            VALUES (?, NULL, NULL, NULL, 'fuel:gov', 'fuel-only-1')
        """, (_utc_iso(-10),))
        con.commit()
        con.close()
        h = compute_traffic_health(tmp_db)
        # Should still be stale based on old traffic data
        assert h["status"] == "stale"


class TestEmptyDatabase:
    """Empty DB → status 'empty'."""

    def test_no_runs(self, tmp_db):
        h = compute_traffic_health(tmp_db)
        assert h["status"] == "empty"

    def test_quick_status_empty(self, tmp_db):
        assert get_quick_status(tmp_db) == "empty"


class TestAutoRecovery:
    """Scenario 7: after new successful fetch, stale resets automatically."""

    def test_recovery_from_stale(self, tmp_db):
        # Start with an old run (stale)
        _insert_run(tmp_db, tomtom_fetched_at=_utc_iso(-5000))
        assert compute_traffic_health(tmp_db)["status"] in ("stale", "collector_down")

        # Collector writes a fresh run
        _insert_run(tmp_db, tomtom_fetched_at=_utc_iso(-20),
                     pipeline_run_id="fresh-run")
        assert compute_traffic_health(tmp_db)["status"] == "healthy"


class TestHistoryStoreTrafficFilter:
    """fetch_latest_traffic_run filters error/fuel-only rows."""

    def test_skip_error_rows(self, tmp_db):
        store = HistoryStore(db_path=Path(tmp_db))
        _insert_run(tmp_db, traffic_source_id="tomtom_flow_v4",
                     tomtom_fetched_at=_utc_iso(-120),
                     pipeline_run_id="good-run", leakage=100.0)
        _insert_run(tmp_db, traffic_source_id="tomtom:error",
                     tomtom_fetched_at=None,
                     pipeline_run_id="bad-run", leakage=0.0)
        run = store.fetch_latest_traffic_run()
        assert run is not None
        assert run["pipeline_run_id"] == "good-run"
        assert run["leakage_ils"] == 100.0

    def test_returns_none_when_only_errors(self, tmp_db):
        store = HistoryStore(db_path=Path(tmp_db))
        _insert_run(tmp_db, traffic_source_id="tomtom:error",
                     tomtom_fetched_at=None,
                     pipeline_run_id="only-error")
        run = store.fetch_latest_traffic_run()
        assert run is None


class TestHealthNeverCallsExternal:
    """Scenario 6: health module has no network calls."""

    def test_no_requests_import(self):
        """health.py must not import requests at module level."""
        import importlib
        import sources.health as mod
        importlib.reload(mod)
        src = Path(mod.__file__).read_text()
        assert "import requests" not in src
        assert "requests.head" not in src
        assert "requests.get" not in src
        assert "api.tomtom.com" not in src
