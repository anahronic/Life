"""
Tests for sources/gov_catalog.py — CKAN client for data.gov.il.

Covers:
  - datastore_search happy path
  - Wholesale selection uses filters (not q=)
  - Excise selection uses filters (not q=)
  - Deterministic latest-date selection from multiple monthly rows
  - Schema mismatch fails explicitly with CkanSchemaError
  - Wrong unit fails explicitly with CkanUnitError
  - No matching product raises RuntimeError
  - validate_resource_schema success / failure
  - Resource IDs configurable via env
  - Fallback chain still works if CKAN raises schema/unit errors
"""

import json
import pytest
from unittest.mock import patch, MagicMock, call
from sources import gov_catalog
from sources.gov_catalog import CkanSchemaError, CkanUnitError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

WHOLESALE_FIELDS = [
    {"id": "_id"}, {"id": "תאריך"}, {"id": "מוצר"},
    {"id": "יחידת מידה"}, {"id": "מחיר"},
]

EXCISE_FIELDS = [
    {"id": "_id"}, {"id": "תאריך"}, {"id": "מוצר"},
    {"id": "יחידות"}, {"id": "מחיר"},
]

MOCK_WHOLESALE_MAR = {
    "_id": 144,
    "תאריך": "2026-03-01 00:00:00",
    "מוצר": "בנזין 95 אוקטן נטול עופרת במכלית",
    "יחידת מידה": 'ש"ח לאלף ליטר',
    "מחיר": 1683.87,
}

MOCK_WHOLESALE_FEB = {
    "_id": 142,
    "תאריך": "2026-02-01 00:00:00",
    "מוצר": "בנזין 95 אוקטן נטול עופרת במכלית",
    "יחידת מידה": 'ש"ח לאלף ליטר',
    "מחיר": 1568.00,
}

MOCK_WHOLESALE_PIPELINE = {
    "_id": 143,
    "תאריך": "2026-03-01 00:00:00",
    "מוצר": "בנזין 95 אוקטן נטול עופרת בהזרמה",
    "יחידת מידה": 'ש"ח לאלף ליטר',
    "מחיר": 1650.00,
}

MOCK_EXCISE_MAR = {
    "_id": 1306,
    "תאריך": "2026-03-01 00:00:00",
    "מוצר": "בלו בנזין (סעיף 1 לתוספת לצו)",
    "יחידות": 'ש"ח לאלף ליטר',
    "מחיר": 3604.33,
}

MOCK_EXCISE_FEB = {
    "_id": 1300,
    "תאריך": "2026-02-01 00:00:00",
    "מוצר": "בלו בנזין (סעיף 1 לתוספת לצו)",
    "יחידות": 'ש"ח לאלף ליטר',
    "מחיר": 3604.33,
}


def _mock_ckan_result(records, fields=None, total=None):
    return {
        "records": records,
        "fields": fields or WHOLESALE_FIELDS,
        "total": total or len(records),
    }


# ---------------------------------------------------------------------------
# datastore_search low-level
# ---------------------------------------------------------------------------

class TestDatastoreSearch:
    def test_happy_path(self):
        result = _mock_ckan_result([MOCK_WHOLESALE_MAR])
        with patch.object(gov_catalog, "_ckan_get", return_value=result) as m:
            out = gov_catalog.datastore_search("fake-resource-id", q="test")
            m.assert_called_once()
            assert out["records"] == [MOCK_WHOLESALE_MAR]

    def test_filters_serialised_to_json(self):
        result = _mock_ckan_result([])
        with patch.object(gov_catalog, "_ckan_get", return_value=result) as m:
            gov_catalog.datastore_search("rid", filters={"מוצר": "בנזין"})
            call_params = m.call_args[0][1]
            assert "filters" in call_params
            parsed = json.loads(call_params["filters"])
            assert parsed == {"מוצר": "בנזין"}


# ---------------------------------------------------------------------------
# Wholesale: filters (not q=), deterministic date, schema, unit
# ---------------------------------------------------------------------------

class TestBenzine95Wholesale:
    def test_uses_filters_not_q(self):
        """Primary selection MUST use filters= param, never q=."""
        result = _mock_ckan_result([MOCK_WHOLESALE_MAR])
        with patch.object(gov_catalog, "_ckan_get", return_value=result) as m:
            gov_catalog.fetch_latest_benzine95_wholesale()
            params = m.call_args[0][1]
            assert "filters" in params, "wholesale query must use filters="
            assert "q" not in params, "wholesale query must NOT use q="
            filt = json.loads(params["filters"])
            assert filt["מוצר"] == gov_catalog.PRODUCT_BENZINE_95_TANKER

    def test_returns_correct_fields(self):
        result = _mock_ckan_result([MOCK_WHOLESALE_MAR])
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            out = gov_catalog.fetch_latest_benzine95_wholesale()
        assert out["price_per_kl"] == 1683.87
        assert out["date"] == "2026-03-01 00:00:00"
        assert out["product"] == "בנזין 95 אוקטן נטול עופרת במכלית"
        assert "resource_id" in out
        assert "raw_record" in out

    def test_deterministic_latest_date(self):
        """When multiple monthly rows returned, explicit max(date) wins."""
        # Return Feb first, Mar second — should still pick Mar
        result = _mock_ckan_result([MOCK_WHOLESALE_FEB, MOCK_WHOLESALE_MAR])
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            out = gov_catalog.fetch_latest_benzine95_wholesale()
        assert out["date"] == "2026-03-01 00:00:00"
        assert out["price_per_kl"] == 1683.87

    def test_no_records_raises(self):
        result = _mock_ckan_result([])
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            with pytest.raises(RuntimeError, match="No records"):
                gov_catalog.fetch_latest_benzine95_wholesale()

    def test_schema_mismatch_raises(self):
        """Missing expected field raises CkanSchemaError."""
        bad_fields = [{"id": "_id"}, {"id": "תאריך"}, {"id": "מוצר"}]  # no מחיר, no יחידת מידה
        result = _mock_ckan_result([MOCK_WHOLESALE_MAR], fields=bad_fields)
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            with pytest.raises(CkanSchemaError, match="missing fields"):
                gov_catalog.fetch_latest_benzine95_wholesale()

    def test_bad_unit_raises(self):
        """Unexpected unit value raises CkanUnitError."""
        bad_rec = {**MOCK_WHOLESALE_MAR, "יחידת מידה": "דולר לטון"}
        result = _mock_ckan_result([bad_rec])
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            with pytest.raises(CkanUnitError, match="Unexpected unit"):
                gov_catalog.fetch_latest_benzine95_wholesale()

    def test_empty_unit_raises(self):
        bad_rec = {**MOCK_WHOLESALE_MAR, "יחידת מידה": ""}
        result = _mock_ckan_result([bad_rec])
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            with pytest.raises(CkanUnitError):
                gov_catalog.fetch_latest_benzine95_wholesale()


# ---------------------------------------------------------------------------
# Excise: filters (not q=), deterministic date, schema, unit
# ---------------------------------------------------------------------------

class TestBenzineExcise:
    def test_uses_filters_not_q(self):
        """Primary selection MUST use filters= param, never q=."""
        result = _mock_ckan_result([MOCK_EXCISE_MAR], fields=EXCISE_FIELDS)
        with patch.object(gov_catalog, "_ckan_get", return_value=result) as m:
            gov_catalog.fetch_latest_benzine_excise()
            params = m.call_args[0][1]
            assert "filters" in params, "excise query must use filters="
            assert "q" not in params, "excise query must NOT use q="
            filt = json.loads(params["filters"])
            assert filt["מוצר"] == gov_catalog.PRODUCT_EXCISE_BENZINE

    def test_returns_correct_fields(self):
        result = _mock_ckan_result([MOCK_EXCISE_MAR], fields=EXCISE_FIELDS)
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            out = gov_catalog.fetch_latest_benzine_excise()
        assert out["excise_per_kl"] == 3604.33
        assert out["date"] == "2026-03-01 00:00:00"
        assert out["product"] == "בלו בנזין (סעיף 1 לתוספת לצו)"

    def test_deterministic_latest_date(self):
        """Explicit max(date) selection across multiple rows."""
        result = _mock_ckan_result(
            [MOCK_EXCISE_FEB, MOCK_EXCISE_MAR], fields=EXCISE_FIELDS,
        )
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            out = gov_catalog.fetch_latest_benzine_excise()
        assert out["date"] == "2026-03-01 00:00:00"

    def test_no_records_raises(self):
        result = _mock_ckan_result([], fields=EXCISE_FIELDS)
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            with pytest.raises(RuntimeError, match="No records"):
                gov_catalog.fetch_latest_benzine_excise()

    def test_schema_mismatch_raises(self):
        bad_fields = [{"id": "_id"}, {"id": "תאריך"}]  # missing מוצר, יחידות, מחיר
        result = _mock_ckan_result([MOCK_EXCISE_MAR], fields=bad_fields)
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            with pytest.raises(CkanSchemaError, match="missing fields"):
                gov_catalog.fetch_latest_benzine_excise()

    def test_bad_unit_raises(self):
        bad_rec = {**MOCK_EXCISE_MAR, "יחידות": "USD per barrel"}
        result = _mock_ckan_result([bad_rec], fields=EXCISE_FIELDS)
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            with pytest.raises(CkanUnitError, match="Unexpected unit"):
                gov_catalog.fetch_latest_benzine_excise()


# ---------------------------------------------------------------------------
# _select_latest helper
# ---------------------------------------------------------------------------

class TestSelectLatest:
    def test_picks_max_date(self):
        records = [
            {"תאריך": "2025-12-01 00:00:00", "v": "dec"},
            {"תאריך": "2026-03-01 00:00:00", "v": "mar"},
            {"תאריך": "2026-01-01 00:00:00", "v": "jan"},
        ]
        best = gov_catalog._select_latest(records)
        assert best["v"] == "mar"

    def test_empty_raises(self):
        with pytest.raises(RuntimeError, match="No records"):
            gov_catalog._select_latest([])

    def test_unparseable_dates_skipped(self):
        records = [
            {"תאריך": "not-a-date", "v": "bad"},
            {"תאריך": "2026-01-15 00:00:00", "v": "good"},
        ]
        best = gov_catalog._select_latest(records)
        assert best["v"] == "good"

    def test_all_unparseable_raises(self):
        records = [{"תאריך": "nope"}, {"תאריך": "also-nope"}]
        with pytest.raises(RuntimeError, match="No records with parseable"):
            gov_catalog._select_latest(records)


# ---------------------------------------------------------------------------
# _parse_date helper
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_standard_format(self):
        dt = gov_catalog._parse_date("2026-03-01 00:00:00")
        assert dt.year == 2026 and dt.month == 3 and dt.day == 1

    def test_iso_format(self):
        dt = gov_catalog._parse_date("2026-03-01T00:00:00")
        assert dt.month == 3

    def test_date_only(self):
        dt = gov_catalog._parse_date("2026-03-01")
        assert dt.day == 1

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            gov_catalog._parse_date("March 2026")


# ---------------------------------------------------------------------------
# validate_resource_schema (standalone)
# ---------------------------------------------------------------------------

class TestValidateSchema:
    def test_valid_schema(self):
        result = _mock_ckan_result([MOCK_WHOLESALE_MAR])
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            ok = gov_catalog.validate_resource_schema(
                "rid", expected_fields=["_id", "תאריך", "מוצר", "מחיר"]
            )
        assert ok is True

    def test_missing_field(self):
        result = _mock_ckan_result([MOCK_WHOLESALE_MAR])
        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            ok = gov_catalog.validate_resource_schema(
                "rid", expected_fields=["_id", "nonexistent_field"]
            )
        assert ok is False


# ---------------------------------------------------------------------------
# Env-configurable resource IDs
# ---------------------------------------------------------------------------

class TestEnvConfig:
    def test_custom_resource_id(self, monkeypatch):
        monkeypatch.setenv("CKAN_FUEL_ORL_PRICES_RESOURCE", "custom-uuid")
        import importlib
        importlib.reload(gov_catalog)
        assert gov_catalog.FUEL_ORL_PRICES_RESOURCE == "custom-uuid"
        monkeypatch.delenv("CKAN_FUEL_ORL_PRICES_RESOURCE")
        importlib.reload(gov_catalog)


# ---------------------------------------------------------------------------
# Fallback chain: schema/unit errors propagate to fuel_govil fallback
# ---------------------------------------------------------------------------

class TestFallbackPropagation:
    """CkanSchemaError and CkanUnitError are RuntimeError subclasses,
    so fuel_govil's except Exception handler catches them and proceeds
    to the PDF/env fallback chain."""

    def test_schema_error_is_runtime_error(self):
        assert issubclass(CkanSchemaError, RuntimeError)

    def test_unit_error_is_runtime_error(self):
        assert issubclass(CkanUnitError, RuntimeError)

    def test_ckan_schema_error_triggers_fallback(self, monkeypatch):
        """Schema error in CKAN adapter → fallback to PDF/env."""
        from sources import fuel_govil

        monkeypatch.setattr("sources.fuel_govil.cache_read", lambda *a, **k: None)
        monkeypatch.setattr("sources.fuel_govil.cache_write", lambda *a, **k: None)
        monkeypatch.setenv("FUEL_PRICE_ILS", "6.99")

        with patch("sources.gov_catalog.fetch_latest_benzine95_wholesale",
                    side_effect=CkanSchemaError("schema broke")):
            monkeypatch.setattr(
                "sources.fuel_govil.requests.get",
                lambda *a, **k: (_ for _ in ()).throw(ConnectionError("no net")),
            )
            result = fuel_govil.fetch_current_fuel_price_ils_per_l(cache_ttl_s=0)

        assert result["source_id"] == "env:FUEL_PRICE_ILS"
        assert result["price_ils_per_l"] == 6.99


# ---------------------------------------------------------------------------
# Live integration (opt-in)
# ---------------------------------------------------------------------------

class TestLiveIntegration:
    def test_live_wholesale(self):
        import os
        if os.getenv("ENABLE_FUEL_LIVE") != "1":
            pytest.skip("Set ENABLE_FUEL_LIVE=1")
        out = gov_catalog.fetch_latest_benzine95_wholesale()
        assert out["price_per_kl"] > 0
        assert len(out["date"]) >= 7

    def test_live_excise(self):
        import os
        if os.getenv("ENABLE_FUEL_LIVE") != "1":
            pytest.skip("Set ENABLE_FUEL_LIVE=1")
        out = gov_catalog.fetch_latest_benzine_excise()
        assert out["excise_per_kl"] > 0
