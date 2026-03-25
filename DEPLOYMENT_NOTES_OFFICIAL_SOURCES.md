# Deployment Notes — Official Gov.il Machine-Readable Sources

**Date:** 2026-03-XX  
**Scope:** Replace fragile PDF parsing with official data.gov.il CKAN datastore for fuel prices; remove mandatory `st.secrets` dependency from official stats.

---

## What Changed

### New file: `sources/gov_catalog.py`
Thin CKAN client for data.gov.il with pinned resource IDs:
- `FUEL_ORL_PRICES_RESOURCE` → wholesale benzine-95 prices (monthly)
- `FUEL_EXCISE_RESOURCE` → benzine excise tax (monthly)
- Helpers: `fetch_latest_benzine95_wholesale()`, `fetch_latest_benzine_excise()`
- All resource IDs configurable via env vars

### Rewritten: `sources/fuel_govil.py`
Three-adapter chain (first success wins):
1. **CKAN datastore** — queries data.gov.il for wholesale + excise, applies consumer formula
2. **PDF notice** — legacy fallback, downloads monthly PDF from gov.il
3. **`FUEL_PRICE_ILS` env var** — emergency override

**Consumer price formula:**
```
consumer = (wholesale_per_l + excise_per_l + RETAIL_MARGIN_ILS) × (1 + VAT_RATE)
```
- Wholesale: `orl-prices` resource, product "בנזין 95 אוקטן נטול עופרת במכלית"
- Excise: `excise` resource, product "בלו בנזין (סעיף 1 לתוספת לצו)"
- Default margin: 0.66 NIS/L, default VAT: 18%
- Verified: (1683.87/1000 + 3604.33/1000 + 0.66) × 1.18 = **7.02 NIS/L** (March 2026)

### Rewritten: `sources/official_stats.py`
- Env-first config — reads `OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR` from env
- Mode via `OFFICIAL_STATS_SOURCE_MODE`: `auto` | `url` | `static` | `disabled`
- No `st.secrets` or `SecureConfig` dependency
- Returns benign "unconfigured" stub when no source configured (instead of error)

### Modified: `traffic_app.py`
- Fuel provenance display shows adapter detail (CKAN breakdown, PDF URL, or env warning)
- All 4 language I18N strings updated: "secrets" → "env"
- Stale cache warning when `:cached` suffix detected

### New tests:
- `tests/test_fuel_parser.py` — 17 tests covering all 3 adapters, cache, errors
- `tests/test_gov_catalog.py` — 12 tests covering datastore queries, schema validation
- `tests/test_official_stats.py` — 13 tests covering all modes, no-secrets assertion

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
| `FUEL_RETAIL_MARGIN_ILS` | `0.66` | Distribution + retail margin (NIS/L, before VAT) |
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
# 1. Copy changed files to server
scp sources/gov_catalog.py admin@37.27.244.96:/opt/Life/sources/
scp sources/fuel_govil.py admin@37.27.244.96:/opt/Life/sources/
scp sources/official_stats.py admin@37.27.244.96:/opt/Life/sources/
scp traffic_app.py admin@37.27.244.96:/opt/Life/
scp tests/test_fuel_parser.py tests/test_gov_catalog.py tests/test_official_stats.py admin@37.27.244.96:/opt/Life/tests/
scp .streamlit/secrets.toml.example admin@37.27.244.96:/opt/Life/.streamlit/
scp README.md admin@37.27.244.96:/opt/Life/

# 2. Clear stale fuel cache
ssh admin@37.27.244.96 'rm -f /opt/Life/sources/_cache/fuel_govil.json'

# 3. Restart service
ssh admin@37.27.244.96 'sudo systemctl restart ayalon-ui'

# 4. Validate
curl -sI https://dikenocracy.com/ayalon/ | head -5
# Should return HTTP/2 200
```

---

## Rollback

If the CKAN adapter fails in production:
1. Set `FUEL_PRICE_ILS=7.02` in `/etc/default/ayalon-monitor`
2. Restart: `sudo systemctl restart ayalon-ui`
3. The env adapter will provide the price immediately

---

## Known Limitations

- **Retail margin drift:** The 0.66 NIS/L margin is derived from March 2026 data. If the Energy Ministry changes distribution margins, update `FUEL_RETAIL_MARGIN_ILS`.
- **CKAN SQL forbidden:** `datastore_search_sql` returns HTTP 403 on data.gov.il; we use full-text `q=` search instead.
- **No congestion datasets on data.gov.il:** Transport/congestion data was not found; official benchmark must be configured manually.
- **Product names in Hebrew:** CKAN record matching depends on exact Hebrew product names. If the Ministry changes naming conventions, update constants in `gov_catalog.py`.
