Ayalon Real-Time Physical Impact Model

> **Status 2026-09-24 — methodology v2.** TomTom removed Israel from its Traffic API
> coverage on 2026-09-15, so TomTom returns no data for Ayalon. The collector now
> supports HERE Traffic API v7 (Israel: flow + incidents) and needs `HERE_API_KEY`.
> v1 figures (Jan–Sep 2026) are methodologically invalid and are kept only as a
> flagged archive. See [docs/ayalon_v2_methodology.md](docs/ayalon_v2_methodology.md).

Quickstart

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Set environment variables (collector; on the VPS they live in `/etc/default/ayalon-monitor`):

```bash
export HERE_API_KEY=...            # real-time provider for Israel
export TRAFFIC_PROVIDERS=here,tomtom  # preference order (default)
```

3. Collect once, then run the dashboard (read-only):

```bash
python collector.py --once
streamlit run traffic_app.py
```

GitHub Pages (static landing page)

- GitHub Pages can host only static files, so it cannot run `traffic_app.py` directly.
- This repo includes a simple landing page in `docs/index.html` plus a Pages workflow.
- Enable it in GitHub: Settings → Pages → Source: GitHub Actions.

Minimal always-on collection (no server): GitHub Actions + SQLite — RETIRED 2026-09-24 (schedule disabled; history/monitor.sqlite3 is a frozen v1 archive)

This repo includes a scheduled workflow that runs `collector.py --once` and commits the updated SQLite DB back into the repo.

Setup:
1) In GitHub repo: Settings → Secrets and variables → Actions → New repository secret
	- Name: `TOMTOM_API_KEY`
	- Value: your TomTom key
2) Ensure Actions are enabled.
3) The workflow is in `.github/workflows/collector.yml` (default: every 10 minutes).
4) Collected history is stored in `history/monitor.sqlite3`.

Public deployment + automatic data collection

Option A (fast demo): Streamlit Community Cloud
- Good for: letting anyone view the dashboard quickly.
- Caveat: Streamlit Cloud runs the app when users open it; it is not a reliable 24/7 background scheduler. History DB on disk may reset on redeploy.

Steps:
1) Push to GitHub (this repo).
2) Create app on https://streamlit.io/cloud and set main file to `traffic_app.py`.
3) Set secrets in the Cloud UI using `.streamlit/secrets.toml.example` (TOMTOM_API_KEY, AQ_LAT/AQ_LON, etc.).

Option B (recommended for 24/7 auto-collection): VPS + systemd
- Run two things:
	1) `collector.py --once` on a timer (every 5 minutes) to fetch data and append to SQLite.
	2) Streamlit UI service to serve the dashboard to the public.

Systemd unit templates are in `deploy/systemd/`:
- `deploy/systemd/ayalon-collector.service`
- `deploy/systemd/ayalon-collector.timer`
- `deploy/systemd/ayalon-ui.service`

Server config is typically placed in `/etc/default/ayalon-monitor` (not in git), for example:
```bash
TOMTOM_API_KEY=... 
AQ_LAT=32.078
AQ_LON=34.796
HISTORY_DB_PATH=/opt/Life/data/monitor.sqlite3
TRAFFIC_MODE=flow
```

Then enable services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ayalon-ui.service
sudo systemctl enable --now ayalon-collector.timer
```

Notes
- The model requires live traffic (TomTom) and fuel price (gov or env var). If TomTom key is not set, the app returns sample segments.

Data Sources

**Fuel price** uses a 4-adapter chain (first success wins):

1. **Derived margin** (primary) — CKAN wholesale + excise + official consumer price from
   gov.il monthly PDF → retail margin is *derived* as:
   `margin = (official_price / (1 + VAT)) - wholesale_per_l - excise_per_l`
   Then: `consumer = (wholesale + excise + derived_margin) × (1 + VAT)`
   See `DERIVED_MARGIN_DESIGN.md` for the full design.

2. **CKAN + fallback margin** — same CKAN data, but with hardcoded fallback margin 0.66 NIS/L
   (used when the official PDF is unavailable). See `RETAIL_MARGIN_SOURCE_AUDIT.md`.
   - Wholesale resource: `orl-prices` (`aaa40832-ac82-4c86-bac6-0d05c83f576f`)
   - Excise resource: `excise` (`bdce45e7-9fe9-473e-bd51-cef1d787a951`)
   - Default VAT 18%, fallback margin 0.66 NIS/L (configurable via `FUEL_VAT_RATE`, `FUEL_RETAIL_MARGIN_ILS`)

3. **Gov.il monthly notice PDF** (fallback) — direct consumer price extraction via regex

4. **`FUEL_PRICE_ILS` env var** (emergency override)

**Official congestion benchmark** (optional):
- `OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR` env var, or
- `OFFICIAL_STATS_JSON_URL` pointing to a JSON endpoint
- Mode: `OFFICIAL_STATS_SOURCE_MODE` = `auto` | `url` | `static` | `disabled`

No API keys required for fuel price — the data.gov.il CKAN API is public.
- Data is cached in `sources/_cache` (file-based). Cache TTLs: traffic 300s, air 600s, fuel daily.
- Use `python run_reproduce.py` to export latest raw JSON for reproducibility.
- If `vehicle_count_mode = normalized_per_probe`, all totals are normalized per probe; absolute totals require flow-based vehicle counts.
