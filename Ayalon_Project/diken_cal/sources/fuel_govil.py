import os
import re
import html
import io
import requests
from datetime import datetime, timezone
from .cache import cache_read, cache_write
from PyPDF2 import PdfReader

# Official source: Gov.il monthly fuel notice PDF (consumer self-service price, incl. VAT)
# Example: https://www.gov.il/BlobFolder/news/fuel-january-2026/he/fuel-january-2026.pdf
NOTICE_PDF_TEMPLATE = "https://www.gov.il/BlobFolder/news/fuel-{month_slug}-{year}/he/fuel-{month_slug}-{year}.pdf"
NOTICE_MONTH_SLUGS = {
    1: "january",
    2: "february",
    3: "march",
    4: "april",
    5: "may",
    6: "june",
    7: "july",
    8: "august",
    9: "september",
    10: "october",
    11: "november",
    12: "december",
}

PRICE_MIN = 4.0
PRICE_MAX = 12.0


def _utc_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _extract_price_from_text(text: str) -> float:
    # Normalize whitespace
    text = html.unescape(text).replace('\xa0', ' ')
    # Allow both apostrophe and double-quote variants used as the shekel sign separator (ש"ח / ש'ח).
    shekel = r"(?:ש['\"״׳]?ח|₪)"
    patterns = [
        rf"לא\s*יעלה[^\d]{{0,10}}(?P<price>\d{{1,2}}(?:[\.,]\d{{1,3}})?)\s*{shekel}\s*לליטר",
        rf"(?P<price>\d{{1,2}}(?:[\.,]\d{{1,3}})?)\s*{shekel}\s*לליטר[^\n]{{0,160}}(?:שירות עצמי|כולל מע['\"״׳]?מ)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group("price").replace(',', '.'))
            except Exception:
                continue
    raise RuntimeError("Gov.il notice parsing failed: price pattern not found")


def _pdf_text_from_bytes(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or '' for page in reader.pages)


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _download_notice_pdf(dt: datetime) -> tuple[str, bytes, int, int]:
    year_months = [(dt.year, dt.month), _prev_month(dt.year, dt.month)]
    last_error = None

    for idx, (year, month) in enumerate(year_months):
        slug = NOTICE_MONTH_SLUGS.get(month)
        if not slug:
            raise RuntimeError("Month slug mapping missing")
        url = NOTICE_PDF_TEMPLATE.format(month_slug=slug, year=year)
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            return url, r.content, year, month

        # TODO: For v1.1 consider probing publication date and effective month instead of blind fallback.
        if r.status_code in {404, 500} and idx == 0:
            last_error = f"Gov.il notice PDF HTTP {r.status_code} for {url}"
            continue

        raise RuntimeError(f"Gov.il notice PDF HTTP {r.status_code} for {url}")

    raise RuntimeError(last_error or "Gov.il notice PDF not found for current or previous month")


def fetch_current_fuel_price_ils_per_l(cache_ttl_s: int = 86400) -> dict:
    """Fetch consumer self-service gasoline 95 price (ILS/L) from Gov.il notice (incl. VAT).

    Primary: Gov.il monthly notice page (fuel-<month>-<year>). Fail-closed if not parsable.
    Emergency only: FUEL_PRICE_ILS override.
    """
    cached = cache_read('fuel_govil', max_age_s=cache_ttl_s)
    if cached:
        return cached

    # Emergency override only (not default path)
    env_val = os.getenv('FUEL_PRICE_ILS')
    if env_val:
        try:
            val = float(env_val)
            out = {
                'source_id': 'env:FUEL_PRICE_ILS',
                'fetched_at_utc': _utc_iso(),
                'effective_year_month': datetime.now(timezone.utc).strftime('%Y-%m'),
                'price_ils_per_l': val,
                'raw': {'source': 'env'}
            }
            cache_write('fuel_govil', out)
            return out
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    pdf_url, pdf_bytes, target_year, target_month = _download_notice_pdf(now)
    text = _pdf_text_from_bytes(pdf_bytes)
    price_l = _extract_price_from_text(text)

    # Sanity guard against wrong unit/source
    if not (PRICE_MIN <= price_l <= PRICE_MAX):
        raise RuntimeError(f"Gov.il notice price out of expected range: {price_l}")

    out = {
        'source_id': f"gov.il:fuel-notice:{target_year}-{target_month:02d}",
        'fetched_at_utc': _utc_iso(),
        'effective_year_month': f"{target_year}-{target_month:02d}",
        'price_ils_per_l': price_l,
        'raw': {
            'notice_pdf_url': pdf_url,
            'pattern': 'consumer self-service 95 incl. VAT',
        }
    }
    cache_write('fuel_govil', out)
    return out
