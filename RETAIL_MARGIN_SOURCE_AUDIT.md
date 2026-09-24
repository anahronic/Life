# Retail Margin Source Audit — data.gov.il

**Date:** 2026-03  
**Conclusion:** ❌ No official machine-readable source for the retail/distribution margin component exists on data.gov.il.  
**Current fallback:** `FUEL_RETAIL_MARGIN_ILS = 0.66` NIS/L (before VAT)

---

## 1. Background

The Ayalon model computes the consumer self-service gasoline 95 price using:

```
consumer = (wholesale_per_l + excise_per_l + retail_margin) × (1 + VAT)
```

- **Wholesale** — sourced from CKAN resource `aaa40832-ac82-4c86-bac6-0d05c83f576f` (orl-prices)
- **Excise** — sourced from CKAN resource `bdce45e7-9fe9-473e-bd51-cef1d787a951` (excise)
- **Retail margin** — the gap between (wholesale + excise) and the consumer price, covering distributor/retailer costs, profit, and self-service station operations

The retail margin is the only component without an official machine-readable source. This audit documents the exhaustive search performed to either find such a source or conclusively prove none exists.

---

## 2. Regulatory Context

**Israeli fuel prices were deregulated in January 2007.**

The Energy Ministry's own page (`gov.il/he/pages/theory_rate_fuel_price`) states:

> מחירי הדלקים המיוצרים בבתי הזיקוק בישראל אינם מפוקחים על ידי המדינה  
> (Fuel prices produced in Israeli refineries are NOT regulated by the state)

> ...לצרכי מידע בלבד, ואין להם כל תוקף מחייב  
> (...for informational purposes only, with no binding validity)

Since deregulation, the retail margin is a **market-determined** component set by fuel companies. The government does not publish, regulate, or digitize this figure.

---

## 3. Complete Energy Ministry Dataset Inventory

All datasets published by the Ministry of Energy & Water on data.gov.il were enumerated using:

```
GET /api/3/action/package_search?fq=organization:energy_and_water&rows=20
```

Organization ID: `08137ad2-c18f-48ec-879b-02de3c7200e2`

| # | Dataset | Resource ID | Content | Has Margin? |
|---|---------|------------|---------|-------------|
| 1 | **orl-prices** | `aaa40832-ac82-4c86-bac6-0d05c83f576f` | Computed wholesale prices (monthly, 12 products) | ❌ Only wholesale price per product |
| 2 | **orl** | `157689c0-69fb-4923-8b27-c780ed64199d` | Theoretical import prices (CIF) | ❌ Import prices only |
| 3 | **excise** | `bdce45e7-9fe9-473e-bd51-cef1d787a951` | Excise tax rates (monthly) | ❌ Tax rates only |
| 4 | **fuelstationbynumber** | `ff3b653c-...` | Fuel station registry by number | ❌ No price data at all |
| 5 | **gas-station** | `5537a0ef-...` | Station list with coordinates/company/address | ❌ No price data at all |
| 6 | **kriahaziva** | `bcc719c8-...` | Quarries and mining areas | ❌ Irrelevant |
| 7 | **raw-material-deposits** | `a5408d43-...` | Raw material deposits | ❌ Irrelevant |

**Result: Exactly 7 datasets. NONE contain retail margin, consumer self-service price, or any price breakdown beyond wholesale/excise.**

---

## 4. Schema Analysis of Fuel Price Datasets

### orl-prices (wholesale)
- Fields: `תאריך`, `מוצר`, `יחידת מידה`, `מחיר` (4 columns only)
- Products: 12 products including "בנזין 95 אוקטן נטול עופרת במכלית" and "בנזין 95 אוקטן נטול עופרת בהזרמה"
- March 2026 benzine-95 tanker price: **1683.87 NIS/kl**
- No consumer price, no margin, no breakdown

### excise
- Fields: `תאריך`, `מוצר`, `יחידות`, `מחיר` (4 columns only)
- Products: 8 products including "בלו בנזין (סעיף 1 לתוספת לצו)"
- March 2026 benzine excise: **3604.33 NIS/kl**
- No consumer price, no margin, no breakdown

### orl (theoretical import)
- Fields: `תאריך`, `מוצר`, `יחידת מידה`, `מחיר` (4 columns only)
- Theoretical CIF import prices for informational purposes
- No consumer price, no margin

---

## 5. CKAN Free-Text Searches Performed

All queries were run against `https://data.gov.il/api/3/action/package_search?q=...`

| # | Query (Hebrew) | Translation | Results |
|---|---------------|-------------|---------|
| 1 | `מרווח שיווק דלק` | marketing margin fuel | **0 results** |
| 2 | `מרכיבי מחיר דלק` | fuel price components | 1 result: orl (no margin) |
| 3 | `מחיר מרבי בנזין 95` | maximum benzine-95 price | **0 results** |
| 4 | `פיקוח מחירי דלק` | fuel price regulation | 3 results: orl-prices, orl, price_controlled_consumer_products¹ |
| 5 | `בנזין שירות עצמי` | benzine self-service | EV charging stations (irrelevant) |
| 6 | `דלק צרכן` | fuel consumer | **0 results** |
| 7 | `מחיר דלק לצרכן` | consumer fuel price | 1 result: orl (no margin) |
| 8 | `עדכון מחיר דלק` | fuel price update | 1 result: orl (no margin) |

¹ `price_controlled_consumer_products` (resource `0a760550`) — Ministry of Economy dataset for controlled consumer goods: eggs, cheese, bread. **NOT fuel.**

---

## 6. Gov.il Portal Pages Checked

| URL | Content | Has Margin? |
|-----|---------|-------------|
| `gov.il/he/pages/theory_rate_fuel_price` | Theoretical fuel prices explanation | ❌ States prices are informational only |
| `gov.il/he/pages/fuel-price` | Monthly fuel price notices | ❌ JS-rendered shell, PDF links |
| `gov.il/he/pages/fuel_prices_regulation` | Fuel regulation info | ❌ JS-rendered shell |
| `gov.il/he/pages/fuel_prices_update` | Price update notices | ❌ JS-rendered shell |

The gov.il pages for fuel prices are server-rendered with JavaScript; the actual PDF notices contain consumer prices but the retail margin is never published separately — only the final consumer price.

---

## 7. How the Fallback Value Was Derived

The 0.66 NIS/L margin was **back-calculated** from the known March 2026 consumer price:

```
Official consumer self-service benzine 95 price: 7.02 NIS/L (incl. VAT)

Pre-VAT price = 7.02 / 1.18 = 5.9492 NIS/L

Wholesale per L = 1683.87 / 1000 = 1.68387 NIS/L
Excise per L    = 3604.33 / 1000 = 3.60433 NIS/L
Sum             = 5.28820 NIS/L

Retail margin   = 5.9492 - 5.2882 = 0.6610 ≈ 0.66 NIS/L
```

Verification: `(1.68387 + 3.60433 + 0.66) × 1.18 = 7.02 NIS/L` ✓

---

## 8. Recommendation

1. **Keep the fallback constant** at 0.66 NIS/L — it produces the correct consumer price for the current period.
2. **Expose via `FUEL_RETAIL_MARGIN_ILS` env var** — allows immediate correction if the margin changes.
3. **Mark provenance as "fallback"** in the output dict (`retail_margin_source` field) — the UI now shows a ⚠ indicator.
4. **Periodic review:** If the Energy Ministry adds a consumer price dataset or a margin breakdown to data.gov.il in the future, this adapter is designed to be easily extended with Adapter 0 (CKAN margin) that would supersede the fallback.
5. **Alternative validation:** Cross-check the derived consumer price against the monthly PDF notices (Adapter 2) when available. If the PDF price diverges significantly from the CKAN-derived price, the margin may have drifted.

---

## 9. Files Modified in This Audit

| File | Change |
|------|--------|
| `sources/fuel_govil.py` | Added `_RETAIL_MARGIN_IS_FALLBACK` flag; expanded comments explaining fallback; added `retail_margin_source` to CKAN adapter output |
| `traffic_app.py` | UI now shows "⚠ fallback" alongside margin value when using hardcoded default |
| `tests/test_fuel_parser.py` | Added `test_margin_provenance_fallback` and `test_margin_provenance_env_override` tests |
| `DEPLOYMENT_NOTES_OFFICIAL_SOURCES.md` | Updated Known Limitations |
| `RETAIL_MARGIN_SOURCE_AUDIT.md` | This file |

---

*Audit conducted: March 2026. Reviewed all 7 Energy Ministry datasets, 8+ CKAN text searches, 4 gov.il pages. Conclusion: no official machine-readable source exists for the retail margin.*
