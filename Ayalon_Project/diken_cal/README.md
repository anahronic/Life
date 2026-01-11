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

Notes
- The model requires live traffic (TomTom) and fuel price (gov or env var). If TomTom key is not set, the app returns sample segments.
- Data is cached in `sources/_cache` (file-based). Cache TTLs: traffic 300s, air 600s, fuel daily.
- Use `python run_reproduce.py` to export latest raw JSON for reproducibility.
- If `vehicle_count_mode = normalized_per_probe`, all totals are normalized per probe; absolute totals require flow-based vehicle counts.
