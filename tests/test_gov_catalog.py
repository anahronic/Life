"""
Tests for sources/gov_catalog.py — CKAN client for data.gov.il.

Covers:
  - datastore_search happy path
  - fetch_latest_benzine95_wholesale parses records correctly
  - fetch_latest_benzine_excise parses records correctly
  - No matching product raises RuntimeError
  - validate_resource_schema success / failure
  - Resource IDs configurable via env
"""

import pytest
from unittest.mock import patch, MagicMock
from sources import gov_catalog


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_WHOLESALE_RECORD = {
    "_id": 144,
    "תאריך": "2026-03-01 00:00:00",
    "מוצר": "בנזין 95 אוקטן נטול עופרת במכלית",
    "יחידת מידה": 'ש"ח לאלף ליטר',
    "מחיר": 1683.87,
}

MOCK_WHOLESALE_PIPELINE = {
    "_id": 143,
    "תאריך": "2026-03-01 00:00:00",
    "מוצר": "בנזין 95 אוקטן נטול עופרת בהזרמה",
    "יחידת מידה": 'ש"ח לאלף ליטר',
    "מחיר": 1650.00,
}

MOCK_EXCISE_RECORD = {
    "_id": 1306,
    "תאריך": "2026-03-01 00:00:00",
    "מוצר": "בלו בנזין (סעיף 1 לתוספת לצו)",
    "יחידות": 'ש"ח לאלף ליטר',
    "מחיר": 3604.33,
}


def _mock_ckan_result(records, total=None):
    return {
        "records": records,
        "fields": [{"id": "_id"}, {"id": "תאריך"}, {"id": "מוצר"}, {"id": "מחיר"}],
        "total": total or len(records),
    }


# ---------------------------------------------------------------------------
# datastore_search
# ---------------------------------------------------------------------------

class TestDatastoreSearch:
    def test_happy_path(self):
        """datastore_search calls CKAN API and returns result."""
        result = _mock_ckan_result([MOCK_WHOLESALE_RECORD])

        with patch.object(gov_catalog, "_ckan_get", return_value=result) as m:
            out = gov_catalog.datastore_search("fake-resource-id", q="test")
            m.assert_called_once()
            assert out["records"] == [MOCK_WHOLESALE_RECORD]

    def test_filters_passed_as_json(self):
        """Filters dict is serialised to JSON param."""
        result = _mock_ckan_result([])

        with patch.object(gov_catalog, "_ckan_get", return_value=result) as m:
            gov_catalog.datastore_search(
                "rid", filters={"מוצר": "בנזין"}
            )
            call_params = m.call_args[0][1]
            assert "filters" in call_params


# ---------------------------------------------------------------------------
# fetch_latest_benzine95_wholesale
# ---------------------------------------------------------------------------

class TestBenzine95Wholesale:
    def test_returns_correct_fields(self):
        """Parses wholesale record into expected output schema."""
        result = _mock_ckan_result(
            [MOCK_WHOLESALE_RECORD, MOCK_WHOLESALE_PIPELINE]
        )

        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            out = gov_catalog.fetch_latest_benzine95_wholesale()

        assert out["price_per_kl"] == 1683.87
        assert out["date"] == "2026-03-01 00:00:00"
        assert out["product"] == "בנזין 95 אוקטן נטול עופרת במכלית"
        assert "resource_id" in out
        assert "raw_record" in out

    def test_filters_pipeline_records(self):
        """Only returns tanker records, not pipeline."""
        result = _mock_ckan_result(
            [MOCK_WHOLESALE_PIPELINE]  # Only pipeline, no tanker
        )

        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            with pytest.raises(RuntimeError, match="No matching benzine 95"):
                gov_catalog.fetch_latest_benzine95_wholesale()

    def test_no_records_raises(self):
        """Empty result raises RuntimeError."""
        result = _mock_ckan_result([])

        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            with pytest.raises(RuntimeError, match="No matching"):
                gov_catalog.fetch_latest_benzine95_wholesale()


# ---------------------------------------------------------------------------
# fetch_latest_benzine_excise
# ---------------------------------------------------------------------------

class TestBenzineExcise:
    def test_returns_correct_fields(self):
        """Parses excise record into expected output schema."""
        result = _mock_ckan_result([MOCK_EXCISE_RECORD])

        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            out = gov_catalog.fetch_latest_benzine_excise()

        assert out["excise_per_kl"] == 3604.33
        assert out["date"] == "2026-03-01 00:00:00"
        assert out["product"] == "בלו בנזין (סעיף 1 לתוספת לצו)"

    def test_no_records_raises(self):
        result = _mock_ckan_result([])

        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            with pytest.raises(RuntimeError, match="No matching"):
                gov_catalog.fetch_latest_benzine_excise()


# ---------------------------------------------------------------------------
# validate_resource_schema
# ---------------------------------------------------------------------------

class TestValidateSchema:
    def test_valid_schema(self):
        result = _mock_ckan_result([MOCK_WHOLESALE_RECORD])

        with patch.object(gov_catalog, "_ckan_get", return_value=result):
            ok = gov_catalog.validate_resource_schema(
                "rid", expected_fields=["_id", "תאריך", "מוצר", "מחיר"]
            )
        assert ok is True

    def test_missing_field(self):
        result = _mock_ckan_result([MOCK_WHOLESALE_RECORD])

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
        """Resource IDs can be overridden via env vars."""
        monkeypatch.setenv("CKAN_FUEL_ORL_PRICES_RESOURCE", "custom-uuid")

        # Re-import to pick up env change
        import importlib
        importlib.reload(gov_catalog)
        assert gov_catalog.FUEL_ORL_PRICES_RESOURCE == "custom-uuid"

        # Clean up: reload with default
        monkeypatch.delenv("CKAN_FUEL_ORL_PRICES_RESOURCE")
        importlib.reload(gov_catalog)


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
