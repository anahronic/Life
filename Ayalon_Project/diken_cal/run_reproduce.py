"""Run a reproducibility export: collects latest raw JSON from sources and writes CSVs.

Usage: set required env vars (TOMTOM_API_KEY optional), then run `python run_reproduce.py`.
"""
import os
import json
from sources import tomtom, sviva
from sources.fuel_govil import fetch_current_fuel_price_ils_per_l as fetch_current_fuel_price

OUTDIR = 'raw'
import pathlib
pathlib.Path(OUTDIR).mkdir(exist_ok=True)

def dump(name, obj):
    with open(f"{OUTDIR}/{name}.json", 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    api_key = os.getenv('TOMTOM_API_KEY')
    tom = tomtom.get_ayalon_segments(api_key, cache_ttl_s=0)
    sv = sviva.get_nearby_aq_for_ayalon(cache_ttl_s=0)
    fu = fetch_current_fuel_price()
    dump('tomtom', tom)
    dump('sviva', sv)
    dump('fuel', fu)
    print('Exported raw/*.json')
