# Deployment Report: Read-Only UI Fix

**Date:** 2026-03-25 15:06 UTC  
**Server:** dikenocracy-main (dikenocracy.com)  
**Deployer:** GitHub Copilot (automated via SSH)

---

## What Was Deployed

Applied the "UI readonly mode" fix from GitHub commit `0764f59` + `77b92f4` (branch `main`).

This makes `traffic_app.py` read from SQLite only (no TomTom API calls, no model runs, no writes) in the default production mode.

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `traffic_app.py` | **Replaced** | New version with `_acquire_readonly()` / `_acquire_live()` architecture |
| `sources/history_store.py` | **Replaced** | Added `fetch_latest_run()`, `fetch_latest_n_runs()` methods |
| `sources/official_stats.py` | **Replaced** | Added `fetch_official_reference_card()` function |
| `/etc/default/ayalon-monitor` | **Appended** | Added `AYALON_UI_MODE=readonly` |

### Backups Created

```
/opt/Life/traffic_app.py.bak.20260325_150517
/opt/Life/sources/history_store.py.bak.20260325_150517
/opt/Life/sources/official_stats.py.bak.20260325_150517
```

### Files NOT Changed

| File | Reason |
|------|--------|
| `collector.py` | Unchanged — remains sole live-ingestion path |
| `methodology.py` | Unchanged |
| `sources/tomtom.py` | Unchanged |
| `app.py` | Unchanged |
| Nginx config | Unchanged |
| systemd units | Unchanged |

## Service Restarted

```
sudo systemctl restart ayalon-ui.service
```

- **PID before:** 157776 (started 13:22:37 UTC)
- **PID after:** 159022 (started 15:06:26 UTC)
- **Status:** active (running), no errors in journalctl

## Validation Results

| # | Check | Result |
|---|-------|--------|
| 1 | `grep` for live calls in traffic_app.py | 3 matches — all inside `_acquire_live()` (not called in default mode) |
| 2 | `_UI_MODE` defaults to `"readonly"` | Confirmed (line 20) |
| 3 | `AYALON_UI_MODE=readonly` in env file | Confirmed in `/etc/default/ayalon-monitor` |
| 4 | SQLite rows before deploy | 17 |
| 5 | SQLite rows after deploy + page loads | **17** (zero new writes) |
| 6 | `curl http://127.0.0.1:8501/ayalon/` | HTTP 200 |
| 7 | `curl https://dikenocracy.com/ayalon/` | HTTP 200 |
| 8 | Streamlit health (`_stcore/health`) | `ok` |
| 9 | Service logs (journalctl) | Clean — no errors |
| 10 | `collector.py` identical to GitHub | Confirmed via `diff` |

## Rollback Procedure

If needed, restore the backups:

```bash
sudo cp /opt/Life/traffic_app.py.bak.20260325_150517 /opt/Life/traffic_app.py
sudo cp /opt/Life/sources/history_store.py.bak.20260325_150517 /opt/Life/sources/history_store.py
sudo cp /opt/Life/sources/official_stats.py.bak.20260325_150517 /opt/Life/sources/official_stats.py
sudo sed -i '/AYALON_UI_MODE/d' /etc/default/ayalon-monitor
sudo systemctl restart ayalon-ui.service
```

## Note: Collector Timer

The `ayalon-collector.timer` is **disabled** on this server. Data collection is handled by GitHub Actions (`.github/workflows/collector.yml`). To enable local collection:

```bash
sudo systemctl enable --now ayalon-collector.timer
```
