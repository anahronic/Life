# Ayalon Real-Time Physical Impact Model — Freeze Notes

## Version: v1.0 Freeze

**Status:** ACCEPTED (Normalized mode)

### Core Parameters

- **Mode:** `normalized_per_probe`
- **Fuel:** Gov.il monthly notice PDF (consumer self-service 95 octane incl. VAT)
- **Update cadence:** 5 min cache TTL (traffic), daily (fuel)
- **Reproduce:** Weekly export enabled (CI workflow)
- **Known limitation:** `vehicle_count` not absolute; normalized per probe until flow-based counts are available

### PTL Posture

- **Fail-closed:** Parser raises RuntimeError if source structure changes or price out of sanity range (4–12 ILS/L)
- **Provenance:** Complete source_id tracking (gov.il:fuel-notice:YYYY-MM, tomtom:flow/sample)
- **Reproducibility:** `python run_reproduce.py` exports raw/*.json with all source timestamps and vehicle_count_mode

### UI Indicators

When `vehicle_count_mode = normalized_per_probe`:
- Banner: "Normalized metrics (per probe). Totals are not absolute until flow-based vehicle counts are available."
- Energy-to-Capital caption: "Normalized (per probe)"

### Next Steps (v1.1 target)

1. **Vehicle-count:** Obtain flow-based counts from TomTom API (currentFlow/currentFlowInVph) or alternative official source
2. **IEC visualization:** Add Investment Efficiency Coefficient overlay
3. **Exposure overlay (optional):** NOx/PM/Noise from Sviva or fail-honest placeholder

---

**Frozen:** 2026-01-08  
**Baseline commit:** d284bfa (Ayalon PTL baseline: fuel notice parser, tests, reproduce)
