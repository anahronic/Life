"""
Tests for sources/fuel_govil.py — the 3-adapter fuel price chain.

Covers:
  - CKAN adapter returns correct consumer price given mocked wholesale + excise
  - PDF adapter fallback when CKAN fails
  - ENV override wins when FUEL_PRICE_ILS is set
  - Cache: fresh hit skips adapters
  - Cache: stale miss triggers chain
  - Sanity range rejection for CKAN and PDF
  - All-adapters-fail raises RuntimeError
  - get_cached_fuel_price stale read
"""

import pytest
from unittest.mock import patch
from sources import fuel_govil


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    """Disable on-disk cache for deterministic tests."""
    monkeypatch.setattr("sources.fuel_govil.cache_read", lambda *a, **k: None)
    monkeypatch.setattr("sources.fuel_govil.cache_write", lambda *a, **k: None)


@pytest.fixture
def mock_ckan_wholesale():
    """Return a factory for mocking fetch_latest_benzine95_wholesale."""
    return {
        "date": "2026-03-01 00:00:00",
        "product": "בנזין 95 אוקטן נטול עופרת במכלית",
        "unit": 'ש"ח לאלף ליטר',
        "price_per_kl": 1683.87,
        "resource_id": "aaa40832-ac82-4c86-bac6-0d05c83f576f",
        "raw_record": {"_id": 1},
    }


@pytest.fixture
def mock_ckan_excise():
    return {
        "date": "2026-03-01 00:00:00",
        "product": "בלו בנזין (סעיף 1 לתוספת לצו)",
        "unit": 'ש"ח לאלף ליטר',
        "excise_per_kl": 3604.33,
        "resource_id": "bdce45e7-9fe9-473e-bd51-cef1d787a951",
        "raw_record": {"_id": 1},
    }


# ---------------------------------------------------------------------------
# Adapter 1: CKAN datastore
# ---------------------------------------------------------------------------

class TestCkanAdapter:
    def test_correct_consumer_price(self, mock_ckan_wholesale, mock_ckan_excise):
        """CKAN adapter computes consumer price from wholesale + excise + margin."""
        with patch("sources.gov_catalog.fetch_latest_benzine95_wholesale",
                    return_value=mock_ckan_wholesale), \
             patch("sources.gov_catalog.fetch_latest_benzine_excise",
                    return_value=mock_ckan_excise):
            result = fuel_govil._fetch_from_ckan()

        assert result["price_ils_per_l"] == 7.02
        assert result["source_id"] == "ckan:orl-prices:2026-03"
        assert result["effective_year_month"] == "2026-03"
        assert result["raw"]["adapter"] == "ckan_datastore"
        assert result["raw"]["wholesale_per_kl"] == 1683.87
        assert result["raw"]["excise_per_kl"] == 3604.33

    def test_formula_components(self, mock_ckan_wholesale, mock_ckan_excise):
        """Verify the raw breakdown includes correct per-litre values."""
        with patch("sources.gov_catalog.fetch_latest_benzine95_wholesale",
                    return_value=mock_ckan_wholesale), \
             patch("sources.gov_catalog.fetch_latest_benzine_excise",
                    return_value=mock_ckan_excise):
            result = fuel_govil._fetch_from_ckan()

        raw = result["raw"]
        assert abs(raw["wholesale_per_l"] - 1.68387) < 0.0001
        assert abs(raw["excise_per_l"] - 3.60433) < 0.0001
        assert raw["retail_margin_ils"] == 0.66
        assert raw["vat_rate"] == 0.18

    def test_sanity_rejection_too_low(self, mock_ckan_wholesale, mock_ckan_excise):
        """CKAN adapter rejects impossibly low prices."""
        mock_ckan_wholesale["price_per_kl"] = 10.0
        mock_ckan_excise["excise_per_kl"] = 10.0

        with patch("sources.gov_catalog.fetch_latest_benzine95_wholesale",
                    return_value=mock_ckan_wholesale), \
             patch("sources.gov_catalog.fetch_latest_benzine_excise",
                    return_value=mock_ckan_excise):
            with pytest.raises(RuntimeError, match="outside"):
                fuel_govil._fetch_from_ckan()

    def test_sanity_rejection_too_high(self, mock_ckan_wholesale, mock_ckan_excise):
        """CKAN adapter rejects impossibly high prices."""
        mock_ckan_wholesale["price_per_kl"] = 8000.0
        mock_ckan_excise["excise_per_kl"] = 8000.0

        with patch("sources.gov_catalog.fetch_latest_benzine95_wholesale",
                    return_value=mock_ckan_wholesale), \
             patch("sources.gov_catalog.fetch_latest_benzine_excise",
                    return_value=mock_ckan_excise):
            with pytest.raises(RuntimeError, match="outside"):
                fuel_govil._fetch_from_ckan()


# ---------------------------------------------------------------------------
# Adapter 2: PDF notice (legacy fallback)
# ---------------------------------------------------------------------------

class TestPdfAdapter:
    def test_pdf_extracts_price(self, monkeypatch):
        """PDF adapter extracts consumer price from Hebrew notice text."""
        pdf_text = (
            'המחיר המרבי לליטר בנזין 95 אוקטן נטול עופרת '
            'לצרכן בתחנה בשירות עצמי (כולל מע"מ) '
            'לא יעלה על 6.85 ש"ח לליטר'
        )
        monkeypatch.setattr(fuel_govil, "_pdf_text_from_bytes", lambda data: pdf_text)

        class Resp:
            status_code = 200
            content = b"fake-pdf"

        monkeypatch.setattr("sources.fuel_govil.requests.get", lambda *a, **k: Resp())
        result = fuel_govil._fetch_from_pdf()

        assert result["price_ils_per_l"] == 6.85
        assert "gov.il:fuel-notice" in result["source_id"]
        assert result["raw"]["adapter"] == "pdf_notice"

    def test_pdf_fallback_on_ckan_failure(self, monkeypatch):
        """Full chain falls back to PDF when CKAN raises."""
        pdf_text = 'לא יעלה על 7.02 ש"ח לליטר'
        monkeypatch.setattr(fuel_govil, "_pdf_text_from_bytes", lambda data: pdf_text)

        class Resp:
            status_code = 200
            content = b"fake-pdf"

        monkeypatch.setattr("sources.fuel_govil.requests.get", lambda *a, **k: Resp())

        with patch("sources.gov_catalog.fetch_latest_benzine95_wholesale",
                    side_effect=RuntimeError("CKAN down")):
            result = fuel_govil.fetch_current_fuel_price_ils_per_l(cache_ttl_s=0)

        assert result["price_ils_per_l"] == 7.02
        assert "gov.il:fuel-notice" in result["source_id"]

    def test_pdf_sanity_rejection(self, monkeypatch):
        """PDF adapter rejects price outside sanity range."""
        pdf_text = 'לא יעלה על 1.23 ש"ח לליטר'
        monkeypatch.setattr(fuel_govil, "_pdf_text_from_bytes", lambda data: pdf_text)

        class Resp:
            status_code = 200
            content = b"fake-pdf"

        monkeypatch.setattr("sources.fuel_govil.requests.get", lambda *a, **k: Resp())

        with pytest.raises(RuntimeError, match="sanity"):
            fuel_govil._fetch_from_pdf()


# ---------------------------------------------------------------------------
# Adapter 3: env override
# ---------------------------------------------------------------------------

class TestEnvAdapter:
    def test_env_returns_price(self, monkeypatch):
        monkeypatch.setenv("FUEL_PRICE_ILS", "7.50")
        result = fuel_govil._fetch_from_env()

        assert result is not None
        assert result["price_ils_per_l"] == 7.50
        assert result["source_id"] == "env:FUEL_PRICE_ILS"
        assert result["raw"]["adapter"] == "env_override"

    def test_env_returns_none_when_unset(self):
        result = fuel_govil._fetch_from_env()
        assert result is None

    def test_env_invalid_float(self, monkeypatch):
        monkeypatch.setenv("FUEL_PRICE_ILS", "not-a-number")
        result = fuel_govil._fetch_from_env()
        assert result is None

    def test_env_fallback_in_chain(self, monkeypatch):
        """Full chain reaches env adapter when CKAN + PDF both fail."""
        monkeypatch.setenv("FUEL_PRICE_ILS", "6.99")

        with patch("sources.gov_catalog.fetch_latest_benzine95_wholesale",
                    side_effect=RuntimeError("CKAN down")):
            monkeypatch.setattr(
                "sources.fuel_govil.requests.get",
                lambda *a, **k: (_ for _ in ()).throw(ConnectionError("no net")),
            )
            result = fuel_govil.fetch_current_fuel_price_ils_per_l(cache_ttl_s=0)

        assert result["price_ils_per_l"] == 6.99
        assert result["source_id"] == "env:FUEL_PRICE_ILS"


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------

class TestCacheBehaviour:
    def test_cache_hit_skips_adapters(self, monkeypatch):
        """Fresh cache hit returns cached data without touching any adapter."""
        cached_data = {
            "source_id": "ckan:orl-prices:2026-03",
            "fetched_at_utc": "2026-03-15T10:00:00Z",
            "effective_year_month": "2026-03",
            "price_ils_per_l": 7.02,
            "raw": {"adapter": "ckan_datastore"},
        }
        monkeypatch.setattr("sources.fuel_govil.cache_read",
                            lambda *a, **k: cached_data)

        # Would fail if any adapter was called
        result = fuel_govil.fetch_current_fuel_price_ils_per_l(cache_ttl_s=300)
        assert result == cached_data

    def test_stale_cache_triggers_chain(self, monkeypatch, mock_ckan_wholesale,
                                        mock_ckan_excise):
        """Expired cache should trigger the adapter chain."""
        # autouse fixture already sets cache_read to None (miss)
        with patch("sources.gov_catalog.fetch_latest_benzine95_wholesale",
                    return_value=mock_ckan_wholesale), \
             patch("sources.gov_catalog.fetch_latest_benzine_excise",
                    return_value=mock_ckan_excise):
            result = fuel_govil.fetch_current_fuel_price_ils_per_l(cache_ttl_s=0)

        assert result["price_ils_per_l"] == 7.02

    def test_get_cached_fuel_price_stale(self, monkeypatch):
        """get_cached_fuel_price can read older data for UI resilience."""
        stale = {"source_id": "old", "price_ils_per_l": 6.50}
        monkeypatch.setattr("sources.fuel_govil.cache_read",
                            lambda key, max_age_s: stale)
        result = fuel_govil.get_cached_fuel_price(max_age_s=7 * 86400)
        assert result["price_ils_per_l"] == 6.50


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_all_adapters_fail_raises(self, monkeypatch):
        """RuntimeError when all three adapters fail."""
        with patch("sources.gov_catalog.fetch_latest_benzine95_wholesale",
                    side_effect=RuntimeError("CKAN down")):
            monkeypatch.setattr(
                "sources.fuel_govil.requests.get",
                lambda *a, **k: (_ for _ in ()).throw(ConnectionError("no net")),
            )
            # No FUEL_PRICE_ILS set either
            with pytest.raises(RuntimeError, match="All fuel price adapters failed"):
                fuel_govil.fetch_current_fuel_price_ils_per_l(cache_ttl_s=0)

    def test_build_output_schema(self):
        """Verify canonical output schema has all required keys."""
        out = fuel_govil._build_output(
            price=7.02,
            source_id="test:mock",
            effective_ym="2026-03",
            raw={"test": True},
        )
        assert set(out.keys()) == {
            "source_id", "fetched_at_utc", "effective_year_month",
            "price_ils_per_l", "raw",
        }
        assert out["price_ils_per_l"] == 7.02


# ---------------------------------------------------------------------------
# Live integration test (opt-in)
# ---------------------------------------------------------------------------

class TestLiveIntegration:
    def test_live_ckan(self):
        """Live CKAN test — only runs with ENABLE_FUEL_LIVE=1."""
        import os
        if os.getenv("ENABLE_FUEL_LIVE") != "1":
            pytest.skip("Set ENABLE_FUEL_LIVE=1 to run live fuel tests")

        result = fuel_govil.fetch_current_fuel_price_ils_per_l(cache_ttl_s=0)
        assert result["source_id"].startswith("ckan:")
        assert isinstance(result["price_ils_per_l"], float)
        assert 4.0 <= result["price_ils_per_l"] <= 12.0
