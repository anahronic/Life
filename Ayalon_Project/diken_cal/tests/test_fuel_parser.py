import pytest
from sources import fuel_govil


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    """Disable on-disk cache for deterministic tests."""
    monkeypatch.setattr("sources.fuel_govil.cache_read", lambda *a, **k: None)
    monkeypatch.setattr("sources.fuel_govil.cache_write", lambda *a, **k: None)


class MockResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


def test_fuel_parser_with_valid_structure(monkeypatch):
    pdf_text = """
    המחיר המרבי לליטר בנזין 95 אוקטן נטול עופרת לצרכן בתחנה בשירות עצמי (כולל מע"מ) לא יעלה על 6.85 ש"ח לליטר
    """

    monkeypatch.setattr(
        fuel_govil,
        "_download_notice_pdf",
        lambda dt: ("http://example/pdf", b"pdf-bytes", 2026, 1),
    )
    monkeypatch.setattr(fuel_govil, "_pdf_text_from_bytes", lambda data: pdf_text)

    result = fuel_govil.fetch_current_fuel_price_ils_per_l(cache_ttl_s=0)

    assert result["price_ils_per_l"] == 6.85
    assert "gov.il:fuel-notice" in result["source_id"]


def test_fuel_parser_raises_on_structure_change(monkeypatch):
    broken_text = "מחיר לא יעלה על 1.23 ש""ח לליטר"  # below sanity guard and wrong

    monkeypatch.setattr(
        fuel_govil,
        "_download_notice_pdf",
        lambda dt: ("http://example/pdf", b"pdf-bytes", 2026, 1),
    )
    monkeypatch.setattr(fuel_govil, "_pdf_text_from_bytes", lambda data: broken_text)

    with pytest.raises(RuntimeError):
        fuel_govil.fetch_current_fuel_price_ils_per_l(cache_ttl_s=0)


def test_fuel_parser_live_optional():
    import os

    if os.getenv("ENABLE_FUEL_LIVE") != "1":
        pytest.skip("Set ENABLE_FUEL_LIVE=1 to run live fuel parser test")

    result = fuel_govil.fetch_current_fuel_price_ils_per_l(cache_ttl_s=0)
    assert result["source_id"].startswith("gov.il:fuel-notice")
    assert isinstance(result["price_ils_per_l"], float)
    assert 4.0 <= result["price_ils_per_l"] <= 12.0
