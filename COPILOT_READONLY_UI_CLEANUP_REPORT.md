# Readonly UI Cleanup Report

**Date:** 2026-03-25 15:20 UTC  
**Server:** dikenocracy-main (dikenocracy.com)  
**Scope:** Post-deploy UI/UX cleanup for `AYALON_UI_MODE=readonly`

---

## Problem

After deploying the readonly architecture fix, the production UI showed:
- **System status: "degraded"** — false alarm
- **Stale data warning** on every page load — false alarm
- **Yellow normalization banner** — cosmetic, not a real warning

These were residual assumptions from the live-fetch era, not real problems.

## Root Causes Identified

| # | Warning | Root Cause | Verdict |
|---|---------|------------|---------|
| 1 | System status: **degraded** (sidebar + sources tab) | `health.py` `get_quick_status()` pings TomTom API + checks live cache freshness → both fail in readonly mode → `stale` → `degraded` | **False alarm** — readonly mode doesn't need TomTom API or live cache |
| 2 | Stale data warning (provenance section) | Checked `tomtom_data.fetched_at` age > 600s. In readonly mode, `fetched_at` comes from the DB field `tomtom_fetched_at` which refers to when the *collector* last fetched, not live age. Always stale. | **False alarm** — should check collector recency, not TomTom cache age |
| 3 | Normalization banner (yellow `st.warning`) | `normalization_banner_text()` displays informational text about normalized-per-probe metrics. Not an error or warning condition. | **Cosmetic** — should be `st.info` not `st.warning` |
| 4 | Official reference: "not configured" | `fetch_official_reference_card()` returns `configured=False` when env vars not set | **Correct behavior** — already shown as `st.info`, no change needed |
| 5 | Fuel source captions | Provenance detail for CKAN/PDF/env adapter origin | **Correct behavior** — informational, no change needed |

## Changes Made

### `sources/health.py` — added `get_quick_status_readonly()`

New function that checks **SQLite data recency** instead of TomTom API + live cache:
- Reads `recorded_at_utc` of the latest run from SQLite
- Returns `ok` if last run is < 30 minutes old
- Returns `stale` if last run is > 30 minutes old
- Returns `empty` if no runs exist
- Returns `error` if SQLite is unreachable
- **No TomTom API ping. No cache directory check.**

### `traffic_app.py` — 5 targeted fixes

| # | Location | Change |
|---|----------|--------|
| 1 | Line 9 (import) | Added `get_quick_status_readonly` to import |
| 2 | Line 679 (sidebar) | `get_quick_status()` → mode-aware: uses `get_quick_status_readonly()` in readonly mode |
| 3 | Line 860 (sources tab) | Same: `get_quick_status()` → mode-aware |
| 4 | Lines 927-940 (provenance) | Stale detection: readonly mode checks `data_timestamp_utc` age > 1800s (30 min) instead of `tomtom_fetched_at` age > 600s |
| 5 | Line 866 (banner) | `st.warning(banner)` → `st.info(banner)` |

### Files NOT changed (intentionally)

- `collector.py` — untouched
- `methodology.py` — untouched
- `ui_messages.py` — untouched (text content is fine)
- `sources/official_stats.py` — untouched (already uses `st.info`)
- `sources/analytics.py` — untouched

## Expected UI Behavior After Cleanup

### Readonly mode (default, production)

| Element | Expected State |
|---------|---------------|
| Sidebar: System health | `ok` (if collector ran within 30 min) |
| Sidebar: System health | `stale` (if collector hasn't run in > 30 min) |
| Normalization banner | Blue `st.info` (informational, not alarming) |
| Stale warning (provenance) | Hidden (unless collector data truly stale > 30 min) |
| Official reference card | `st.info("not configured")` or populated — neutral either way |
| Sources tab columns | Show source IDs and timestamps from DB — informational |
| Fuel adapter provenance | Show adapter type caption — informational |

### Conditions that STILL trigger warnings (real problems)

| Condition | UI Response |
|-----------|------------|
| No runs in SQLite (empty DB) | `st.info("Waiting for input data")` |
| Collector stopped > 30 min | System health: `stale` + stale warning in provenance |
| SQLite unreachable | System health: `error` |
| `AYALON_UI_MODE=live` with TomTom failure | `st.warning()` with error detail |

## Service Restart

```
sudo systemctl restart ayalon-ui.service
```

- **PID:** 159217 (started 15:20:20 UTC)
- **Status:** active (running), clean logs

## Validation

| Check | Before | After |
|-------|--------|-------|
| System health status | `degraded` | **`ok`** |
| Stale warning | Shown on every load | **Hidden** (data age < 30 min threshold) |
| Normalization banner | Yellow `st.warning` | **Blue `st.info`** |
| Streamlit health endpoint | `ok` | `ok` |
| Public URL (HTTPS) | HTTP 200 | HTTP 200 |
| SQLite rows | 17 | 17 (no new writes) |
| Service logs | Clean | Clean |
