# Derived Margin — Implementation Report

**Date:** 2026-03-25  
**Commit:** (pending)  
**Status:** Implemented in repo, NOT deployed

---

## 1. Summary

The retail margin component of the fuel price formula is now **derived** from the official consumer price rather than hardcoded. The system fetches the Energy Ministry's monthly PDF notice, extracts the official consumer self-service benzine 95 price, and computes:

```
margin = (official_price / (1 + VAT)) - wholesale_per_l - excise_per_l
```

The hardcoded 0.66 NIS/L remains as a fallback when the PDF is unavailable.

---

## 2. Official Price Source

**Source chosen:** Gov.il monthly fuel price notice PDF

- **URL pattern:** `https://www.gov.il/BlobFolder/news/fuel-{month}-{year}/he/fuel-{month}-{year}.pdf`
- **Parsing method:** Hebrew text regex extraction from PDF via PyPDF2
- **Patterns matched:**
  - `לא יעלה על X.XX ש"ח לליטר` ("shall not exceed X.XX NIS per liter")
  - `X.XX ש"ח לליטר ... שירות עצמי` (with "self-service" context)
- **Source type:** `gov_il_pdf`
- **Module:** `sources/fuel_official_price.py`

**Why PDF and not machine-readable:**
- The Energy Ministry does NOT publish the consumer price in any machine-readable format (JSON/CSV/CKAN)
- All 7 Energy Ministry datasets on data.gov.il were checked — none contain consumer prices (see `RETAIL_MARGIN_SOURCE_AUDIT.md`)
- The PDF is the only official publication of the consumer price

---

## 3. Adapter Chain

| Priority | Adapter | Source | Margin | When used |
|----------|---------|--------|--------|-----------|
| 1 | Derived margin | CKAN + gov.il PDF | Computed from official price | Primary — when all 3 sources available |
| 2 | CKAN + fallback | CKAN only | 0.66 hardcoded | When PDF unavailable |
| 3 | PDF full | gov.il PDF only | N/A (direct price) | When CKAN unavailable |
| 4 | ENV override | Environment variable | N/A | Emergency manual override |

---

## 4. Validation Rules

| Rule | Bounds | Behavior on failure |
|------|--------|-------------------|
| Derived margin range | 0.30 – 1.50 NIS/L | RuntimeError → fall to adapter 2 |
| Consumer price sanity | 4.00 – 12.00 NIS/L | RuntimeError → fall to next |
| Month alignment | CKAN vs official ≤ 1 month | >1 month: RuntimeError. ±1: warning + proceed |
| Positive margin | margin > 0 | Covered by lower bound |

---

## 5. Example Calculation (March 2026)

### Inputs
| Component | Value | Source |
|-----------|-------|--------|
| Official consumer price | 7.02 NIS/L | gov.il PDF `fuel-march-2026.pdf` |
| Wholesale (benzine 95 tanker) | 1683.87 NIS/kl | CKAN `orl-prices` |
| Excise (benzine) | 3604.33 NIS/kl | CKAN `excise` |
| VAT | 18% | Default |

### Calculation
```
net_price = 7.02 / 1.18 = 5.9492 NIS/L

wholesale_per_l = 1683.87 / 1000 = 1.68387 NIS/L
excise_per_l    = 3604.33 / 1000 = 3.60433 NIS/L

derived_margin  = 5.9492 - 1.68387 - 3.60433 = 0.6610 NIS/L

Validation: 0.30 ≤ 0.6610 ≤ 1.50 ✓

Consumer check: (1.68387 + 3.60433 + 0.6610) × 1.18 = 7.02 NIS/L ✓
```

---

## 6. When Fallback Is Used

The 0.66 fallback is used when:
1. The gov.il PDF is not yet published for the current/previous month
2. The PDF format changes and regex parsing fails
3. The derived margin falls outside the 0.30–1.50 range (data anomaly)
4. The CKAN month and PDF month are >1 month apart
5. Any network error fetching the PDF

In all these cases, the system logs a warning and transparently falls back to adapter 2.

---

## 7. Output Provenance

### Derived (adapter 1)
```json
{
  "source_id": "ckan+official:2026-03",
  "price_ils_per_l": 7.02,
  "raw": {
    "adapter": "ckan_derived_margin",
    "retail_margin_ils": 0.661,
    "retail_margin_source": "derived",
    "official_consumer_price_ils_per_l": 7.02,
    "official_source_id": "gov.il:fuel-notice:2026-03",
    "month_aligned": true
  }
}
```

### Fallback (adapter 2)
```json
{
  "source_id": "ckan:orl-prices:2026-03",
  "price_ils_per_l": 7.02,
  "raw": {
    "adapter": "ckan_datastore",
    "retail_margin_ils": 0.66,
    "retail_margin_source": "fallback (no official machine-readable source)"
  }
}
```

---

## 8. Test Coverage

### New tests added: 14

| Test file | Tests | Coverage |
|-----------|-------|----------|
| `test_fuel_parser.py` | +8 | Derived margin success, month alignment, invalid range, fallback chain, provenance |
| `test_fuel_official_price.py` | +6 | PDF extraction, sanity rejection, schema, HTTP 404 retry, comma decimals |

### Total test suite: 79 passed, 3 skipped

---

## 9. Files Changed

| File | Type | Description |
|------|------|-------------|
| `sources/fuel_official_price.py` | **New** | Official consumer price adapter (PDF) |
| `sources/fuel_govil.py` | Modified | 4-tier adapter chain, `_fetch_derived_margin()`, `_derive_margin()`, `_months_match()` |
| `traffic_app.py` | Modified | UI handles `ckan_derived_margin` adapter display |
| `tests/test_fuel_parser.py` | Modified | +8 derived margin tests, updated fallback chain tests |
| `tests/test_fuel_official_price.py` | **New** | 6 tests for official price module |
| `DERIVED_MARGIN_DESIGN.md` | **New** | Design document |
| `DERIVED_MARGIN_IMPLEMENTATION_REPORT.md` | **New** | This report |
| `README.md` | Modified | Updated adapter chain description |
| `DEPLOYMENT_NOTES_OFFICIAL_SOURCES.md` | Modified | Updated chain, added derived margin limitation |

---

## 10. Deployment Note

**This change is NOT deployed.** It exists only in the local repository.

To deploy, copy the new/modified files to the server and restart:
```bash
scp sources/fuel_official_price.py admin@37.27.244.96:/opt/Life/sources/
scp sources/fuel_govil.py admin@37.27.244.96:/opt/Life/sources/
scp traffic_app.py admin@37.27.244.96:/opt/Life/
scp tests/test_fuel_parser.py tests/test_fuel_official_price.py admin@37.27.244.96:/opt/Life/tests/
ssh admin@37.27.244.96 'rm -f /opt/Life/sources/_cache/fuel_govil.json && sudo systemctl restart ayalon-ui'
```
