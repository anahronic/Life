# Derived Margin — Design Document

**Date:** 2026-03-25  
**Status:** Implemented (repo-only, not deployed)

---

## 1. Problem Statement

The consumer fuel price formula requires three components:

```
consumer = (wholesale + excise + retail_margin) × (1 + VAT)
```

Wholesale and excise come from CKAN (machine-readable). The retail margin was previously a **hardcoded fallback** (0.66 NIS/L) because no official machine-readable source exists for this component (see `RETAIL_MARGIN_SOURCE_AUDIT.md`).

**Goal:** Derive the margin from the official consumer price published in the Energy Ministry's monthly PDF notice, instead of hardcoding it.

---

## 2. Core Formula

```
margin = (official_consumer_price / (1 + VAT)) - wholesale_per_l - excise_per_l
```

Where:
- `official_consumer_price` — benzine 95, self-service, incl. VAT (ILS/L) — from gov.il PDF
- `VAT` — default 0.18, configurable via `FUEL_VAT_RATE`
- `wholesale_per_l` — from CKAN resource `orl-prices` (NIS/kl ÷ 1000)
- `excise_per_l` — from CKAN resource `excise` (NIS/kl ÷ 1000)

### Example (March 2026)

```
official_price = 7.02 NIS/L
net = 7.02 / 1.18 = 5.9492 NIS/L
wholesale = 1683.87 / 1000 = 1.68387 NIS/L
excise = 3604.33 / 1000 = 3.60433 NIS/L
margin = 5.9492 - 1.68387 - 3.60433 = 0.661 NIS/L
```

Verification: `(1.68387 + 3.60433 + 0.661) × 1.18 ≈ 7.02` ✓

---

## 3. Architecture

### Adapter Chain (priority order)

```
1. Derived margin    — CKAN wholesale + CKAN excise + official PDF price → derived margin
2. CKAN + fallback   — CKAN wholesale + CKAN excise + 0.66 hardcoded → consumer estimate
3. PDF full fallback — Gov.il PDF notice → direct consumer price (no component breakdown)
4. ENV override      — FUEL_PRICE_ILS env var → emergency manual price
```

### New Module: `sources/fuel_official_price.py`

Standalone module to fetch the official consumer price:

```python
def fetch_official_benzine95_self_service_price() -> dict:
    """Returns {source_id, source_type, fetched_at_utc, effective_year_month,
               price_ils_per_l, raw}"""
```

- Tries current month PDF, then previous month
- Parses Hebrew text with regex (same patterns as legacy adapter)
- Returns `source_type: "gov_il_pdf"`

### Modified: `sources/fuel_govil.py`

New function `_fetch_derived_margin()`:
1. Calls `fetch_latest_benzine95_wholesale()` (CKAN)
2. Calls `fetch_latest_benzine_excise()` (CKAN)
3. Calls `fetch_official_benzine95_self_service_price()` (PDF)
4. Computes `margin = (official / (1+VAT)) - wholesale - excise`
5. Validates margin range and month alignment
6. Returns consumer price with `retail_margin_source: "derived"`

---

## 4. Validation Rules

| Check | Rule | On failure |
|-------|------|------------|
| Margin range | `0.30 ≤ margin ≤ 1.50` NIS/L | Raise → fall through to adapter 2 |
| Consumer price sanity | `4.00 ≤ price ≤ 12.00` NIS/L | Raise → fall through |
| Month alignment | CKAN month vs official month ≤ 1 month apart | >1: Raise. =1: Proceed with warning |
| Margin positive | `margin > 0` | Implicitly covered by min bound |

---

## 5. Output Schema Extension

When derived margin is used, the `raw` dict includes:

```json
{
  "adapter": "ckan_derived_margin",
  "retail_margin_ils": 0.661,
  "retail_margin_source": "derived",
  "official_consumer_price_ils_per_l": 7.02,
  "official_source_id": "gov.il:fuel-notice:2026-03",
  "official_source_type": "gov_il_pdf",
  "month_aligned": true,
  "wholesale_per_l": 1.6839,
  "excise_per_l": 3.6043,
  "vat_rate": 0.18,
  ...
}
```

When fallback margin is used:

```json
{
  "adapter": "ckan_datastore",
  "retail_margin_ils": 0.66,
  "retail_margin_source": "fallback (no official machine-readable source)",
  ...
}
```

---

## 6. Risks

| Risk | Mitigation |
|------|-----------|
| PDF format changes | Regex patterns are broad; fallback chain catches failures |
| PDF not published yet for current month | Tries previous month; then falls to adapter 2 |
| VAT rate changes | Configurable via `FUEL_VAT_RATE` env var |
| Rounding discrepancies | Margin stored to 4 decimal places; consumer price rounded to 2 |
| CKAN/official month mismatch | ±1 month tolerance with warning; >1 month rejected |
| Gov.il downtime | Falls through to CKAN+fallback → PDF → ENV |

---

## 7. UI Changes

The Sources tab shows:
- **Derived:** `Margin: 0.66 ₪/L (derived) × (1+VAT)` — with month offset warning if applicable
- **Fallback:** `Margin: 0.66 ₪/L ⚠ fallback × (1+VAT)`
- **PDF direct:** `Parsed from: <URL>`
- **ENV:** `⚠ Manual env override (FUEL_PRICE_ILS)`

---

## 8. Files

| File | Role |
|------|------|
| `sources/fuel_official_price.py` | New — official consumer price adapter (PDF) |
| `sources/fuel_govil.py` | Modified — 4-tier chain, derived margin logic |
| `traffic_app.py` | Modified — UI handles `ckan_derived_margin` adapter |
| `tests/test_fuel_parser.py` | Modified — +8 derived margin tests |
| `tests/test_fuel_official_price.py` | New — 6 tests for official price adapter |
