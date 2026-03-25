"""
Fuel price source: fetch consumer self-service gasoline 95 price (ILS/L) from official Gov.il data.

Adapter chain (tried in order, first success wins):
  1. data.gov.il CKAN datastore -- machine-readable wholesale price + excise -> consumer formula
  2. Gov.il monthly notice PDF -- direct consumer price extraction (legacy, more fragile)
  3. FUEL_PRICE_ILS environment variable -- emergency manual override

All adapters return the same stable output schema (see ``_build_output``).
"""

import html
import io
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional, Tuple

import requests

from .cache import cache_read, cache_write

logger = logging.getLogger(__name__)

# -- Constants ---------------------------------------------------------------
PRICE_MIN = 4.0   # ILS/L -- sanity floor
PRICE_MAX = 12.0  # ILS/L -- sanity ceiling

# Consumer-price formula components (configurable via env)
VAT_RATE = float(os.getenv("FUEL_VAT_RATE", "0.18"))
# Distribution + retail self-service margin (NIS/L, before VAT).
# Default 0.66 derived from March 2026: (7.02/1.18) - (1683.87+3604.33)/1000
RETAIL_MARGIN_ILS = float(os.getenv("FUEL_RETAIL_MARGIN_ILS", "0.66"))

# PDF template for legacy fallback
NOTICE_PDF_TEMPLATE = (
    "https://www.gov.il/BlobFolder/news/fuel-{month_slug}-{year}"
    "/he/fuel-{month_slug}-{year}.pdf"
)
NOTICE_MONTH_SLUGS = {
    1: "january", 2: "february", 3: "march", 4: "april",
    5: "may", 6: "june", 7: "july", 8: "august",
    9: "september", 10: "october", 11: "november", 12: "december",
}

CACHE_KEY = "fuel_govil"


# -- Utility -----------------------------------------------------------------

def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_output(
    price: float,
    source_id: str,
    effective_ym: str,
    raw: dict,
) -> dict:
    """Canonical output schema returned by every adapter."""
    return {
        "source_id": source_id,
        "fetched_at_utc": _utc_iso(),
        "effective_year_month": effective_ym,
        "price_ils_per_l": round(price, 2),
        "raw": raw,
    }


# -- Adapter 1: data.gov.il CKAN datastore -----------------------------------

def _fetch_from_ckan() -> dict:
    """Query data.gov.il for wholesale benzine-95 price + excise, compute consumer price.

    Uses the ``gov_catalog`` module which pins known resource IDs.
    """
    from .gov_catalog import (
        fetch_latest_benzine95_wholesale,
        fetch_latest_benzine_excise,
    )

    wholesale = fetch_latest_benzine95_wholesale()
    excise = fetch_latest_benzine_excise()

    wholesale_per_l = wholesale["price_per_kl"] / 1000.0
    excise_per_l = excise["excise_per_kl"] / 1000.0

    # Consumer = (wholesale + excise + distribution/retail margin) * (1 + VAT)
    consumer_estimate = (wholesale_per_l + excise_per_l + RETAIL_MARGIN_ILS) * (1 + VAT_RATE)
    consumer_estimate = round(consumer_estimate, 2)

    # Sanity check
    if not (PRICE_MIN <= consumer_estimate <= PRICE_MAX):
        raise RuntimeError(
            f"CKAN-derived consumer price {consumer_estimate} outside "
            f"[{PRICE_MIN}, {PRICE_MAX}] range"
        )

    # Derive effective year-month from the wholesale record date
    date_str = wholesale.get("date", "")
    if date_str and len(date_str) >= 7:
        effective_ym = date_str[:7]  # "2026-03-01 00:00:00" -> "2026-03"
    else:
        effective_ym = datetime.now(timezone.utc).strftime("%Y-%m")

    return _build_output(
        price=consumer_estimate,
        source_id=f"ckan:orl-prices:{effective_ym}",
        effective_ym=effective_ym,
        raw={
            "adapter": "ckan_datastore",
            "wholesale_per_kl": wholesale["price_per_kl"],
            "wholesale_per_l": round(wholesale_per_l, 4),
            "excise_per_kl": excise["excise_per_kl"],
            "excise_per_l": round(excise_per_l, 4),
            "retail_margin_ils": RETAIL_MARGIN_ILS,
            "vat_rate": VAT_RATE,
            "consumer_formula": "(wholesale_l + excise_l + margin) * (1+VAT)",
            "wholesale_resource_id": wholesale["resource_id"],
            "excise_resource_id": excise["resource_id"],
            "wholesale_date": wholesale["date"],
            "excise_date": excise["date"],
        },
    )


# -- Adapter 2: Gov.il notice PDF (legacy fallback) --------------------------

def _extract_price_from_text(text: str) -> float:
    """Extract consumer self-service 95 price from Hebrew PDF notice text."""
    text = html.unescape(text).replace("\xa0", " ")
    shekel = r"(?:ש['\"״׳]?ח|₪)"
    patterns = [
        rf"לא\s*יעלה[^\d]{{0,10}}(?P<price>\d{{1,2}}(?:[\.,]\d{{1,3}})?)\s*{shekel}\s*לליטר",
        rf"(?P<price>\d{{1,2}}(?:[\.,]\d{{1,3}})?)\s*{shekel}\s*לליטר"
        rf"[^\n]{{0,160}}(?:שירות עצמי|כולל מע['\"״׳]?מ)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group("price").replace(",", "."))
            except Exception:
                continue
    raise RuntimeError("Gov.il notice parsing failed: price pattern not found")


def _pdf_text_from_bytes(pdf_bytes: bytes) -> str:
    from PyPDF2 import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _prev_month(year: int, month: int) -> Tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _fetch_from_pdf() -> dict:
    """Download Gov.il monthly notice PDF and parse consumer price."""
    now = datetime.now(timezone.utc)
    year_months = [(now.year, now.month), _prev_month(now.year, now.month)]
    last_error: Optional[str] = None

    for idx, (year, month) in enumerate(year_months):
        slug = NOTICE_MONTH_SLUGS.get(month)
        if not slug:
            continue
        url = NOTICE_PDF_TEMPLATE.format(month_slug=slug, year=year)
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                text = _pdf_text_from_bytes(r.content)
                price = _extract_price_from_text(text)
                if not (PRICE_MIN <= price <= PRICE_MAX):
                    raise RuntimeError(f"PDF price {price} outside sanity range")
                return _build_output(
                    price=price,
                    source_id=f"gov.il:fuel-notice:{year}-{month:02d}",
                    effective_ym=f"{year}-{month:02d}",
                    raw={
                        "adapter": "pdf_notice",
                        "notice_pdf_url": url,
                        "pattern": "consumer self-service 95 incl. VAT",
                    },
                )
            if r.status_code in {404, 500} and idx == 0:
                last_error = f"PDF HTTP {r.status_code} for {url}"
                continue
            raise RuntimeError(f"PDF HTTP {r.status_code} for {url}")
        except RuntimeError:
            raise
        except Exception as e:
            last_error = str(e)
            if idx == 0:
                continue
            raise RuntimeError(last_error) from e

    raise RuntimeError(last_error or "Gov.il notice PDF not found")


# -- Adapter 3: environment override -----------------------------------------

def _fetch_from_env() -> Optional[dict]:
    """Read consumer price from FUEL_PRICE_ILS env var (emergency override)."""
    env_val = os.getenv("FUEL_PRICE_ILS")
    if not env_val:
        return None
    try:
        val = float(env_val)
    except ValueError:
        logger.warning("FUEL_PRICE_ILS is not a valid float: %s", env_val)
        return None
    return _build_output(
        price=val,
        source_id="env:FUEL_PRICE_ILS",
        effective_ym=datetime.now(timezone.utc).strftime("%Y-%m"),
        raw={"adapter": "env_override", "env_var": "FUEL_PRICE_ILS"},
    )


# -- Public interface ---------------------------------------------------------

def fetch_current_fuel_price_ils_per_l(cache_ttl_s: int = 86400) -> dict:
    """Fetch consumer self-service gasoline 95 price (ILS/L) including VAT.

    Adapter chain:
      1. data.gov.il CKAN datastore (wholesale + excise -> formula)
      2. Gov.il monthly notice PDF (direct consumer price)
      3. FUEL_PRICE_ILS env var (emergency override)

    Returns stable dict: source_id, fetched_at_utc, effective_year_month,
    price_ils_per_l, raw.
    """
    # 0. Check cache first
    cached = cache_read(CACHE_KEY, max_age_s=cache_ttl_s)
    if cached:
        return cached

    errors: list[str] = []

    # 1. Primary: CKAN datastore
    try:
        result = _fetch_from_ckan()
        logger.info("Fuel price from CKAN: %.2f ILS/L", result["price_ils_per_l"])
        cache_write(CACHE_KEY, result)
        return result
    except Exception as e:
        errors.append(f"ckan: {e}")
        logger.warning("CKAN fuel adapter failed: %s", e)

    # 2. Secondary: PDF notice
    try:
        result = _fetch_from_pdf()
        logger.info("Fuel price from PDF: %.2f ILS/L", result["price_ils_per_l"])
        cache_write(CACHE_KEY, result)
        return result
    except Exception as e:
        errors.append(f"pdf: {e}")
        logger.warning("PDF fuel adapter failed: %s", e)

    # 3. Tertiary: env override
    env_result = _fetch_from_env()
    if env_result:
        logger.info("Fuel price from env: %.2f ILS/L", env_result["price_ils_per_l"])
        cache_write(CACHE_KEY, env_result)
        return env_result
    errors.append("env: FUEL_PRICE_ILS not set")

    # All adapters failed
    raise RuntimeError(
        "All fuel price adapters failed: " + "; ".join(errors)
    )


def get_cached_fuel_price(max_age_s: int = 7 * 86400) -> Optional[dict]:
    """Return last cached fuel price even if stale (for UI resilience)."""
    return cache_read(CACHE_KEY, max_age_s=max_age_s)
