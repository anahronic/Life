import os
import json
import time
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "_cache"
CACHE_DIR.mkdir(exist_ok=True)


def cache_write(name: str, data: dict):
    path = CACHE_DIR / f"{name}.json"
    payload = {'ts': time.time(), 'data': data}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f)


def cache_read(name: str, max_age_s: int = 300):
    path = CACHE_DIR / f"{name}.json"
    if not path.exists():
        return None
    with open(path, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    if time.time() - payload.get('ts', 0) > max_age_s:
        return None
    return payload['data']
