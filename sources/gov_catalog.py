"""
Thin CKAN client for data.gov.il — Israel's official open-data portal.

Used at *development* time to discover datasets and at *runtime* to query
the datastore API for machine-readable fuel/transport data.

Production configuration pins known resource IDs (via env or constants)
so the catalogue is never hit on a live user request.

Primary record selection uses CKAN datastore **field filters** (not q=)
for deterministic exact-match queries.  Latest-month selection is done
explicitly by parsing dates and picking ``max(date)`` in Python.
"""

import json
import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ── API root ────────────────────────────────────────────────────────────
CKAN_BASE = os.getenv("DATA_GOV_IL_BASE", "https://data.gov.il")
CKAN_API = f"{CKAN_BASE}/api/3/action"
TIMEOUT_S = int(os.getenv("CKAN_TIMEOUT_S", "20"))

# ── Pinned resource IDs (production defaults) ───────────────────────────
# "orl-prices": calculated/regulated fuel prices (monthly, Ministry of Energy)
FUEL_ORL_PRICES_RESOURCE = os.getenv(
    "CKAN_FUEL_ORL_PRICES_RESOURCE",
    "aaa40832-ac82-4c86-bac6-0d05c83f576f",
)
# "excise": fuel excise tax rates (monthly, Ministry of Energy)
FUEL_EXCISE_RESOURCE = os.getenv(
    "CKAN_FUEL_EXCISE_RESOURCE",
    "bdce45e7-9fe9-473e-bd51-cef1d787a951",
)
# "orl": theoretical import prices (monthly, Ministry of Energy)
FUEL_ORL_THEORETICAL_RESOURCE = os.getenv(
    "CKAN_FUEL_ORL_THEORETICAL_RESOURCE",
    "157689c0-69fb-4923-8b27-c780ed64199d",
)

# ── Product names (Hebrew, as they appear in the datasets) ──────────────
PRODUCT_BENZINE_95_TANKER = "בנזין 95 אוקטן נטול עופרת במכלית"
PRODUCT_BENZINE_95_PIPELINE = "בנזין 95 אוקטן נטול עופרת בהזרמה"
PRODUCT_EXCISE_BENZINE = "בלו בנזין (סעיף 1 לתוספת לצו)"

# ── Expected schemas ────────────────────────────────────────────────────
WHOLESALE_EXPECTED_FIELDS = ["תאריך", "מוצר", "יחידת מידה", "מחיר"]
EXCISE_EXPECTED_FIELDS = ["תאריך", "מוצר", "יחידות", "מחיר"]

# ── Expected unit substrings (for unit validation) ──────────────────────
# The CKAN datasets use slightly varying unit text; we match substrings.
EXPECTED_UNIT_SUBSTR_KL = "ליטר"  # must appear in unit field for per-kl price


# ── Errors ──────────────────────────────────────────────────────────────

class CkanSchemaError(RuntimeError):
    """Raised when a CKAN resource schema does not match expectations."""
    pass


class CkanUnitError(RuntimeError):
    """Raised when a CKAN record has an unexpected measurement unit."""
    pass


# ── Low-level helpers ───────────────────────────────────────────────────

def _ckan_get(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Call a CKAN API action and return the ``result`` payload."""
    url = f"{CKAN_API}/{action}"
    r = requests.get(url, params=params, timeout=TIMEOUT_S)
    r.raise_for_status()
    body = r.json()
    if not body.get("success"):
        raise RuntimeError(f"CKAN API error: {body}")
    return body["result"]


# ── Datastore queries ───────────────────────────────────────────────────

def datastore_search(
    resource_id: str,
    *,
    q: Optional[str] = None,
    filters: Optional[Dict[str, str]] = None,
    sort: str = "_id desc",
    limit: int = 5,
    offset: int = 0,
) -> Dict[str, Any]:
    """Query the CKAN datastore for a given resource.

    Returns the full ``result`` dict with ``records``, ``fields``, ``total``.
    """
    params: Dict[str, Any] = {
        "resource_id": resource_id,
        "sort": sort,
        "limit": limit,
        "offset": offset,
    }
    if q:
        params["q"] = q
    if filters:
        params["filters"] = json.dumps(filters)
    return _ckan_get("datastore_search", params)


def get_latest_records(
    resource_id: str,
    product_query: str,
    limit: int = 2,
) -> List[Dict[str, Any]]:
    """Convenience: fetch latest records for a product text search.

    .. deprecated:: Use :func:`get_filtered_records` instead for deterministic queries.
    """
    result = datastore_search(resource_id, q=product_query, limit=limit)
    return result.get("records", [])


def get_filtered_records(
    resource_id: str,
    filters: Dict[str, str],
    limit: int = 6,
    sort: str = "_id desc",
) -> List[Dict[str, Any]]:
    """Fetch records using exact field filters (deterministic, no full-text)."""
    result = datastore_search(
        resource_id, filters=filters, limit=limit, sort=sort,
    )
    return result.get("records", [])


# ── Schema validation (used on the critical path) ──────────────────────

def validate_resource_schema(
    resource_id: str,
    expected_fields: List[str],
) -> bool:
    """Check that a datastore resource contains the expected field names.

    Returns True if all expected fields are present, False otherwise.
    """
    result = datastore_search(resource_id, limit=0)
    actual = {f["id"] for f in result.get("fields", [])}
    missing = set(expected_fields) - actual
    if missing:
        logger.warning("Schema mismatch for %s: missing %s", resource_id, missing)
        return False
    return True


def _check_schema(fields: List[Dict[str, Any]], expected: List[str], resource_id: str) -> None:
    """Raise :class:`CkanSchemaError` if *expected* fields are missing from *fields*."""
    actual = {f["id"] for f in fields}
    missing = set(expected) - actual
    if missing:
        raise CkanSchemaError(
            f"Schema mismatch for resource {resource_id}: "
            f"missing fields {sorted(missing)}; have {sorted(actual)}"
        )


def _check_unit(unit_value: str, field_name: str, resource_id: str) -> None:
    """Raise :class:`CkanUnitError` if *unit_value* doesn't contain expected substring."""
    if not unit_value or EXPECTED_UNIT_SUBSTR_KL not in unit_value:
        raise CkanUnitError(
            f"Unexpected unit in resource {resource_id}: "
            f"{field_name}={unit_value!r}; expected substring {EXPECTED_UNIT_SUBSTR_KL!r}"
        )


# ── Deterministic latest-date selection ─────────────────────────────────

def _parse_date(date_str: str) -> datetime:
    """Parse CKAN date string to datetime.  Handles 'YYYY-MM-DD HH:MM:SS' and 'YYYY-MM-DD'."""
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str!r}")


def _select_latest(records: List[Dict[str, Any]], date_field: str = "תאריך") -> Dict[str, Any]:
    """From a list of records pick the one with the latest date.

    Raises RuntimeError if no records or no parseable dates.
    """
    if not records:
        raise RuntimeError("No records to select from")

    best_rec = None
    best_dt: Optional[datetime] = None

    for rec in records:
        try:
            dt = _parse_date(str(rec.get(date_field, "")))
        except ValueError:
            logger.debug("Skipping record with unparseable date: %s", rec.get(date_field))
            continue
        if best_dt is None or dt > best_dt:
            best_dt = dt
            best_rec = rec

    if best_rec is None:
        raise RuntimeError(
            f"No records with parseable {date_field!r} field; "
            f"checked {len(records)} records"
        )
    return best_rec


# ── Discovery helpers (development-time) ────────────────────────────────

def package_search(query: str, rows: int = 10) -> Dict[str, Any]:
    """Search the data.gov.il catalogue for datasets matching *query*."""
    return _ckan_get("package_search", {"q": query, "rows": rows})


def find_fuel_datasets() -> List[Dict[str, Any]]:
    """Convenience: search for fuel-related datasets (Hebrew: דלק)."""
    result = package_search("דלק", rows=20)
    return result.get("results", [])


def resolve_resource_url(dataset_id: str, resource_id: str) -> str:
    """Build the direct download URL for a CKAN resource."""
    return f"{CKAN_BASE}/dataset/{dataset_id}/resource/{resource_id}/download"


# ── Benzine-95 specific queries ─────────────────────────────────────────

def fetch_latest_benzine95_wholesale(
    resource_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch latest calculated wholesale price for benzine 95 (tanker) in NIS/kiloliter.

    Selection strategy:
      1. Query with ``filters={"מוצר": "<exact product>"}`` (no q=)
      2. Validate schema (expected fields present in resource)
      3. Pick record with ``max(תאריך)`` explicitly in Python
      4. Validate unit field

    Returns dict with keys: date, product, unit, price_per_kl, resource_id, raw_record.
    Raises RuntimeError / CkanSchemaError / CkanUnitError on failure.
    """
    rid = resource_id or FUEL_ORL_PRICES_RESOURCE

    # Filtered query — deterministic, exact product match
    result = datastore_search(
        rid,
        filters={"מוצר": PRODUCT_BENZINE_95_TANKER},
        sort="_id desc",
        limit=6,
    )

    # Schema check on actual resource fields
    _check_schema(result.get("fields", []), WHOLESALE_EXPECTED_FIELDS, rid)

    records = result.get("records", [])
    if not records:
        raise RuntimeError(
            f"No records for benzine 95 tanker in resource {rid} "
            f"(filter returned 0 rows)"
        )

    # Deterministic latest date selection
    rec = _select_latest(records)

    # Unit validation
    unit_val = rec.get("יחידת מידה", "")
    _check_unit(unit_val, "יחידת מידה", rid)

    return {
        "date": rec.get("תאריך", ""),
        "product": rec.get("מוצר", ""),
        "unit": unit_val,
        "price_per_kl": float(rec.get("מחיר", 0)),
        "resource_id": rid,
        "raw_record": rec,
    }


def fetch_latest_benzine_excise(
    resource_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch latest excise rate for benzine in NIS/kiloliter.

    Same deterministic strategy as :func:`fetch_latest_benzine95_wholesale`:
    field filter → schema check → latest date → unit check.

    Returns dict with keys: date, product, unit, excise_per_kl, resource_id, raw_record.
    """
    rid = resource_id or FUEL_EXCISE_RESOURCE

    result = datastore_search(
        rid,
        filters={"מוצר": PRODUCT_EXCISE_BENZINE},
        sort="_id desc",
        limit=6,
    )

    _check_schema(result.get("fields", []), EXCISE_EXPECTED_FIELDS, rid)

    records = result.get("records", [])
    if not records:
        raise RuntimeError(
            f"No records for benzine excise in resource {rid} "
            f"(filter returned 0 rows)"
        )

    rec = _select_latest(records)

    unit_val = rec.get("יחידות", "")
    _check_unit(unit_val, "יחידות", rid)

    return {
        "date": rec.get("תאריך", ""),
        "product": rec.get("מוצר", ""),
        "unit": unit_val,
        "excise_per_kl": float(rec.get("מחיר", 0)),
        "resource_id": rid,
        "raw_record": rec,
    }
