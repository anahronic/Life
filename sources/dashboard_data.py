"""Read-only data preparation for the Streamlit dashboard (no Streamlit import).

All freshness decisions use the time a measurement refers to
(observed_at_utc).  Values older than health.TRAFFIC_FRESH_S are never
returned as "current".
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from methodology_v2 import (
    MAX_HOLD_S,
    economic_estimates,
    load_volume_profile,
    parse_ts,
    summarize_series,
    vehicle_hours,
)
from .health import TRAFFIC_FRESH_S, TRAFFIC_STALE_S
from .segment_matcher import ReferenceSegment

TZ_IL = ZoneInfo("Asia/Jerusalem")
DIRECTIONS = ("northbound", "southbound")


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def fmt_local(ts_or_iso) -> str:
    ts = parse_ts(ts_or_iso) if isinstance(ts_or_iso, str) else ts_or_iso
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(TZ_IL).strftime("%Y-%m-%d %H:%M")


def segment_state(refs: Sequence[ReferenceSegment], latest_any: Dict[str, Dict], latest_ok: Dict[str, Dict], now_ts: float) -> List[Dict[str, Any]]:
    """One row per reference segment with its freshness classification."""
    rows = []
    for r in refs:
        ok = latest_ok.get(r.segment_id)
        last = latest_any.get(r.segment_id)
        age = None
        fresh = "none"
        if ok:
            t = parse_ts(ok["observed_at_utc"])
            age = now_ts - t if t else None
            if age is not None and age <= TRAFFIC_FRESH_S:
                fresh = "current"
            elif age is not None and age <= TRAFFIC_STALE_S:
                fresh = "stale"
            else:
                fresh = "old"
        rows.append({
            "segment_id": r.segment_id,
            "direction": r.direction,
            "from": r.meta.get("from"),
            "to": r.meta.get("to"),
            "length_m": r.length_m,
            "freshness": fresh,
            "age_s": age,
            "last_status": last.get("status") if last else None,
            "observed_at_utc": ok.get("observed_at_utc") if ok else None,
            "travel_time_s": ok.get("travel_time_s") if ok else None,
            "freeflow_time_s": ok.get("freeflow_time_s") if ok else None,
            "delay_s": ok.get("delay_s") if ok else None,
            "speed_kmh": ok.get("speed_kmh") if ok else None,
            "freeflow_kmh": ok.get("freeflow_kmh") if ok else None,
            "coverage": ok.get("coverage") if ok else None,
            "provider": ok.get("provider") if ok else None,
        })
    return rows


def corridor_now(state_rows: List[Dict[str, Any]]) -> Dict[str, Optional[Dict[str, float]]]:
    """Per-direction corridor totals, only if EVERY section of that direction is current."""
    out: Dict[str, Optional[Dict[str, float]]] = {}
    for d in DIRECTIONS:
        rows = [r for r in state_rows if r["direction"] == d]
        if rows and all(r["freshness"] == "current" for r in rows):
            tt = sum(r["travel_time_s"] for r in rows)
            ff = sum(r["freeflow_time_s"] for r in rows)
            length = sum(r["length_m"] for r in rows)
            out[d] = {
                "length_m": length,
                "travel_time_s": tt,
                "freeflow_time_s": ff,
                "delay_s": max(0.0, tt - ff),
                "speed_kmh": length / tt * 3.6 if tt > 0 else None,
                "observed_at_utc": max(r["observed_at_utc"] for r in rows),
            }
        else:
            out[d] = None
    return out


def _with_ts(obs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for o in obs:
        o = dict(o)
        o["observed_at_ts"] = parse_ts(o["observed_at_utc"])
        out.append(o)
    return out


def corridor_series(obs: List[Dict[str, Any]], refs: Sequence[ReferenceSegment], direction: str) -> List[Dict[str, Any]]:
    """Corridor observations: snapshots where ALL sections of the direction are ok."""
    ids = {r.segment_id for r in refs if r.direction == direction}
    by_snap: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for o in obs:
        if o["segment_id"] in ids and o["status"] == "ok":
            by_snap[(o["provider"], o["observed_at_utc"])].append(o)
    series = []
    for (_prov, t), rows in by_snap.items():
        if {r["segment_id"] for r in rows} == ids:
            series.append({
                "observed_at_utc": t,
                "observed_at_ts": parse_ts(t),
                "travel_time_s": sum(r["travel_time_s"] for r in rows),
                "freeflow_time_s": sum(r["freeflow_time_s"] for r in rows),
            })
    return sorted(series, key=lambda r: r["observed_at_ts"])


def period_summary(obs: List[Dict[str, Any]], refs: Sequence[ReferenceSegment], window: Tuple[float, float],
                   fuel_price: Optional[float]) -> Dict[str, Any]:
    """Time-weighted statistics for a window; economic figures only with a documented volume profile."""
    obs = _with_ts(obs)
    by_seg: Dict[str, List[Dict]] = defaultdict(list)
    for o in obs:
        by_seg[o["segment_id"]].append(o)
    seg = {}
    for r in refs:
        s = summarize_series(by_seg.get(r.segment_id, []), window)
        seg[r.segment_id] = s
    corr = {d: summarize_series(corridor_series(obs, refs, d), window) for d in DIRECTIONS}
    profile = load_volume_profile()
    econ = None
    if profile is not None:
        vh = sum(vehicle_hours(by_seg.get(r.segment_id, []), window, profile) for r in refs)
        econ = economic_estimates(vh, fuel_price)
        econ["volume_source"] = profile.source
        econ["volume_citation"] = profile.citation
    return {"segments": seg, "corridor": corr, "economic": econ, "window": window, "max_hold_s": MAX_HOLD_S}


def daily_rows(obs: List[Dict[str, Any]], refs: Sequence[ReferenceSegment], start_ts: float, end_ts: float) -> List[Dict[str, Any]]:
    """One row per local (Asia/Jerusalem) day and direction."""
    obs = _with_ts(obs)
    rows = []
    day = datetime.fromtimestamp(start_ts, tz=timezone.utc).astimezone(TZ_IL).replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = datetime.fromtimestamp(end_ts, tz=timezone.utc).astimezone(TZ_IL)
    while day <= end_local:
        nxt = (day + timedelta(days=1, hours=2)).replace(hour=0)  # DST-safe next midnight
        w = (max(day.timestamp(), start_ts), min(nxt.timestamp(), end_ts))
        if w[1] > w[0]:
            for d in DIRECTIONS:
                s = summarize_series(corridor_series(obs, refs, d), w)
                rows.append({
                    "date": day.strftime("%Y-%m-%d"),
                    "direction": d,
                    "observed_h": round(s.observed_s / 3600, 2),
                    "coverage_pct": round(100 * s.coverage, 1),
                    "mean_delay_s": None if s.mean_delay_s is None else round(s.mean_delay_s, 1),
                    "max_delay_s": None if s.max_delay_s is None else round(s.max_delay_s, 1),
                    "mean_travel_time_s": None if s.mean_travel_time_s is None else round(s.mean_travel_time_s, 1),
                    "congested_h": round(s.congested_s / 3600, 2),
                })
        day = nxt
    return rows
