"""Ayalon measurement methodology v2.

Replaces v1 (methodology.py, "1.0-freeze"), whose defects are documented in
docs/ayalon_v2_methodology.md:
  * v1 compared a provider travel time for a 9-18 km provider segment with
    the free-flow time of a 0.4-1.1 km polyline window (~858 vehicle-hours
    of "delay" at perfectly free flow);
  * v1 used vehicles = speed x 25 veh/km (not a measurement);
  * the UI summed per-run snapshots, so totals scaled with the number of runs.

v2 definitions (all per reference segment s, see reference/ayalon_segments_v2.json):

  T_obs(s,t)  [s]      travel time over the segment, from real-time speeds
  T_ff(s,t)   [s]      free-flow travel time over the SAME covered stretch
  d(s,t)      [s/veh]  = max(0, T_obs - T_ff)      delay per vehicle

Accumulation over time uses a step-hold integral: an observation at t_k is
valid until the next observation of the same segment, but never longer than
MAX_HOLD_S.  Time without a valid observation is reported as a coverage gap
and contributes nothing (it is NOT interpolated).  Totals therefore depend
on elapsed time and measured conditions, not on how often the API was called.

Vehicle-hours need a traffic volume q(s,t) [veh/h], which no connected source
provides in real time.  Economic indicators are computed ONLY when a
documented volume profile is configured (reference/volume_profile.json);
otherwise they are reported as unavailable.

  VH  [veh*h]  = sum_s  integral d(s,t)/3600 * q(s,t) dt[h]
  fuel [L]     = VH * Fuel_idle_rate_L_per_h * StopGo_factor      (model estimate)
  CO2  [kg]    = fuel * CO2_per_liter_kg
  cost [ILS]   = fuel * P_fuel
  time [ILS]   = VH * Value_of_Time_ILS_per_h
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

METHODOLOGY_VERSION = "2.0"
MAX_HOLD_S = 600.0  # 2 x the 5-minute collection cadence
CONGESTED_DELAY_RATIO = 0.25  # d / T_ff above this counts as "congested" time

_ROOT = Path(__file__).resolve().parent
_LOCKED = json.loads((_ROOT / "LOCKED_CONSTANTS.json").read_text(encoding="utf-8"))
VOLUME_PROFILE_FILE = _ROOT / "reference" / "volume_profile.json"


@dataclass(frozen=True)
class Constants:
    fuel_idle_rate_l_per_h: float = float(_LOCKED["fuel_constants"]["Fuel_idle_rate_L_per_h"])
    stop_go_factor: float = float(_LOCKED["fuel_constants"]["StopGo_factor"])
    co2_kg_per_l: float = float(_LOCKED["fuel_constants"]["CO2_per_liter_kg"])
    value_of_time_ils_per_h: float = float(_LOCKED["economic_constants"]["Value_of_Time_ILS_per_h"])


CONSTANTS = Constants()


def parse_ts(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def delay_per_vehicle_s(travel_time_s: Optional[float], freeflow_time_s: Optional[float]) -> Optional[float]:
    """Congestion delay per vehicle; None when either input is missing."""
    if travel_time_s is None or freeflow_time_s is None:
        return None
    return max(0.0, float(travel_time_s) - float(freeflow_time_s))


def step_hold_intervals(times: Sequence[float], window: Tuple[float, float], max_hold_s: float = MAX_HOLD_S) -> List[Tuple[int, float, float]]:
    """Validity interval of each observation inside the window.

    Returns (index, start, end) for observations sorted by time; an
    observation holds until the next one or max_hold_s, whichever is first.
    """
    w0, w1 = window
    out = []
    for i, t in enumerate(times):
        end = t + max_hold_s
        if i + 1 < len(times):
            end = min(end, times[i + 1])
        a, b = max(t, w0), min(end, w1)
        if b > a:
            out.append((i, a, b))
    return out


@dataclass
class SeriesSummary:
    observed_s: float
    window_s: float
    mean_delay_s: Optional[float]
    max_delay_s: Optional[float]
    mean_travel_time_s: Optional[float]
    mean_freeflow_time_s: Optional[float]
    congested_s: float
    n_observations: int

    @property
    def coverage(self) -> float:
        return self.observed_s / self.window_s if self.window_s > 0 else 0.0


def summarize_series(rows: Iterable[Dict], window: Tuple[float, float], max_hold_s: float = MAX_HOLD_S) -> SeriesSummary:
    """Time-weighted summary of one segment's (or corridor's) observations.

    rows: dicts with observed_at_ts, travel_time_s, freeflow_time_s.
    """
    pts = sorted(
        (r for r in rows if r.get("observed_at_ts") is not None and r.get("travel_time_s") is not None and r.get("freeflow_time_s") is not None),
        key=lambda r: r["observed_at_ts"],
    )
    times = [float(r["observed_at_ts"]) for r in pts]
    iv = step_hold_intervals(times, window, max_hold_s)
    obs = sum(b - a for _i, a, b in iv)
    w = window[1] - window[0]
    if obs <= 0:
        return SeriesSummary(0.0, w, None, None, None, None, 0.0, 0)
    sd = st = sf = cong = 0.0
    mx = 0.0
    for i, a, b in iv:
        r = pts[i]
        d = delay_per_vehicle_s(r["travel_time_s"], r["freeflow_time_s"])
        sd += d * (b - a)
        st += float(r["travel_time_s"]) * (b - a)
        sf += float(r["freeflow_time_s"]) * (b - a)
        mx = max(mx, d)
        if float(r["freeflow_time_s"]) > 0 and d / float(r["freeflow_time_s"]) > CONGESTED_DELAY_RATIO:
            cong += b - a
    return SeriesSummary(obs, w, sd / obs, mx, st / obs, sf / obs, cong, len({i for i, _a, _b in iv}))


# ── Volume profile (optional, must be documented) ──────────────────────


@dataclass
class VolumeProfile:
    source: str
    citation: str
    weekday_vph: List[float]  # 24 hourly values, per direction, local time (Asia/Jerusalem)
    weekend_vph: List[float]
    weekend_days: Tuple[int, ...] = (4, 5)  # Friday, Saturday (Python weekday numbers)

    def vph(self, ts: float) -> float:
        from zoneinfo import ZoneInfo

        lt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ZoneInfo("Asia/Jerusalem"))
        prof = self.weekend_vph if lt.weekday() in self.weekend_days else self.weekday_vph
        return float(prof[lt.hour])


def load_volume_profile(path: Path = VOLUME_PROFILE_FILE) -> Optional[VolumeProfile]:
    """Return the configured volume profile, or None if not documented."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    try:
        wd = [float(x) for x in d["weekday_vph"]]
        we = [float(x) for x in d["weekend_vph"]]
        if len(wd) != 24 or len(we) != 24 or not d.get("source") or not d.get("citation"):
            return None
        return VolumeProfile(d["source"], d["citation"], wd, we, tuple(d.get("weekend_days", (4, 5))))
    except (KeyError, TypeError, ValueError):
        return None


def vehicle_hours(rows: Iterable[Dict], window: Tuple[float, float], profile: VolumeProfile, max_hold_s: float = MAX_HOLD_S, step_s: float = 300.0) -> float:
    """Integral of delay x volume over the window for one segment [veh*h]."""
    pts = sorted(
        (r for r in rows if r.get("observed_at_ts") is not None and r.get("travel_time_s") is not None and r.get("freeflow_time_s") is not None),
        key=lambda r: r["observed_at_ts"],
    )
    total = 0.0
    for i, a, b in step_hold_intervals([float(r["observed_at_ts"]) for r in pts], window, max_hold_s):
        d_h = delay_per_vehicle_s(pts[i]["travel_time_s"], pts[i]["freeflow_time_s"]) / 3600.0
        t = a
        while t < b:  # sub-step so the hourly volume profile is respected
            u = min(b, t + step_s)
            total += d_h * profile.vph((t + u) / 2) * (u - t) / 3600.0
            t = u
    return total


def economic_estimates(vh: float, fuel_price_ils_per_l: Optional[float], c: Constants = CONSTANTS) -> Dict[str, Optional[float]]:
    fuel_l = vh * c.fuel_idle_rate_l_per_h * c.stop_go_factor
    return {
        "vehicle_hours": vh,
        "fuel_excess_l": fuel_l,
        "co2_kg": fuel_l * c.co2_kg_per_l,
        "fuel_cost_ils": fuel_l * fuel_price_ils_per_l if fuel_price_ils_per_l else None,
        "time_value_ils": vh * c.value_of_time_ils_per_h,
    }
