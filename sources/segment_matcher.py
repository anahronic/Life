"""Match provider flow geometry onto the v2 reference segments.

A provider (HERE, TomTom, ...) delivers *flow pieces*: a polyline with one
current speed and one free-flow speed.  A reference segment is a fixed,
versioned stretch of one Ayalon carriageway (reference/ayalon_segments_v2.json).

Each reference segment is split into bins of BIN_M metres.  A bin is covered
by a piece only if the piece passes within MAX_OFFSET_M of the bin centre AND
runs in the same direction (heading within MAX_HEADING_DIFF_DEG).  This
rejects the opposite carriageway, ramps crossing at an angle and unrelated
roads, which is exactly what the v1 probe-point design failed to do.

Travel time and free-flow time are integrated bin by bin over the SAME
covered bins, so both refer to the same physical stretch:

    T_obs = sum(len_i / v_i)          T_ff = sum(len_i / v_ff_i)

and extrapolated to the full segment length only when coverage is at least
MIN_COVERAGE (otherwise the segment is reported as insufficient_coverage and
no values are produced).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .geo import (
    LatLon,
    LocalProjection,
    ProjectedPolyline,
    angle_diff_deg,
    bbox_expand,
    bbox_intersects,
)

REFERENCE_FILE = Path(__file__).resolve().parent.parent / "reference" / "ayalon_segments_v2.json"

BIN_M = 10.0
MAX_OFFSET_M = 20.0
MAX_HEADING_DIFF_DEG = 35.0
MIN_COVERAGE = 0.8
MIN_SPEED_MPS = 0.5  # below this a speed is treated as unusable, not as "infinite delay"

_PROJ = LocalProjection(32.07, 34.79)


@dataclass
class FlowPiece:
    """One homogeneous piece of provider flow data."""

    points: List[LatLon]
    speed_mps: float
    freeflow_mps: float
    piece_id: str
    confidence: Optional[float] = None
    jam_factor: Optional[float] = None
    closed: bool = False
    functional_class: Optional[int] = None

    def __post_init__(self):
        self._line: Optional[ProjectedPolyline] = None

    @property
    def line(self) -> ProjectedPolyline:
        if self._line is None:
            self._line = ProjectedPolyline(self.points, _PROJ)
        return self._line


@dataclass
class ReferenceSegment:
    segment_id: str
    segment_version: int
    direction: str
    length_m: float
    geometry: List[LatLon]
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.line = ProjectedPolyline(self.geometry, _PROJ)
        n = max(1, int(round(self.line.length / BIN_M)))
        self.bin_len = self.line.length / n
        self.bins = []  # (xy, heading)
        for k in range(n):
            xy, i = self.line.point_at((k + 0.5) * self.bin_len)
            self.bins.append((xy, self.line.heading_at_segment(i)))

    @property
    def midpoint(self) -> LatLon:
        xy, _ = self.line.point_at(self.line.length / 2)
        return _PROJ.to_ll(xy)


@dataclass
class SegmentMatch:
    segment_id: str
    segment_version: int
    status: str  # ok | insufficient_coverage | closed | no_data
    coverage: float
    length_m: float
    travel_time_s: Optional[float] = None
    freeflow_time_s: Optional[float] = None
    speed_kmh: Optional[float] = None
    freeflow_kmh: Optional[float] = None
    confidence: Optional[float] = None
    jam_factor: Optional[float] = None
    mean_offset_m: Optional[float] = None
    max_offset_m: Optional[float] = None
    piece_ids: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def load_reference_segments(path: Path = REFERENCE_FILE) -> List[ReferenceSegment]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for s in data["segments"]:
        out.append(ReferenceSegment(
            segment_id=s["segment_id"],
            segment_version=int(s["segment_version"]),
            direction=s["direction"],
            length_m=float(s["length_m"]),
            geometry=[(float(p[0]), float(p[1])) for p in s["geometry"]],
            meta={k: s[k] for k in ("road", "carriageway", "from", "to", "start", "end", "mean_bearing_deg") if k in s},
        ))
    return out


def match_segment(ref: ReferenceSegment, pieces: Sequence[FlowPiece]) -> SegmentMatch:
    box = bbox_expand(ref.line.bbox, MAX_OFFSET_M + 5)
    cands = [p for p in pieces if len(p.points) >= 2 and bbox_intersects(p.line.bbox, box)]

    assigned = []  # (piece, offset)
    for xy, heading in ref.bins:
        best = None
        for p in cands:
            if not (p.line.bbox[0] - MAX_OFFSET_M <= xy[0] <= p.line.bbox[2] + MAX_OFFSET_M
                    and p.line.bbox[1] - MAX_OFFSET_M <= xy[1] <= p.line.bbox[3] + MAX_OFFSET_M):
                continue
            d, _c, i = p.line.nearest(xy)
            if d > MAX_OFFSET_M:
                continue
            if angle_diff_deg(p.line.heading_at_segment(i), heading) > MAX_HEADING_DIFF_DEG:
                continue
            if best is None or d < best[1]:
                best = (p, d)
        assigned.append(best)

    covered = [a for a in assigned if a is not None]
    n = len(assigned)
    coverage = len(covered) / n if n else 0.0
    m = SegmentMatch(ref.segment_id, ref.segment_version, "no_data", round(coverage, 4), round(ref.line.length, 1))
    if not covered:
        return m

    used = []
    for p, _d in covered:
        if p.piece_id not in used:
            used.append(p.piece_id)
    m.piece_ids = used
    offsets = [d for _p, d in covered]
    m.mean_offset_m = round(sum(offsets) / len(offsets), 2)
    m.max_offset_m = round(max(offsets), 2)

    if any(p.closed for p, _d in covered):
        m.status = "closed"
        return m
    if coverage < MIN_COVERAGE:
        m.status = "insufficient_coverage"
        return m

    usable = [(p, d) for p, d in covered if p.speed_mps >= MIN_SPEED_MPS and p.freeflow_mps >= MIN_SPEED_MPS]
    if len(usable) / n < MIN_COVERAGE:
        m.status = "insufficient_coverage"
        return m

    t_obs = sum(ref.bin_len / p.speed_mps for p, _d in usable)
    t_ff = sum(ref.bin_len / p.freeflow_mps for p, _d in usable)
    covered_len = ref.bin_len * len(usable)
    scale = ref.line.length / covered_len
    m.travel_time_s = round(t_obs * scale, 2)
    m.freeflow_time_s = round(t_ff * scale, 2)
    m.speed_kmh = round(ref.line.length / m.travel_time_s * 3.6, 2)
    m.freeflow_kmh = round(ref.line.length / m.freeflow_time_s * 3.6, 2)

    def weighted(attr):
        vals = [(getattr(p, attr)) for p, _d in usable if getattr(p, attr) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    m.confidence = weighted("confidence")
    m.jam_factor = weighted("jam_factor")
    m.status = "ok"
    return m


def match_all(refs: Sequence[ReferenceSegment], pieces: Sequence[FlowPiece]) -> List[SegmentMatch]:
    return [match_segment(r, pieces) for r in refs]


def mps(kmh: float) -> float:
    return float(kmh) / 3.6


def is_finite_positive(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x) and x > 0
