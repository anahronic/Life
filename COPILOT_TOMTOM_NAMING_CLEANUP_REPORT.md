# TomTom Naming Cleanup Report

**Date:** 2026-03-25  
**Scope:** Final consistency pass — `TOMTOM_QUOTA_PER_HOUR` → `TOMTOM_QUOTA_PER_DAY`

---

## Problem

After the rate-limiter rewrite (daily quota with persistent enforcement), several
files still used the legacy `TOMTOM_QUOTA_PER_HOUR` naming as if it were the
canonical name.  This was confusing: the TomTom free plan is **2 500 calls/day**,
not per hour.

## Changes Applied

| # | File | Change |
|---|------|--------|
| 1 | `sources/secure_config.py` | Renamed `get_quota_per_hour()` → `get_quota_per_day()`. New method reads `TOMTOM_QUOTA_PER_DAY` first, falls back to `TOMTOM_QUOTA_PER_HOUR`. Old name kept as class-level alias. |
| 2 | `.streamlit/secrets.toml.example` | `TOMTOM_QUOTA_PER_HOUR = 2500` → `TOMTOM_QUOTA_PER_DAY = 2500` |
| 3 | `sources/tomtom.py.bak.pre_daily_fix` | **Deleted** |
| 4 | `sources/rate_limiter.py.bak.pre_daily_fix` | **Deleted** |
| 5 | `sources/history_store.py.bak.20260325_150517` | **Deleted** |
| 6 | `sources/official_stats.py.bak.20260325_150517` | **Deleted** |

## Remaining `QUOTA_PER_HOUR` References (intentional)

All remaining occurrences are **explicit backward-compatibility fallbacks**:

| File | Line | Purpose |
|------|------|---------|
| `sources/rate_limiter.py` | 11, 139, 142 | Docstring + env-var fallback |
| `sources/tomtom.py` | 13-14 | Same env-var fallback chain |
| `sources/secure_config.py` | 66, 69, 73 | Docstring + fallback + alias |

## Validation

| Check | Result |
|-------|--------|
| `secure_config.py` AST parse | OK |
| Service restart (`ayalon-ui`) | active |
| HTTP 200 on `/ayalon/` | OK |
| Streamlit health | ok |
| No `.bak` files remaining | OK |
