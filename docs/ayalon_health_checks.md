# Ayalon Health Checks — Operator Guide

Quick reference for diagnosing the Ayalon monitoring pipeline from the production server.

**Server:** `37.27.244.96`
**SSH:** `ssh admin@37.27.244.96`
**App root:** `/opt/Life/`

---

## 1. Is the collector running?

```bash
systemctl status ayalon-collector.timer
```

**Expected (healthy):**
```
● ayalon-collector.timer - Run Ayalon collector every 5 minutes
     Active: active (waiting)
    Trigger: <next fire time>
```

**If `inactive (dead)` or `disabled`:**
```bash
sudo systemctl enable --now ayalon-collector.timer
```

Check recent execution:
```bash
systemctl status ayalon-collector.service
journalctl -u ayalon-collector.service --since "1 hour ago" --no-pager
```

---

## 2. When was the last successful traffic update?

```bash
sqlite3 /opt/Life/data/monitor.sqlite3 \
  "SELECT id, recorded_at_utc, tomtom_fetched_at, traffic_source_id
   FROM runs
   WHERE traffic_source_id IS NOT NULL
     AND traffic_source_id NOT LIKE '%:error%'
     AND tomtom_fetched_at IS NOT NULL
   ORDER BY id DESC LIMIT 5;"
```

The `tomtom_fetched_at` column is UTC. Compare with current time (`date -u`).

**Health thresholds:**
| Age | Status |
|-----|--------|
| < 10 min (600s) | `healthy` |
| < 30 min (1800s) | `degraded` |
| < 2 h (7200s) | `stale` |
| > 2 h | `collector_down` |

---

## 3. Check the collector logs

Structured JSON logs go to journald:

```bash
# Last 20 entries
journalctl -u ayalon-collector.service -n 20 --no-pager

# Only errors
journalctl -u ayalon-collector.service -p err --since "24 hours ago" --no-pager

# Search for specific status
journalctl -u ayalon-collector.service --since "1 hour ago" --no-pager | grep '"fetch_status"'
```

**Fetch status codes in logs:**
| `fetch_status` | Meaning |
|----------------|---------|
| `ok` | TomTom returned valid segments |
| `quota_exhausted` | Daily 2500-call limit reached — stops until midnight UTC |
| `rate_limited` | Too many calls in short window — retries next cycle |
| `auth_error` | API key rejected (401/403) — check key validity |
| `fetch_error` | Network timeout or API 5xx — retries next cycle |

---

## 4. Is the UI running?

```bash
systemctl status ayalon-ui.service
```

If the UI needs a restart (e.g., after deploying new code):
```bash
sudo systemctl restart ayalon-ui.service
```

The UI runs on port 8501:
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8501
# Should return 200
```

---

## 5. Check the rate limiter / quota

```bash
cat /opt/Life/data/tomtom_quota.json
```

Shows:
```json
{
  "date": "2026-03-30",
  "count": 142,
  "daily_limit": 2500
}
```

If `count` is near 2500, the collector will skip TomTom calls until midnight UTC. This is normal behavior — last-known-good data is preserved.

To reset (emergency only):
```bash
echo '{"date":"'$(date -u +%Y-%m-%d)'","count":0,"daily_limit":2500}' > /opt/Life/data/tomtom_quota.json
```

---

## 6. Check the file cache

```bash
ls -la /opt/Life/sources/_cache/
```

Cache files are a performance optimization. They do **not** determine health status. If cache files are missing or stale, data will still be read from SQLite.

---

## 7. Check environment / API key

```bash
cat /etc/default/ayalon-monitor
```

Must contain at minimum:
```
TOMTOM_API_KEY=<valid-key>
```

If missing, the collector falls back to `sample` mode (fake data).

---

## 8. Common scenarios

### Scenario: UI shows "collector_down"
1. Check timer: `systemctl status ayalon-collector.timer`
2. If dead: `sudo systemctl enable --now ayalon-collector.timer`
3. Check logs: `journalctl -u ayalon-collector.service --since "1 hour ago"`
4. Check for auth errors → verify API key in `/etc/default/ayalon-monitor`

### Scenario: UI shows "stale" but collector is running
1. Check last successful traffic row (section 2)
2. Check recent logs for `quota_exhausted` or `fetch_error`
3. If quota exhausted → normal, wait for midnight UTC reset
4. If `fetch_error` → check network connectivity: `curl -I https://api.tomtom.com/`

### Scenario: UI shows "degraded"
- Data is between 10–30 minutes old
- Usually means the collector missed 1–2 cycles
- Check if it recovers on next cycle (within 5 min)
- If persistent, check logs

### Scenario: All data shows 0 or None
1. Check SQLite for rows: `sqlite3 /opt/Life/data/monitor.sqlite3 "SELECT COUNT(*) FROM runs;"`
2. If 0 rows → collector never ran successfully. Enable timer + check API key
3. If rows exist but all error → `SELECT traffic_source_id FROM runs ORDER BY id DESC LIMIT 5;`

### Scenario: Fuel data is stale but traffic is fresh
- This is by design. Fuel and traffic are independent pipelines.
- Fuel fetches from Israeli government APIs which may be down or updated less frequently.
- Traffic freshness is never affected by fuel data.

---

## 9. Service files reference

| Unit | Path | Purpose |
|------|------|---------|
| `ayalon-collector.service` | `/etc/systemd/system/ayalon-collector.service` | Type=oneshot, runs `collector.py --once` |
| `ayalon-collector.timer` | `/etc/systemd/system/ayalon-collector.timer` | Fires every 5 min, Persistent=true |
| `ayalon-ui.service` | `/etc/systemd/system/ayalon-ui.service` | Streamlit on port 8501 |

**Environment:** `/etc/default/ayalon-monitor`
**SQLite DB:** `/opt/Life/data/monitor.sqlite3`
**Quota file:** `/opt/Life/data/tomtom_quota.json`
**Cache dir:** `/opt/Life/sources/_cache/`
**Logs:** `journalctl -u ayalon-collector.service`
