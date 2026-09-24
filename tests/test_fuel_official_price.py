"""
Tests for sources/fuel_official_price.py — official consumer price adapter.

Covers:
  - PDF parsing extracts correct price from Hebrew text
  - Sanity range rejection
  - Month fallback (current → previous)
  - HTTP 404 retry logic
  - Output schema validation
"""

import pytest
from unittest.mock import patch
from sources import fuel_official_price


class TestOfficialPricePdfAdapter:
    def test_pdf_extracts_price(self, monkeypatch):
        """Extracts consumer price from Hebrew PDF notice text."""
        pdf_text = (
            'המחיר המרבי לליטר בנזין 95 אוקטן נטול עופרת '
            'לצרכן בתחנה בשירות עצמי (כולל מע"מ) '
            'לא יעלה על 7.02 ש"ח לליטר'
        )
        monkeypatch.setattr(fuel_official_price, "_pdf_text_from_bytes",
                            lambda data: pdf_text)

        class Resp:
            status_code = 200
            content = b"fake-pdf"

        monkeypatch.setattr("sources.fuel_official_price.requests.get",
                            lambda *a, **k: Resp())
        result = fuel_official_price.fetch_official_benzine95_self_service_price()

        assert result["price_ils_per_l"] == 7.02
        assert result["source_type"] == "gov_il_pdf"
        assert "gov.il:fuel-notice" in result["source_id"]
        assert result["raw"]["adapter"] == "official_price_pdf"
        assert "notice_pdf_url" in result["raw"]

    def test_pdf_sanity_rejection(self, monkeypatch):
        """Rejects price outside sanity range."""
        pdf_text = 'לא יעלה על 1.50 ש"ח לליטר'
        monkeypatch.setattr(fuel_official_price, "_pdf_text_from_bytes",
                            lambda data: pdf_text)

        class Resp:
            status_code = 200
            content = b"fake-pdf"

        monkeypatch.setattr("sources.fuel_official_price.requests.get",
                            lambda *a, **k: Resp())
        with pytest.raises(RuntimeError, match="sanity range"):
            fuel_official_price.fetch_official_benzine95_self_service_price()

    def test_output_schema(self, monkeypatch):
        """Output has all required fields."""
        pdf_text = 'לא יעלה על 6.85 ש"ח לליטר'
        monkeypatch.setattr(fuel_official_price, "_pdf_text_from_bytes",
                            lambda data: pdf_text)

        class Resp:
            status_code = 200
            content = b"fake-pdf"

        monkeypatch.setattr("sources.fuel_official_price.requests.get",
                            lambda *a, **k: Resp())
        result = fuel_official_price.fetch_official_benzine95_self_service_price()

        assert set(result.keys()) == {
            "source_id", "source_type", "fetched_at_utc",
            "effective_year_month", "price_ils_per_l", "raw",
        }
        assert isinstance(result["price_ils_per_l"], float)
        assert result["effective_year_month"]  # non-empty

    def test_http_404_retries_previous_month(self, monkeypatch):
        """HTTP 404 for current month retries previous month."""
        pdf_text = 'לא יעלה על 7.02 ש"ח לליטר'
        monkeypatch.setattr(fuel_official_price, "_pdf_text_from_bytes",
                            lambda data: pdf_text)

        call_count = 0

        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            class Resp404:
                status_code = 404
                content = b""

            class Resp200:
                status_code = 200
                content = b"fake-pdf"

            return Resp404() if call_count == 1 else Resp200()

        monkeypatch.setattr("sources.fuel_official_price.requests.get", mock_get)
        result = fuel_official_price.fetch_official_benzine95_self_service_price()

        assert result["price_ils_per_l"] == 7.02
        assert call_count == 2

    def test_all_months_fail_raises(self, monkeypatch):
        """RuntimeError when both months fail."""
        class Resp404:
            status_code = 404
            content = b""

        monkeypatch.setattr("sources.fuel_official_price.requests.get",
                            lambda *a, **k: Resp404())
        with pytest.raises(RuntimeError):
            fuel_official_price.fetch_official_benzine95_self_service_price()

    def test_price_extraction_comma_decimal(self):
        """Handles comma as decimal separator."""
        price = fuel_official_price._extract_price_from_text(
            'לא יעלה על 7,02 ש"ח לליטר'
        )
        assert price == 7.02
