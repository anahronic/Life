"""
Official consumer fuel price source — Gov.il monthly notice (PDF).

Fetches the official maximum consumer self-service benzine 95 price (ILS/L,
including VAT) from the Energy Ministry's monthly PDF notices published on
gov.il.

This is used by the derived-margin path in ``fuel_govil.py`` to compute
the retail margin as:

    margin = (official_price / (1 + VAT)) - wholesale_per_l - excise_per_l

The module tries the current month first, then the previous month (notices
are sometimes published with a short delay).

Output schema::

    {
        "source_id":            "gov.il:fuel-notice:YYYY-MM",
        "source_type":          "gov_il_pdf",
        "fetched_at_utc":       "...",
        "effective_year_month":  "YYYY-MM",
        "price_ils_per_l":      float,
        "raw": {
            "adapter":          "official_price_pdf",
            "notice_pdf_url":   "...",
            "extracted_text_snippet": "...",
        },
    }
"""

import html
import io
import logging
import re
from datetime import datetime, timezone
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# -- Constants ---------------------------------------------------------------

PRICE_MIN = 4.0   # ILS/L -- sanity floor
PRICE_MAX = 12.0  # ILS/L -- sanity ceiling

NOTICE_PDF_TEMPLATE = (
    "https://www.gov.il/BlobFolder/news/fuel-{month_slug}-{year}"
    "/he/fuel-{month_slug}-{year}.pdf"
)
NOTICE_MONTH_SLUGS = {
    1: "january", 2: "february", 3: "march", 4: "april",
    5: "may", 6: "june", 7: "july", 8: "august",
    9: "september", 10: "october", 11: "november", 12: "december",
}


# -- Internal helpers --------------------------------------------------------

def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _prev_month(year: int, month: int) -> Tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _pdf_text_from_bytes(pdf_bytes: bytes) -> str:
    from PyPDF2 import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_price_from_text(text: str) -> float:
    """Extract consumer self-service 95 price from Hebrew PDF notice text.

    Returns the price in ILS/L (including VAT).
    """
    text = html.unescape(text).replace("\xa0", " ")
    shekel = r"(?:ש['\"״׳]?ח|₪)"
    patterns = [
        # "לא יעלה על X.XX ש"ח לליטר"
        rf"לא\s*יעלה[^\d]{{0,10}}(?P<price>\d{{1,2}}(?:[\.,]\d{{1,3}})?)\s*{shekel}\s*לליטר",
        # "X.XX ש"ח לליטר ... שירות עצמי / כולל מע"מ"
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
    raise RuntimeError("Official price PDF parsing failed: price pattern not found")


# -- Public interface --------------------------------------------------------

def fetch_official_benzine95_self_service_price() -> dict:
    """Fetch official consumer self-service benzine 95 price from gov.il PDF.

    Tries current month, then previous month.

    Returns:
        dict with keys: source_id, source_type, fetched_at_utc,
        effective_year_month, price_ils_per_l, raw.

    Raises:
        RuntimeError if the PDF cannot be fetched or parsed.
    """
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
                    raise RuntimeError(
                        f"Official price {price} outside sanity range "
                        f"[{PRICE_MIN}, {PRICE_MAX}]"
                    )
                snippet = text[:300].replace("\n", " ").strip()
                return {
                    "source_id": f"gov.il:fuel-notice:{year}-{month:02d}",
                    "source_type": "gov_il_pdf",
                    "fetched_at_utc": _utc_iso(),
                    "effective_year_month": f"{year}-{month:02d}",
                    "price_ils_per_l": round(price, 2),
                    "raw": {
                        "adapter": "official_price_pdf",
                        "notice_pdf_url": url,
                        "extracted_text_snippet": snippet,
                    },
                }
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

    raise RuntimeError(last_error or "Official price PDF not found for any month")
