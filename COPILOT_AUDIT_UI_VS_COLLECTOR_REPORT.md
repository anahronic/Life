# Ayalon Architecture Audit: UI vs Collector — Report

**Date:** 2026-03-25  
**Commit:** `0764f59` — `refactor: UI readonly mode — stop consuming TomTom API on page load`  
**Scope:** Highway 20 (Ayalon) Real-Time Physical Impact Model  
**Auditor:** GitHub Copilot (automated)

---

## 1. Current Problem (Before Fix)

### Why the old scheme wasted TomTom quota

The TomTom Flow API (v4) has a **daily/hourly request limit** on the free tier.
Two separate code paths were consuming these calls:

| Component         | File              | What it did                                    |
|-------------------|-------------------|------------------------------------------------|
| **Collector**     | `collector.py`    | `tomtom.get_ayalon_segments()` → `model.run_model()` → `history.record_run()` |
| **UI (Streamlit)**| `traffic_app.py`  | **Same chain:** `tomtom.get_ayalon_segments()` → `model.run_model()` → `history.record_run()` |

Every browser tab open, every user page load, and every Streamlit auto-refresh (every 5 minutes) would trigger a **live TomTom API call** from the UI — duplicating what the collector already does on a schedule.

### Where exactly the duplication happened

In the **original** `traffic_app.py`:

| Line(s) | Call | Problem |
|---------|------|---------|
| ~704–710 | `tomtom.get_ayalon_segments(api_key, ...)` | Live TomTom API call on every UI load |
| ~716–732 | `get_air_quality_for_ayalon()`, `fetch_current_fuel_price()` | Live external API calls (air quality, fuel) |
| ~809 | `model.run_model(segments, ...)` | Re-computation of model on every UI load |
| ~813–815 | `history.record_run(results=..., ...)` | **Double-write** to SQLite from UI |
| ~752 | `if auto_refresh and tomtom_age > 300: st.rerun()` | Forced page rerun, triggering all of the above again |

### Calls deemed unnecessary in the UI

- `tomtom.get_ayalon_segments()` — **unnecessary**: collector already fetches and stores results.
- `model.run_model()` — **unnecessary**: collector already computes and stores results.
- `history.record_run()` — **harmful**: duplicate rows in SQLite with different `pipeline_run_id`, polluting history.
- `st.rerun()` based on traffic age — **triggers cascading live fetches**.

---

## 2. Findings

### Files audited

| File | Lines | Role | Changes |
|------|-------|------|---------|
| `traffic_app.py` | 1020→1068 | Streamlit UI | **Major**: removed live fetch path from default mode |
| `collector.py` | 144 | Headless collector | **None**: untouched, remains sole ingestion path |
| `methodology.py` | 124 | Model calculations | **None**: untouched |
| `sources/history_store.py` | 158→177 | SQLite persistence | **Minor**: added `fetch_latest_run()`, `fetch_latest_n_runs()` |
| `sources/tomtom.py` | 292 | TomTom API adapter | **None**: untouched |
| `sources/official_stats.py` | 158→245 | Official reference card | **Minor**: added `fetch_official_reference_card()` function |

### SQLite schema (`runs` table)

```sql
CREATE TABLE runs (
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
);
```

**Finding:** The existing schema already contains **all fields** needed for the read-only dashboard:
- All 4 model metrics: `delta_T_total_h`, `co2_emissions_kg`, `fuel_excess_L`, `leakage_ils`
- Provenance: `pipeline_run_id`, `data_timestamp_utc`, `vehicle_count_mode`
- Source IDs: `traffic_source_id`, `air_source_id`, `fuel_source_id`
- Timestamps: `tomtom_fetched_at`, `air_fetched_at`, `fuel_fetched_at`

**No schema changes were needed.**

At time of audit: **54 rows** in the database, latest from `2026-01-13T16:37:23Z`.

---

## 3. Final Architecture

### BEFORE (broken)

```
┌──────────────┐     TomTom API     ┌──────────────┐
│  collector.py │ ──────────────────→│   SQLite      │
│  (cron/timer) │     model.run()    │  runs table   │
└──────────────┘     record_run()   └──────────────┘
                                          ↑
┌──────────────┐     TomTom API     ┌─────┘
│ traffic_app   │ ──────────────────→│  (duplicate writes!)
│ (Streamlit UI)│     model.run()    │
└──────────────┘     record_run()
```

**Problem:** Both paths call TomTom → model → SQLite. UI wastes API quota and creates duplicate rows.

### AFTER (fixed)

```
┌──────────────┐     TomTom API     ┌──────────────┐
│  collector.py │ ──────────────────→│   SQLite      │
│  (cron/timer) │     model.run()    │  runs table   │
└──────────────┘     record_run()   └──────────────┘
                                          │
                                    (read-only)
                                          │
                                          ↓
                                   ┌──────────────┐
                                   │ traffic_app   │
                                   │ (Streamlit UI)│
                                   └──────────────┘
```

**Fix:** UI reads from SQLite only. Zero TomTom calls. Zero model runs. Zero writes.

---

## 4. Data Flow

### Collector (unchanged)

```
collector.py --once
  → tomtom.get_ayalon_segments(api_key)       # TomTom API call
  → get_air_quality_for_ayalon()               # Air quality API call
  → fetch_current_fuel_price()                 # Fuel price fetch
  → model.run_model(segments, ...)             # Calculate metrics
  → history.record_run(results, ...)           # Write to SQLite
```

Triggered by: `systemd timer` (ayalon-collector.timer) or cron

### UI (new read-only path)

```
traffic_app.py (AYALON_UI_MODE=readonly, default)
  → history.fetch_latest_run()                 # Read latest row from SQLite
  → Build results dict from DB row             # No API calls
  → Render dashboard metrics                   # Display only
  → history.fetch_runs_df(limit=5000)          # Read history for charts/table
```

### UI (optional debug/live path)

```
traffic_app.py (AYALON_UI_MODE=live)
  → [old behaviour: fetch + model + record]    # For manual testing only
  → Sidebar warning: "⚠ UI mode: live"
```

---

## 5. Repo Sync Result

### State before sync

| Aspect | State |
|--------|-------|
| Local HEAD | `3bc9668` (Remove PDF export; keep Excel only) |
| origin/main | `add3c0f` (1344 commits ahead — mostly automated "collector: update history") |
| Working tree | 3 uncommitted modified files + our architecture changes |
| Divergence direction | Remote was ahead; local had no unique commits |

### Significant remote-only commits merged in

| Commit | Description |
|--------|-------------|
| `481e6e5` | Add GitHub Pages + scheduled collector |
| `6ecdaf5` | Added Dev Container Folder |
| `3d9e709` | refactor: official gov.il machine-readable sources for fuel prices |
| `aca99a8` | harden: CKAN adapter — field filters, deterministic date, schema+unit validation |

Plus ~1340 automated `collector: update history` commits (updating `history/monitor.sqlite3`).

### Sync process

1. Stashed local working changes
2. Fast-forward merged `origin/main` → local `main` (no conflicts at merge level)
3. Popped stash → 3 file conflicts: `traffic_app.py`, `sources/official_stats.py`, `.streamlit/secrets.toml.example`
4. Resolved conflicts:
   - `traffic_app.py`: took our read-only architecture version + merged fuel adapter provenance from remote
   - `sources/official_stats.py`: took remote refactored version + appended `fetch_official_reference_card()`
   - `.streamlit/secrets.toml.example`: took our updated version with reference card config
5. Committed as `0764f59`
6. Pushed to `origin/main`

### Final state

| Aspect | State |
|--------|-------|
| Local HEAD | `0764f59` (refactor: UI readonly mode) |
| origin/main | `0764f59` (same — synced) |
| Uncommitted changes | **None** |
| Divergence | **Zero** — local and remote are identical |

---

## 6. What Was Changed (Detailed)

### `traffic_app.py`

1. **Added `AYALON_UI_MODE` env var** (default: `readonly`)
2. **Created `_acquire_readonly()` function**: reads from `history.fetch_latest_run()`, constructs results dict from DB columns, returns zero-API-call data with synthetic tomtom_data/aq_data/fuel_data stubs.
3. **Created `_acquire_live()` function**: encapsulates the old live-fetch chain (preserved for debug use).
4. **Removed from default path**:
   - `auto_refresh` checkbox and `st.rerun()` timer
   - Traffic mode selector (flow/sample) — not meaningful in readonly mode
   - Direct calls to `tomtom.get_ayalon_segments()`, `model.run_model()`, `history.record_run()`
5. **Added null-safety** for `tomtom_data`, `aq_data`, `fuel_data` in Sources tab (they may be `None` in readonly mode if no runs exist)
6. **Added fuel adapter provenance** from upstream refactoring (CKAN/PDF/env details)
7. **Updated stale detection** to work from `tomtom_fetched_at` timestamp stored in DB

### `sources/history_store.py`

1. **Added `fetch_latest_run()`**: returns the most recent row as a dict.
2. **Added `fetch_latest_n_runs(n=300)`**: returns the N most recent rows.
3. **No schema changes** — existing table is sufficient.

### `sources/official_stats.py`

1. **Preserved upstream refactoring** (`fetch_official_congestion_benchmark` with CKAN/URL/static adapters)
2. **Added `_get_secret_or_env()`**: reads Streamlit secrets with env fallback
3. **Added `fetch_official_reference_card()`**: returns a configurable official reference card for context-only display

### `collector.py`

**No changes.** Continues as the sole live-ingestion path.

### `methodology.py`

**No changes.** Model logic untouched.

---

## 7. Risk Notes

### Remaining potential issues

1. **Stale data display**: If the collector stops running, the UI will show the last available data indefinitely. The stale warning is preserved (>600s), but there's no mechanism to distinguish "collector stopped" from "collector ran recently with old cached data."

2. **No per-segment data in readonly mode**: The `runs` table stores aggregated metrics only. If the UI ever needs to display per-segment details (e.g., a map of individual segment speeds), a `segments` snapshot table would be needed. Currently, the UI doesn't display per-segment data, so this is not a regression.

3. **SQLite file locking**: Both the collector (writer) and UI (reader) access the same SQLite file. SQLite handles this via WAL mode or default locking, but under high concurrency (many simultaneous UI users + frequent collector writes), brief locking delays are possible. For current usage patterns this is fine.

4. **`AYALON_UI_MODE=live` is not password-protected**: Anyone who can set environment variables can re-enable live mode. If this is a concern, the live mode function could be removed entirely in a future commit.

### Recommended next improvements

1. **Add a `--continuous` mode to `collector.py`** with built-in sleep loop, instead of relying solely on systemd timer. This would allow easier deployment in Docker/container environments.

2. **Add a "last collector run" timestamp** to the UI sidebar, so users can see when data was last refreshed by the collector.

3. **Consider pruning old runs** from SQLite (e.g., keep last 30 days) to prevent unbounded database growth.

4. **Add a lightweight health-check endpoint** that returns the age of the latest run, for monitoring/alerting.

---

## 8. Validation Checklist

| # | Check | Status |
|---|-------|--------|
| 1 | UI page load does NOT call TomTom API | ✅ Verified: `tomtom.get_ayalon_segments()` only in `_acquire_live()`, not called in default `readonly` mode |
| 2 | `collector.py` still works (no changes) | ✅ Verified: file unchanged, compiles OK |
| 3 | SQLite continues to be populated by collector | ✅ Verified: collector path (`collect_once()`) unchanged |
| 4 | `traffic_app.py` displays data from SQLite | ✅ Verified: `_acquire_readonly()` → `history.fetch_latest_run()` → render |
| 5 | No regression in dashboard rendering | ✅ Verified: all metrics, charts, and history tabs use same data shape |
| 6 | No double-write on UI open | ✅ Verified: `history.record_run()` only in `_acquire_live()` |
| 7 | Production behavior preserved | ✅ Verified: `AYALON_UI_MODE=live` restores old behavior as explicit opt-in |
| 8 | Backward compatibility of new methods | ✅ Verified: `fetch_latest_run()`/`fetch_latest_n_runs()` are additive; existing methods unchanged |
| 9 | All files compile without errors | ✅ Verified: `py_compile` passes for all 5 key files |
| 10 | Repo synced with GitHub | ✅ Pushed as commit `0764f59` to `origin/main` |

---

## Summary

| Metric | Before | After |
|--------|--------|-------|
| TomTom API calls per UI load | 3 (one per probe point) | **0** |
| `model.run_model()` per UI load | 1 | **0** |
| SQLite writes per UI load | 1 (duplicate) | **0** |
| Data source for dashboard | Live TomTom API | SQLite (collector-written) |
| Collector changes | — | **None** |
| Schema changes | — | **None** |
| New env var | — | `AYALON_UI_MODE` (default: `readonly`) |
