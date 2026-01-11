# Freeze Manifest — Ayalon Real-Time Physical Impact Model v1.0

**Frozen:** 2026-01-08  
**Status:** Production-grade freeze (normalized mode)  
**Baseline commit:** 03e5991

## Runtime Environment

```
Python: 3.10.12
OS: Linux
```

## Locked Dependencies

```
streamlit==1.52.2
pyluach==2.3.0
requests==2.32.5
pandas==2.3.3
openpyxl==3.1.5
PyPDF2==3.0.1
pytest==6.2.5
```

## Data Sources

- **Traffic:** TomTom Flow API (fallback: synthetic sample)  
  - Mode: `normalized_per_probe` (vehicle_count=1 per segment)  
  - Cache TTL: 300s
  
- **Fuel:** Gov.il monthly notice PDF (consumer self-service 95 octane incl. VAT)  
  - Source: `https://www.gov.il/BlobFolder/news/fuel-{month}-{year}/he/fuel-{month}-{year}.pdf`  
  - Sanity guard: 4–12 ILS/L (fail-closed)  
  - Cache TTL: 86400s

- **Air Quality:** Sviva API (station-based)  
  - Cache TTL: 600s

## Model Constants

See: `LOCKED_CONSTANTS.json`

- V_free: 90.0 km/h
- Fuel_idle_rate: 0.8 L/h
- StopGo_factor: 1.5
- CO2_per_liter: 2.31 kg/L

## Verification Commands

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run tests
```bash
pytest -q
# Expected: 6 passed, 1 skipped
```

### 3. Run reproduce (no API keys)
```bash
python run_reproduce.py
# Exports: raw/tomtom.json, raw/sviva.json, raw/fuel.json
```

### 4. Run Streamlit monitor
```bash
streamlit run traffic_app.py
# Opens: http://localhost:8501
# Shows: normalized mode banner if TOMTOM_API_KEY unset
```

### 5. Run methodology demo
```bash
python methodology.py
# Outputs: JSON with provenance
```

## Known Limitations

- **vehicle_count:** Normalized per probe (not absolute totals) until flow-based counts available
- **TomTom API:** Requires `TOMTOM_API_KEY` env var for live traffic data
- **Fuel price:** Falls back to `FUEL_PRICE_ILS` env var if PDF unavailable

## PTL Posture

- **Fail-closed:** Parser raises RuntimeError on structure change or out-of-range values
- **Provenance:** Complete source_id tracking for all data layers
- **Reproducibility:** Weekly CI export enabled (`.github/workflows/reproduce_weekly.yml`)

## Next Steps (v1.1 target)

1. Obtain flow-based vehicle counts from TomTom API (`currentFlow`/`currentFlowInVph`)
2. Add IEC (Investment Efficiency Coefficient) visualization
3. Add Exposure overlay (NOx/PM/Noise)

---

**Frozen by:** GitHub Copilot (Claude Sonnet 4.5)  
**Audit:** See `AUDIT_REPORT.md`, `IMPLEMENTATION_REPORT.md`
