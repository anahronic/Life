# TomTom Rate Limiter Fix & SQLite Permissions Fix

**Date:** 2026-03-25 16:10 UTC  
**Server:** dikenocracy-main (dikenocracy.com)  
**Deployer:** GitHub Copilot (automated via SSH)

---

## Problem 1: TomTom Rate Limiter — Misleading Semantics & No Enforcement

### What Was Wrong

The internal rate limiter (`sources/rate_limiter.py`) had three critical issues:

| # | Issue | Impact |
|---|-------|--------|
| 1 | **Misleading naming**: `TOMTOM_QUOTA_PER_HOUR = 2500` | TomTom free plan limit is **2500/day**, not /hour. The variable name implied 2500/hour was acceptable. |
| 2 | **Quota never enforced**: `can_call()` only checked minimum interval (60s) between calls. It **never** checked if the call count exceeded the quota limit. | The quota counter was tracked but had no fail-closed behavior. Exceeded quota would only log a warning at 90%. |
| 3 | **In-memory counter reset on each process**: Collector runs as `Type=oneshot` systemd service — new process each run. Counter started at 0 every invocation. | For oneshot processes, the hourly quota tracking was effectively useless — it could never accumulate across runs. |

### How The Old Code Worked

```
rate_limiter.py (old):
  can_call("tomtom"):
    ✓ Checks min_interval_seconds (60s) — blocks if called too soon
    ✗ Does NOT check call_count vs quota — always allows if interval OK
    ✗ Counter resets every process start — useless for oneshot collector

  record_call("tomtom", quota_per_hour=2500):
    ✓ Increments in-memory counter
    ✗ Counter dies with process — no persistence
    ✗ quota_per_hour parameter is accepted but never used for enforcement
```

### What Was Changed

**`sources/rate_limiter.py`** — full rewrite:

| Feature | Old | New |
|---------|-----|-----|
| Quota naming | `quota_per_hour` | `quota_per_day` |
| Quota enforcement | Not enforced (log only at 90%) | **Fail-closed**: `can_call()` returns `(False, -1)` when daily quota exhausted |
| Counter persistence | In-memory only (resets per process) | **File-based**: `_cache/_rate_limiter_daily.json`, survives process restarts |
| Counter window | 3600s (1 hour) | **Calendar day UTC** (resets at midnight UTC) |
| Env var | `TOMTOM_QUOTA_PER_HOUR` | `TOMTOM_QUOTA_PER_DAY` (falls back to legacy `TOMTOM_QUOTA_PER_HOUR` if set) |
| Backward compat | — | `record_api_call()` and `get_quota_status()` accept both old and new kwargs |

**`sources/tomtom.py`** — 5 call-site updates:

| # | Change |
|---|--------|
| 1 | `TOMTOM_QUOTA_PER_HOUR` → `TOMTOM_QUOTA_PER_DAY` (env var + constant) |
| 2 | `record_api_call("tomtom", quota_per_hour=...)` → `record_api_call("tomtom", quota_per_day=...)` |
| 3 | `get_quota_status("tomtom", quota_per_hour=...)` → `get_quota_status("tomtom", quota_per_day=...)` |
| 4 | `quota.get("calls_this_hour", 0)` → `quota.get("calls_today", 0)` |
| 5 | `quota.get("quota_per_hour", ...)` → `quota.get("quota_per_day", ...)` |

**`/etc/default/ayalon-monitor`** — added `TOMTOM_QUOTA_PER_DAY=2500`

### Persistent Counter File

Location: `/opt/Life/sources/_cache/_rate_limiter_daily.json`

Format:
```json
{"date": "2026-03-25", "counts": {"tomtom": 3}}
```

- Resets automatically when UTC date changes
- Each `record_api_call()` increments the counter and writes to disk
- `can_call()` reads this file before allowing a call
- If file is unreadable/corrupt, counter resets (fail-open for reads, fail-closed for quota check)

### Expected Safe Collector Cadence Under Free Plan

| Interval | Runs/day | API calls/day (3 probes) | vs. 2500 limit | Status |
|----------|----------|--------------------------|-----------------|--------|
| 5 min | 288 | 864 | 34.6% | **Safe** |
| 3 min | 480 | 1440 | 57.6% | Safe |
| 2 min | 720 | 2160 | 86.4% | Warning zone |
| 1 min | 1440 | 4320 | 172.8% | **BLOCKED by limiter** at call #2500 |

Current systemd timer: every 5 minutes → **864 calls/day** → well within safe limits.

### Files NOT Changed

- `collector.py` — untouched
- `traffic_app.py` — untouched (readonly mode doesn't touch rate limiter)
- `sources/logger.py` — untouched (log_quota_alert signature unchanged)
- Sample mode — untouched (no API calls, no rate limiting involved)
- Cache logic — untouched

---

## Problem 2: SQLite Readonly Write Failure

### Symptom

```
$ python3 /opt/Life/collector.py --once
sqlite3.OperationalError: attempt to write a readonly database
```

### Root Cause

| File | Owner | Permissions | Problem |
|------|-------|-------------|---------|
| `/opt/Life/data/monitor.sqlite3` | `root:root` | `644` (`-rw-r--r--`) | Only root can write; `admin` user gets read-only |
| `/opt/Life/data/` | `root:root` | `777` (`drwxrwxrwx`) | Directory was world-writable but file was not |

The systemd collector service runs as root (no `User=` in unit file) → root can write to 644 files.
But `admin` running `python3 /opt/Life/collector.py --once` cannot write to root-owned 644 file.

### What Was Fixed

```bash
chown admin:admin /opt/Life/data/monitor.sqlite3
chmod 664 /opt/Life/data/monitor.sqlite3

chown admin:admin /opt/Life/data
chmod 775 /opt/Life/data

chown -R admin:admin /opt/Life/sources/_cache
```

| File | Owner | Permissions | After |
|------|-------|-------------|-------|
| `monitor.sqlite3` | `admin:admin` | `664` (`-rw-rw-r--`) | admin can write; root can write (superuser); others read-only |
| `data/` | `admin:admin` | `775` | admin can create WAL/journal files; root can too |
| `_cache/` | `admin:admin` | (preserved) | admin can write rate limiter counter file |

### Who Can Now Write to SQLite

| Actor | Method | Can write? |
|-------|--------|------------|
| systemd collector service | Runs as root | **Yes** (root bypasses permissions) |
| `admin` user (manual run) | `python3 /opt/Life/collector.py --once` | **Yes** (file owner) |
| `admin` via sudo | `sudo python3 /opt/Life/collector.py --once` | **Yes** (root) |
| Streamlit UI | Runs as root, readonly mode | **Does not write** (readonly architecture) |
| Other users | — | **No** (read-only: `664`) |

### Manual Collector Run (Supported Command)

```bash
# As admin user (now works directly):
cd /opt/Life && python3 collector.py --once

# Or via systemd (preferred for ops):
sudo systemctl start ayalon-collector.service
```

---

## Validation Results

| # | Check | Result |
|---|-------|--------|
| 1 | `rate_limiter.py` AST parse | OK |
| 2 | `tomtom.py` AST parse | OK |
| 3 | Persistent counter created | `{"date": "2026-03-25", "counts": {"tomtom": 3}}` |
| 4 | `collector.py --once` as admin | **Success** — row 18 written, 3 TomTom calls |
| 5 | SQLite rows: 17 → 18 | Confirmed |
| 6 | UI health endpoint | `ok` |
| 7 | Public URL (HTTPS) | HTTP 200 |
| 8 | UI readonly: no TomTom calls in logs | Confirmed |
| 9 | Service restarted (PID 159762) | active (running) |
| 10 | Env file: `TOMTOM_QUOTA_PER_DAY=2500` | Present |

### Backups Created

```
/opt/Life/sources/rate_limiter.py.bak.pre_daily_fix
/opt/Life/sources/tomtom.py.bak.pre_daily_fix
```

### Rollback

```bash
sudo cp /opt/Life/sources/rate_limiter.py.bak.pre_daily_fix /opt/Life/sources/rate_limiter.py
sudo cp /opt/Life/sources/tomtom.py.bak.pre_daily_fix /opt/Life/sources/tomtom.py
sudo sed -i '/TOMTOM_QUOTA_PER_DAY/d' /etc/default/ayalon-monitor
sudo chown root:root /opt/Life/data/monitor.sqlite3
sudo chmod 644 /opt/Life/data/monitor.sqlite3
sudo systemctl restart ayalon-ui.service
```

---

## Remaining Considerations

1. **Collector timer is still disabled**: `ayalon-collector.timer` is disabled on this server. Collection is via GitHub Actions. To enable local collection: `sudo systemctl enable --now ayalon-collector.timer`

2. **Rate limiter counter file ownership**: The `_rate_limiter_daily.json` file is in `_cache/` now owned by admin. Both root (service) and admin (manual) can write to it.

3. **GitHub Actions collector**: The GitHub Actions workflow runs in a separate environment and has its own in-memory rate limiting (counter starts at 0 each workflow run). The persistent file counter only applies to the local server. This is acceptable because GitHub Actions and the local server don't share state.
