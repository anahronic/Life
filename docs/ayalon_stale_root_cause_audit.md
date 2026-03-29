# Ayalon Stale Status — Root Cause Audit

**Date:** 2026-03-30
**Scope:** Full causal audit of the `stale` system-health status in the Ayalon monitoring pipeline.

---

## 1. Primary Root Cause

**The systemd collector timer was never activated.**

```
$ systemctl status ayalon-collector.timer
○ ayalon-collector.timer - Run Ayalon collector every 5 minutes
     Loaded: loaded (/etc/systemd/system/ayalon-collector.timer; disabled)
     Active: inactive (dead)
```

The timer unit (`ayalon-collector.timer`) was deployed to `/etc/systemd/system/` but was never enabled or started. Consequently:

- `collector.py --once` was never invoked by systemd.
- All 18 rows in `monitor.sqlite3` came from manual test invocations or the legacy live-UI path.
- The UI, running in readonly mode, saw no recent `recorded_at_utc` and correctly reported `stale`.

**The system was stale because the data collector was not running, not because of a logic bug in status computation.**

However, the audit uncovered **six secondary defects** that would have caused incorrect status even with the collector running.

---

## 2. Secondary Defects

### 2.1. `health.py` made live HTTP requests to TomTom

**File:** `sources/health.py` → `HealthChecker.check_tomtom_api()`

The health check performed `requests.head('https://api.tomtom.com/')` on every invocation. This violated the invariant that the UI never calls TomTom directly. It also:
- Consumed network I/O on every Streamlit page load
- Could erroneously return "down" if the HEAD endpoint was slow, even when traffic data was fresh
- Polluted the aggregate health status: a TomTom HEAD timeout → `overall = 'down'` → UI says "down" even though the last valid traffic snapshot was 2 minutes old

**Fix:** Removed `check_tomtom_api()` entirely. Health is now computed solely from SQLite data age.

### 2.2. `health.py` freshness check read from file cache, not SQLite

**File:** `sources/health.py` → `HealthChecker.check_data_freshness()`

Used `cache_read('tomtom_ayalon_v4_abs10_flow', max_age_s=3600)`. The file cache has a hard `max_age_s`; data older than 1 hour was always `None`, yielding `status: 'stale'` regardless of actual data quality.

The file cache is an ephemeral optimization layer — it is not the source of truth. After a process restart, the cache is empty, immediately producing `stale`.

**Fix:** Freshness is now determined exclusively from the `runs` table in SQLite, using the `tomtom_fetched_at` column of the last valid traffic row.

### 2.3. `get_quick_status_readonly()` did not filter by traffic source

**File:** `sources/health.py` → `get_quick_status_readonly()`

Query: `SELECT recorded_at_utc FROM runs ORDER BY id DESC LIMIT 1`

This returns the most recent row of *any* type — including fuel-only writes, error rows, or partial runs. A fuel update 1 minute ago would mask a traffic snapshot that was 3 hours old.

**Fix:** Replaced with `compute_traffic_health()` which queries:
```sql
SELECT ... FROM runs
WHERE traffic_source_id IS NOT NULL
  AND traffic_source_id NOT LIKE '%:error%'
  AND tomtom_fetched_at IS NOT NULL
ORDER BY id DESC LIMIT 1
```

### 2.4. `history_store.py` `fetch_latest_run()` returned any row type

**File:** `sources/history_store.py`

The UI's readonly path called `fetch_latest_run()` which returns the most recent row without quality filters. If the most recent row was an error entry with `leakage_ils = None`, the dashboard would display `None` or crash.

**Fix:** Added `fetch_latest_traffic_run()` which applies the same traffic-validity filter. The UI now calls this first, falling back to `fetch_latest_run()` only if no valid traffic row exists.

### 2.5. No environment file on production server

**File:** `/etc/default/ayalon-monitor` — missing

The systemd service file references `EnvironmentFile=-/etc/default/ayalon-monitor` for `TOMTOM_API_KEY` and other configuration. This file did not exist. Without it, the collector would have fallen back to `sample` mode even if started.

**Fix:** Will be created during deployment with the correct API key.

### 2.6. Stale detection in UI used two inconsistent code paths

**File:** `traffic_app.py` (lines ~935-950)

In live mode, stale was computed from `tomtom_data.get('fetched_at')` with a 600s threshold.
In readonly mode, from `results.get('data_timestamp_utc')` with a 1800s threshold.
Neither path filtered for valid traffic rows, and the different thresholds meant the same data could be "healthy" in one mode and "stale" in another.

**Fix:** Both modes now call `compute_traffic_health()` which uses a single set of thresholds (600s → healthy, 1800s → degraded, 7200s → stale, >7200s → collector_down) applied to the last valid traffic row's `tomtom_fetched_at`.

---

## 3. Files Changed

| File | Change |
|------|--------|
| `collector.py` | Added structured JSON logging, quota-exhaustion pre-check, classified fetch errors (ok/rate_limited/auth_error/fetch_error), try/except around `main()` |
| `sources/health.py` | **Full rewrite.** Removed `HealthChecker` class with TomTom HEAD ping and cache-based freshness. Replaced with `compute_traffic_health()` using SQLite-only queries with traffic source filtering. Explicit states: healthy/degraded/stale/collector_down/empty/error |
| `sources/history_store.py` | Added `fetch_latest_traffic_run()` with traffic-validity SQL filter |
| `traffic_app.py` | Changed stale detection from inline timestamp math to `compute_traffic_health()`. Changed sidebar + Sources tab to use unified `get_quick_status()`. Changed `_acquire_readonly()` to use `fetch_latest_traffic_run()` |
| `tests/test_health_pipeline.py` | **New.** 14 tests covering all 7 TZ scenarios: healthy, preserved snapshot, degraded/stale by time, rate-limit resilience, fuel isolation, no-external-calls, auto-recovery |
| `docs/ayalon_stale_root_cause_audit.md` | This file |
| `docs/ayalon_health_checks.md` | Operator guide |

## 4. Deleted / Disabled

| What | Reason |
|------|--------|
| `HealthChecker.check_tomtom_api()` | Made live HTTP requests to TomTom from the UI process — violated invariant #2 |
| `HealthChecker.check_data_freshness()` | Read from file cache instead of SQLite — unreliable source of truth |
| `HealthChecker.full_health_check()` | Combined the two broken checks above into an incorrect aggregate |
| Inline stale logic in `traffic_app.py` | Replaced by single `compute_traffic_health()` call |

## 5. Normative Data Flow (post-fix)

```
┌──────────────────────┐
│  systemd timer       │  fires every 5 min
│  ayalon-collector    │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│  collector.py        │  ONLY path that calls TomTom
│  --once              │  also fetches air quality + fuel
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│  TomTom Flow API v4  │  external API (rate-limited, quota-checked)
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│  sources/tomtom.py   │  normalize → file cache → return segments
│  (cache.py)          │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│  methodology.py      │  AyalonModel.run_model() → metrics
│  (AyalonModel)       │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│  history_store.py    │  record_run() → SQLite (data/monitor.sqlite3)
│  (SQLite)            │  recorded_at_utc, traffic_source_id, tomtom_fetched_at, ...
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│  traffic_app.py (UI) │  READONLY: fetch_latest_traffic_run() from SQLite
│  (Streamlit)         │  NEVER calls TomTom
│                      │  Health: compute_traffic_health() → SQLite age check
└──────────────────────┘
```

## 6. Guaranteed Invariants

1. **TomTom is called only from `collector.py` → `_fetch_traffic()` → `tomtom.get_ayalon_segments()`.**
2. **UI never makes live traffic fetch.** Readonly path reads from SQLite. Even legacy `_acquire_live()` is gated behind `AYALON_UI_MODE=live` env var (not set on production).
3. **Last-known-good traffic snapshot is stored in SQLite**, identified by `traffic_source_id NOT LIKE '%:error%' AND tomtom_fetched_at IS NOT NULL`.
4. **Stale is computed from `tomtom_fetched_at` of the last valid traffic row only** — not from fuel timestamps, cache metadata, process memory, or UI request time.
5. **Failed/empty/rate-limited fetches fall back to cached data** and log the failure classification; they never overwrite the good snapshot in SQLite (the collector simply doesn't insert a row if it has insufficient data).
6. **Fuel pipeline has no influence on traffic freshness.** The `compute_traffic_health()` query explicitly filters by `traffic_source_id`.
7. **After a new successful collector cycle, status returns to `healthy` automatically** — the query always picks the newest valid row.
8. **Rate-limit detection happens before the API call** in `collector.py`, preventing retry storms.
9. **All operational states are logged as structured JSON** to stdout/journald: `cycle_start`, `cycle_complete` (with fetch status, data age, segment count), or `cycle_failed` (with error and traceback).
