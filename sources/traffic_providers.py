"""Traffic flow providers for the v2 collector.

Each provider returns a ProviderResult with *flow pieces* (geometry + current
and free-flow speed) that segment_matcher maps onto the reference segments.

Only real-time measurements are accepted as pieces:
  * HERE Traffic API v7: confidence > 0.7 means real-time speeds
    (0.5-0.7 = historical profile, <=0.5 = speed limit; HERE docs "Flow").
  * TomTom Flow Segment Data v4: confidence >= TT_CONFIDENCE_MIN.
Pieces below the threshold are dropped, never substituted.

API keys are never logged: every URL recorded for provenance is built
without the key parameter, and error bodies are scrubbed of the key.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlencode

import requests

from .geo import LocalProjection, split_by_lengths
from .segment_matcher import FlowPiece, ReferenceSegment, match_segment, mps

HTTP_TIMEOUT_S = float(os.getenv("TRAFFIC_HTTP_TIMEOUT_S", "20"))
HTTP_RETRIES = int(os.getenv("TRAFFIC_HTTP_RETRIES", "1"))  # extra attempts on timeout/5xx only
HERE_MIN_CONFIDENCE = float(os.getenv("HERE_MIN_CONFIDENCE", "0.7"))
TT_CONFIDENCE_MIN = float(os.getenv("TT_CONFIDENCE_MIN", "0.7"))
TT_ZOOM = int(os.getenv("TT_ZOOM", "10"))

HERE_FLOW_URL = "https://data.traffic.hereapi.com/v7/flow"
TOMTOM_FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/{zoom}/json"

_PROJ = LocalProjection(32.07, 34.79)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class HttpAttempt:
    url: str  # never contains the API key
    status: Optional[int]
    elapsed_ms: int
    request_id: Optional[str]
    error: Optional[str] = None


@dataclass
class ProviderResult:
    provider: str
    status: str  # ok | no_coverage | auth_error | rate_limited | http_error | network_error | parse_error | not_configured
    fetched_at: Optional[str] = None
    source_updated: Optional[str] = None
    response_id: Optional[str] = None
    pieces: List[FlowPiece] = field(default_factory=list)
    dropped_low_confidence: int = 0
    attempts: List[HttpAttempt] = field(default_factory=list)
    raw_gz: Optional[bytes] = None
    raw_sha256: Optional[str] = None
    error: Optional[str] = None

    def summary(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "fetched_at": self.fetched_at,
            "source_updated": self.source_updated,
            "response_id": self.response_id,
            "pieces": len(self.pieces),
            "dropped_low_confidence": self.dropped_low_confidence,
            "http": [a.__dict__ for a in self.attempts],
            "error": self.error,
        }


def _scrub(text: str, secret: Optional[str]) -> str:
    if secret:
        text = text.replace(secret, "***")
    return text


def _get(url: str, params: Dict[str, str], secret_param: str, secret: str, attempts: List[HttpAttempt],
         headers: Optional[Dict[str, str]] = None) -> Optional[requests.Response]:
    """GET with bounded retries (timeouts, connection errors and 5xx only)."""
    safe_url = url + "?" + urlencode({k: v for k, v in params.items() if k != secret_param})
    full = dict(params)
    full[secret_param] = secret
    for attempt in range(HTTP_RETRIES + 1):
        req_id = str(uuid.uuid4())
        h = {"Accept": "application/json", "X-Request-Id": req_id}
        h.update(headers or {})
        t0 = time.monotonic()
        try:
            r = requests.get(url, params=full, headers=h, timeout=HTTP_TIMEOUT_S)
        except requests.RequestException as exc:
            attempts.append(HttpAttempt(safe_url, None, int((time.monotonic() - t0) * 1000), req_id,
                                        _scrub(f"{type(exc).__name__}: {exc}", secret)[:300]))
            if attempt < HTTP_RETRIES:
                time.sleep(3)
                continue
            return None
        rid = r.headers.get("Tracking-ID") or r.headers.get("X-Request-Id") or req_id
        err = None if r.status_code == 200 else _scrub(r.text, secret)[:300]
        attempts.append(HttpAttempt(safe_url, r.status_code, int((time.monotonic() - t0) * 1000), rid, err))
        if r.status_code >= 500 and attempt < HTTP_RETRIES:
            time.sleep(3)
            continue
        return r
    return None


def _classify_http(status: Optional[int], body: str) -> str:
    if status is None:
        return "network_error"
    if status in (401, 403):
        return "auth_error"
    if status == 429:
        return "rate_limited"
    if status == 400 and "too far from nearest existing segment" in body.lower():
        return "no_coverage"
    return "http_error"


def _pack_raw(obj: Any) -> tuple[bytes, str]:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return gzip.compress(raw, mtime=0), hashlib.sha256(raw).hexdigest()


# ── HERE Traffic API v7 ────────────────────────────────────────────────


def _corridor_bbox(refs: Sequence[ReferenceSegment], margin_deg: float = 0.003) -> str:
    lats = [p[0] for r in refs for p in r.geometry]
    lons = [p[1] for r in refs for p in r.geometry]
    return f"bbox:{min(lons) - margin_deg:.5f},{min(lats) - margin_deg:.5f},{max(lons) + margin_deg:.5f},{max(lats) + margin_deg:.5f}"


def parse_here_flow(js: Dict[str, Any], min_confidence: float = HERE_MIN_CONFIDENCE) -> tuple[List[FlowPiece], int]:
    """Convert a HERE v7 /flow JSON body into flow pieces (real-time only)."""
    pieces: List[FlowPiece] = []
    dropped = 0
    for n, res in enumerate(js.get("results") or []):
        loc = res.get("location") or {}
        cf = res.get("currentFlow") or {}
        pts = []
        fcs = []
        for link in (loc.get("shape") or {}).get("links") or []:
            lp = [(float(p["lat"]), float(p["lng"])) for p in link.get("points") or []]
            if not lp:
                continue
            fcs.append(link.get("functionalClass"))
            pts.extend(lp if not pts or pts[-1] != lp[0] else lp[1:])
        if len(pts) < 2:
            continue
        fc = min((f for f in fcs if f is not None), default=None)
        desc = str(loc.get("description") or "")
        subs = cf.get("subSegments") or []
        parts = []
        if subs and all(s.get("length") for s in subs):
            try:
                geoms = split_by_lengths(pts, [float(s["length"]) for s in subs], _PROJ)
                if len(geoms) == len(subs):
                    parts = list(zip(geoms, subs))
            except ValueError:
                parts = []
        if not parts:
            parts = [(pts, cf)]
        for k, (geom, flow) in enumerate(parts):
            conf = flow.get("confidence", cf.get("confidence"))
            conf = float(conf) if conf is not None else None
            if conf is None or conf <= min_confidence:
                dropped += 1
                continue
            speed = flow.get("speed")
            ff = flow.get("freeFlow")
            if speed is None or ff is None:
                dropped += 1
                continue
            trav = flow.get("traversability", cf.get("traversability"))
            pieces.append(FlowPiece(
                points=geom,
                speed_mps=float(speed),
                freeflow_mps=float(ff),
                piece_id=f"here:{n}.{k}:{desc[:40]}",
                confidence=conf,
                jam_factor=flow.get("jamFactor", cf.get("jamFactor")),
                closed=(trav == "closed"),
                functional_class=fc,
            ))
    return pieces, dropped


def fetch_here(api_key: Optional[str], refs: Sequence[ReferenceSegment]) -> ProviderResult:
    res = ProviderResult(provider="here_traffic_v7", status="not_configured")
    if not api_key:
        res.error = "HERE_API_KEY not configured"
        return res
    params = {
        "in": _corridor_bbox(refs),
        "locationReferencing": "shape",
        "functionalClasses": "1,2",
    }
    r = _get(HERE_FLOW_URL, params, "apiKey", api_key, res.attempts)
    res.fetched_at = utc_now_iso()
    if r is None:
        res.status = "network_error"
        res.error = res.attempts[-1].error if res.attempts else "no response"
        return res
    res.response_id = res.attempts[-1].request_id
    if r.status_code != 200:
        res.status = _classify_http(r.status_code, r.text)
        res.error = res.attempts[-1].error
        return res
    try:
        js = r.json()
        res.source_updated = js.get("sourceUpdated")
        res.pieces, res.dropped_low_confidence = parse_here_flow(js)
        res.raw_gz, res.raw_sha256 = _pack_raw(js)
    except (ValueError, KeyError, TypeError) as exc:
        res.status = "parse_error"
        res.error = f"{type(exc).__name__}: {exc}"[:300]
        return res
    res.status = "ok"
    return res


# ── TomTom Flow Segment Data v4 (legacy) ───────────────────────────────


def parse_tomtom_flow(js: Dict[str, Any], piece_id: str) -> Optional[FlowPiece]:
    f = js.get("flowSegmentData")
    if not isinstance(f, dict):
        raise ValueError("missing flowSegmentData")
    coords = f.get("coordinates", {}).get("coordinate") or []
    pts = [(float(c["latitude"]), float(c["longitude"])) for c in coords]
    conf = float(f.get("confidence", 0))
    if len(pts) < 2 or conf < TT_CONFIDENCE_MIN:
        return None
    closure = f.get("roadClosure")
    closed = closure is True or str(closure).lower() == "true"
    return FlowPiece(
        points=pts,
        speed_mps=mps(float(f["currentSpeed"])),
        freeflow_mps=mps(float(f["freeFlowSpeed"])),
        piece_id=piece_id,
        confidence=conf,
        closed=closed,
    )


def fetch_tomtom(api_key: Optional[str], refs: Sequence[ReferenceSegment]) -> ProviderResult:
    """Query segment midpoints; skip segments already covered by earlier pieces.

    Stops at the first 'no_coverage' answer: TomTom removed Israel from its
    Traffic API market coverage on 2026-09-15, so repeating the query for
    every segment would only burn quota.
    """
    res = ProviderResult(provider="tomtom_flow_v4", status="not_configured")
    if not api_key:
        res.error = "TOMTOM_API_KEY not configured"
        return res
    bodies = []
    url = TOMTOM_FLOW_URL.format(zoom=TT_ZOOM)
    for ref in refs:
        if res.pieces and match_segment(ref, res.pieces).coverage >= 0.99:
            continue
        lat, lon = ref.midpoint
        params = {"point": f"{lat:.6f},{lon:.6f}", "unit": "KMPH", "openLr": "false"}
        r = _get(url, params, "key", api_key, res.attempts)
        res.fetched_at = utc_now_iso()
        if r is None:
            res.status = "network_error"
            res.error = res.attempts[-1].error if res.attempts else "no response"
            break
        if r.status_code != 200:
            res.status = _classify_http(r.status_code, r.text)
            res.error = res.attempts[-1].error
            break
        try:
            js = r.json()
            piece = parse_tomtom_flow(js, piece_id=f"tomtom:{res.attempts[-1].request_id}")
        except (ValueError, KeyError, TypeError) as exc:
            res.status = "parse_error"
            res.error = f"{type(exc).__name__}: {exc}"[:300]
            break
        bodies.append(js)
        if piece is None:
            res.dropped_low_confidence += 1
        else:
            res.pieces.append(piece)
        res.status = "ok"
    if bodies:
        res.raw_gz, res.raw_sha256 = _pack_raw(bodies)
        res.response_id = ",".join(a.request_id or "" for a in res.attempts if a.status == 200)[:500]
    return res


PROVIDERS = {
    "here": ("HERE_API_KEY", fetch_here),
    "tomtom": ("TOMTOM_API_KEY", fetch_tomtom),
}


def configured_provider_order() -> List[str]:
    """Provider preference from TRAFFIC_PROVIDERS (comma list), default here,tomtom."""
    raw = os.getenv("TRAFFIC_PROVIDERS", "here,tomtom")
    return [p.strip().lower() for p in raw.split(",") if p.strip().lower() in PROVIDERS]
