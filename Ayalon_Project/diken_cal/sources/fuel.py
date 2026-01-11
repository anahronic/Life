import os
import re
import requests
import pandas as pd
from io import BytesIO
from datetime import datetime
from .cache import cache_read, cache_write

FUEL_PAGE = "https://www.gov.il/en/pages/fuel_prices_xls"


def extract_xls_links(html: str):
    # Find http(s) links ending with .xls or .xlsx
    pattern = r'https?://[^"\']+\.(?:xls|xlsx)'
    return list(set(re.findall(pattern, html, flags=re.I)))


def fetch_current_fuel_price_ils_per_l():
    cached = cache_read('fuel_price', max_age_s=24*3600)
    if cached:
        return cached
    # First, allow override via env var
    env_val = os.getenv('FUEL_PRICE_ILS')
    if env_val:
        try:
            val = float(env_val)
            out = {'price_ils_per_l': val, 'source': 'env:FUEL_PRICE_ILS', 'fetched_at': datetime.utcnow().isoformat() + 'Z'}
            cache_write('fuel_price', out)
            return out
        except:
            pass
    try:
        r = requests.get(FUEL_PAGE, timeout=20)
        r.raise_for_status()
        links = extract_xls_links(r.text)
        if not links:
            # can't find XLS; return None
            raise RuntimeError('No xls links found')
        xls_url = links[0]
        fx = requests.get(xls_url, timeout=30)
        fx.raise_for_status()
        df = pd.read_excel(BytesIO(fx.content))
        # Heuristic: search numeric values and take max as price (best-effort)
        nums = df.select_dtypes(include=['number']).values.flatten()
        if len(nums) == 0:
            raise RuntimeError('No numeric cells found in fuel xls')
        price = float(nums.max())
        out = {'price_ils_per_l': price, 'source': xls_url, 'fetched_at': datetime.utcnow().isoformat() + 'Z'}
        cache_write('fuel_price', out)
        return out
    except Exception as e:
        # fallback: require env var set by operator
        env_val2 = os.getenv('FUEL_PRICE_ILS')
        if env_val2:
            try:
                val = float(env_val2)
                out = {'price_ils_per_l': val, 'source': 'env:FUEL_PRICE_ILS', 'fetched_at': datetime.utcnow().isoformat() + 'Z'}
                cache_write('fuel_price', out)
                return out
            except:
                pass
        return {'error': str(e)}
