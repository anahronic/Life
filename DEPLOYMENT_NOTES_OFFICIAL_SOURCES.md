# Deployment Notes — Official Gov.il Machine-Readable Sources

**Date:** 2026-03-25  
**Scope:** Replace fragile PDF parsing with official data.gov.il CKAN datastore for fuel prices; derive retail margin from official consumer price; remove mandatory `st.secrets` dependency from official stats.

---

## What Changed

### New file: `sources/gov_catalog.py`
Thin CKAN client for data.gov.il with pinned resource IDs:
- `FUEL_ORL_PRICES_RESOURCE` → wholesale benzine-95 prices (monthly)
- `FUEL_EXCISE_RESOURCE` → benzine excise tax (monthly)
- Helpers: `fetch_latest_benzine95_wholesale()`, `fetch_latest_benzine_excise()`
- All resource IDs configurable via env vars

### Rewritten: `sources/fuel_govil.py`
Four-adapter chain (first success wins):
1. **Derived margin** — CKAN wholesale + excise + official PDF consumer price → derived margin
2. **CKAN + fallback margin** — CKAN wholesale + excise + 0.66 hardcoded margin
3. **PDF notice** — legacy fallback, downloads monthly PDF from gov.il
4. **`FUEL_PRICE_ILS` env var** — emergency override

**Derived margin formula (adapter 1):**
```
margin = (official_consumer_price / (1 + VAT)) - wholesale_per_l - excise_per_l
```

**Fallback consumer formula (adapter 2):**
```
consumer = (wholesale_per_l + excise_per_l + RETAIL_MARGIN_ILS) × (1 + VAT_RATE)
```
- Wholesale: `orl-prices` resource, product "בנזין 95 אוקטן נטול עופרת במכלית"
- Excise: `excise` resource, product "בלו בנזין (סעיף 1 לתוספת לצו)"
- Default margin: 0.66 NIS/L (fallback), default VAT: 18%
- Verified: (1683.87/1000 + 3604.33/1000 + 0.66) × 1.18 = **7.02 NIS/L** (March 2026)

### New: `sources/fuel_official_price.py`
Standalone module to fetch official consumer benzine-95 self-service price from gov.il PDF.
Used by derived margin adapter. See `DERIVED_MARGIN_DESIGN.md`.

### Rewritten: `sources/official_stats.py`
- Env-first config — reads `OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR` from env
- Mode via `OFFICIAL_STATS_SOURCE_MODE`: `auto` | `url` | `static` | `disabled`
- No `st.secrets` or `SecureConfig` dependency
- Returns benign "unconfigured" stub when no source configured (instead of error)

### Modified: `traffic_app.py`
- Fuel provenance display shows adapter detail: derived margin, CKAN+fallback breakdown, PDF URL, or env warning
- Shows "(derived)" or "⚠ fallback" next to margin value; month-offset warning when CKAN/official months differ
- All 4 language I18N strings updated: "secrets" → "env"
- Stale cache warning when `:cached` suffix detected

### New tests:
- `tests/test_fuel_parser.py` — 26 tests covering all 4 adapters (derived margin, CKAN+fallback, PDF, env), cache, errors, provenance
- `tests/test_fuel_official_price.py` — 6 tests covering official consumer price PDF adapter (extraction, sanity, schema, retry, comma decimals)
- `tests/test_gov_catalog.py` — 31 tests covering datastore queries, schema validation, unit validation
- `tests/test_official_stats.py` — 13 tests covering all modes, no-secrets assertion

**Total: 82 tests collected, 79 pass, 3 skipped (opt-in live integration)**

---

## CKAN Dataset Reference

| Dataset | Resource ID | API Field |
|---------|------------|-----------|
| orl-prices (wholesale) | `aaa40832-ac82-4c86-bac6-0d05c83f576f` | `מחיר` (NIS/kl) |
| excise (tax rates) | `bdce45e7-9fe9-473e-bd51-cef1d787a951` | `מחיר` (NIS/kl) |
| orl (theoretical import) | `157689c0-69fb-4923-8b27-c780ed64199d` | `מחיר` (NIS/kl) |

All queried via: `https://data.gov.il/api/3/action/datastore_search`

---

## New Environment Variables

### Required: none (CKAN API is public)

### Optional:
| Variable | Default | Purpose |
|----------|---------|---------|
| `FUEL_VAT_RATE` | `0.18` | VAT rate for consumer price formula |
| `FUEL_RETAIL_MARGIN_ILS` | `0.66` | Distribution + retail margin (NIS/L, before VAT). **Fallback** — no official source; see `RETAIL_MARGIN_SOURCE_AUDIT.md` |
| `FUEL_PRICE_ILS` | — | Emergency manual override (skip all adapters) |
| `CKAN_FUEL_ORL_PRICES_RESOURCE` | `aaa40832-...` | Wholesale resource UUID |
| `CKAN_FUEL_EXCISE_RESOURCE` | `bdce45e7-...` | Excise resource UUID |
| `CKAN_TIMEOUT_S` | `20` | CKAN API timeout |
| `OFFICIAL_STATS_SOURCE_MODE` | `auto` | Benchmark mode: auto/url/static/disabled |
| `OFFICIAL_STATS_JSON_URL` | — | JSON URL for benchmark data |
| `OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR` | — | Static benchmark value |
| `OFFICIAL_SOURCE_LABEL` | — | Human-readable label for benchmark source |

---

## Deployment Steps

```bash
# 1. Copy source modules
scp sources/gov_catalog.py admin@37.27.244.96:/opt/Life/sources/
scp sources/fuel_govil.py admin@37.27.244.96:/opt/Life/sources/
scp sources/fuel_official_price.py admin@37.27.244.96:/opt/Life/sources/
scp sources/official_stats.py admin@37.27.244.96:/opt/Life/sources/

# 2. Copy app + config
scp traffic_app.py admin@37.27.244.96:/opt/Life/
scp README.md admin@37.27.244.96:/opt/Life/
scp .streamlit/secrets.toml.example admin@37.27.244.96:/opt/Life/.streamlit/

# 3. Copy tests
scp tests/test_fuel_parser.py admin@37.27.244.96:/opt/Life/tests/
scp tests/test_fuel_official_price.py admin@37.27.244.96:/opt/Life/tests/
scp tests/test_gov_catalog.py admin@37.27.244.96:/opt/Life/tests/
scp tests/test_official_stats.py admin@37.27.244.96:/opt/Life/tests/

# 4. Copy documentation
scp DEPLOYMENT_NOTES_OFFICIAL_SOURCES.md admin@37.27.244.96:/opt/Life/
scp RETAIL_MARGIN_SOURCE_AUDIT.md admin@37.27.244.96:/opt/Life/
scp DERIVED_MARGIN_DESIGN.md admin@37.27.244.96:/opt/Life/
scp DERIVED_MARGIN_IMPLEMENTATION_REPORT.md admin@37.27.244.96:/opt/Life/

# 5. Clear stale fuel cache
ssh admin@37.27.244.96 'rm -f /opt/Life/sources/_cache/fuel_govil.json'

# 6. Restart service
ssh admin@37.27.244.96 'sudo systemctl restart ayalon-ui'

# 7. Validate
curl -sI https://dikenocracy.com/ayalon/ | head -5
# Should return HTTP/2 200
```

---

## Rollback

The 4-tier chain degrades gracefully — each adapter failure falls through to the next:
- Derived margin fails → CKAN + fallback margin (0.66)
- CKAN fails → PDF direct consumer price
- PDF fails → ENV override

Full manual override:
1. Set `FUEL_PRICE_ILS=7.02` in `/etc/default/ayalon-monitor`
2. Restart: `sudo systemctl restart ayalon-ui`
3. The env adapter (tier 4) will provide the price immediately, bypassing all other adapters

---

## Known Limitations

- **Derived margin depends on PDF parsing:** The primary adapter derives the retail margin from the official consumer price PDF. If the Energy Ministry changes the PDF format, deriving will fail and the system falls back to hardcoded 0.66 NIS/L.
- **Retail margin fallback value:** The 0.66 NIS/L margin is back-calculated from March 2026 data. No official machine-readable source for the retail/distribution margin exists on data.gov.il (Israeli fuel prices at the pump are deregulated since 2007). See `RETAIL_MARGIN_SOURCE_AUDIT.md` for the full audit trail.
- **CKAN SQL forbidden:** `datastore_search_sql` returns HTTP 403 on data.gov.il; we use field `filters=` for deterministic exact-match queries.
- **No congestion datasets on data.gov.il:** Transport/congestion data was not found; official benchmark must be configured manually.
- **Product names in Hebrew:** CKAN record matching depends on exact Hebrew product names. If the Ministry changes naming conventions, update constants in `gov_catalog.py`.
