"""
Thin CKAN client for data.gov.il — Israel's official open-data portal.

Used at *development* time to discover datasets and at *runtime* to query
the datastore API for machine-readable fuel/transport data.

Production configuration pins known resource IDs (via env or constants)
so the catalogue is never hit on a live user request.
"""

import os
import logging
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
        import json
        params["filters"] = json.dumps(filters)
    return _ckan_get("datastore_search", params)


def get_latest_records(
    resource_id: str,
    product_query: str,
    limit: int = 2,
) -> List[Dict[str, Any]]:
    """Convenience: fetch latest records for a product text search."""
    result = datastore_search(resource_id, q=product_query, limit=limit)
    return result.get("records", [])


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

    Returns dict with keys: date, product, unit, price_per_kl, resource_id, raw_record.
    Raises RuntimeError on failure.
    """
    rid = resource_id or FUEL_ORL_PRICES_RESOURCE
    records = get_latest_records(rid, PRODUCT_BENZINE_95_TANKER, limit=2)
    # Filter for exact product match (q= is full-text, may return pipeline too)
    for rec in records:
        if rec.get("מוצר") == PRODUCT_BENZINE_95_TANKER:
            return {
                "date": rec.get("תאריך", ""),
                "product": rec.get("מוצר", ""),
                "unit": rec.get("יחידת מידה", ""),
                "price_per_kl": float(rec.get("מחיר", 0)),
                "resource_id": rid,
                "raw_record": rec,
            }
    raise RuntimeError(
        f"No matching benzine 95 tanker record in resource {rid}; "
        f"got {len(records)} records"
    )


def fetch_latest_benzine_excise(
    resource_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch latest excise rate for benzine in NIS/kiloliter.

    Returns dict with keys: date, product, unit, excise_per_kl, resource_id, raw_record.
    """
    rid = resource_id or FUEL_EXCISE_RESOURCE
    records = get_latest_records(rid, PRODUCT_EXCISE_BENZINE, limit=2)
    for rec in records:
        if rec.get("מוצר") == PRODUCT_EXCISE_BENZINE:
            return {
                "date": rec.get("תאריך", ""),
                "product": rec.get("מוצר", ""),
                "unit": rec.get("יחידות", ""),
                "excise_per_kl": float(rec.get("מחיר", 0)),
                "resource_id": rid,
                "raw_record": rec,
            }
    raise RuntimeError(
        f"No matching benzine excise record in resource {rid}; "
        f"got {len(records)} records"
    )


def validate_resource_schema(
    resource_id: str,
    expected_fields: List[str],
) -> bool:
    """Check that a datastore resource contains the expected field names."""
    result = datastore_search(resource_id, limit=0)
    actual = {f["id"] for f in result.get("fields", [])}
    missing = set(expected_fields) - actual
    if missing:
        logger.warning("Schema mismatch for %s: missing %s", resource_id, missing)
        return False
    return True
