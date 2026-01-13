Ayalon Real-Time Physical Impact Model

Quickstart

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Set environment variables (recommended):

```bash
export TOMTOM_API_KEY=your_key_here
export FUEL_PRICE_ILS=7.5  # optional fallback
```

3. Run Streamlit monitor:

```bash
streamlit run traffic_app.py
```

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
- Data is cached in `sources/_cache` (file-based). Cache TTLs: traffic 300s, air 600s, fuel daily.
- Use `python run_reproduce.py` to export latest raw JSON for reproducibility.
- If `vehicle_count_mode = normalized_per_probe`, all totals are normalized per probe; absolute totals require flow-based vehicle counts.
