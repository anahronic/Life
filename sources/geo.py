"""Planar geometry helpers for road-segment matching (WGS84 in, metres out).

All distance work is done in a local equirectangular projection centred on
the area of interest.  Over the ~15 km extent of the Ayalon corridor the
projection error is far below 0.1 %, which is negligible compared with the
metre-level tolerances used for matching.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

LatLon = Tuple[float, float]

EARTH_RADIUS_M = 6371008.8


def haversine_m(a: LatLon, b: LatLon) -> float:
    """Great-circle distance in metres between two (lat, lon) points."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


class LocalProjection:
    """Equirectangular projection around a reference latitude/longitude."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0 = lat0
        self.lon0 = lon0
        self.kx = math.radians(1) * EARTH_RADIUS_M * math.cos(math.radians(lat0))
        self.ky = math.radians(1) * EARTH_RADIUS_M

    def to_xy(self, p: LatLon) -> Tuple[float, float]:
        return ((p[1] - self.lon0) * self.kx, (p[0] - self.lat0) * self.ky)

    def to_ll(self, xy: Tuple[float, float]) -> LatLon:
        return (xy[1] / self.ky + self.lat0, xy[0] / self.kx + self.lon0)


def polyline_length_m(pts: Sequence[LatLon]) -> float:
    return sum(haversine_m(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def bearing_deg(a: LatLon, b: LatLon) -> float:
    """Initial bearing from a to b, degrees clockwise from north [0, 360)."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def angle_diff_deg(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings (0..180)."""
    d = abs(a - b) % 360.0
    return 360.0 - d if d > 180.0 else d


class ProjectedPolyline:
    """A polyline projected to local metres with cumulative chainage."""

    def __init__(self, pts: Sequence[LatLon], proj: LocalProjection):
        if len(pts) < 2:
            raise ValueError("polyline needs at least two points")
        self.ll = [(float(p[0]), float(p[1])) for p in pts]
        self.proj = proj
        self.xy = [proj.to_xy(p) for p in self.ll]
        self.cum = [0.0]
        for i in range(len(self.xy) - 1):
            self.cum.append(self.cum[-1] + math.dist(self.xy[i], self.xy[i + 1]))
        self.length = self.cum[-1]
        xs = [p[0] for p in self.xy]
        ys = [p[1] for p in self.xy]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))

    def nearest(self, q: Tuple[float, float]) -> Tuple[float, float, int]:
        """Return (distance_m, chainage_m, segment_index) of the closest point."""
        best = (float("inf"), 0.0, 0)
        qx, qy = q
        for i in range(len(self.xy) - 1):
            ax, ay = self.xy[i]
            bx, by = self.xy[i + 1]
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((qx - ax) * dx + (qy - ay) * dy) / seg2))
            px, py = ax + t * dx, ay + t * dy
            d = math.hypot(qx - px, qy - py)
            if d < best[0]:
                best = (d, self.cum[i] + t * math.sqrt(seg2), i)
        return best

    def heading_at_segment(self, i: int) -> float:
        (ax, ay), (bx, by) = self.xy[i], self.xy[i + 1]
        return (math.degrees(math.atan2(bx - ax, by - ay)) + 360.0) % 360.0

    def point_at(self, chainage: float) -> Tuple[Tuple[float, float], int]:
        """Point (projected xy) and segment index at a given chainage."""
        c = max(0.0, min(self.length, chainage))
        for i in range(len(self.cum) - 1):
            if self.cum[i + 1] >= c:
                seg = self.cum[i + 1] - self.cum[i]
                t = 0.0 if seg == 0 else (c - self.cum[i]) / seg
                (ax, ay), (bx, by) = self.xy[i], self.xy[i + 1]
                return (ax + t * (bx - ax), ay + t * (by - ay)), i
        return self.xy[-1], len(self.xy) - 2

    def cut(self, c0: float, c1: float) -> List[LatLon]:
        """Sub-polyline between chainages c0 < c1, as (lat, lon) points."""
        c0 = max(0.0, min(self.length, c0))
        c1 = max(0.0, min(self.length, c1))
        if c1 <= c0:
            raise ValueError("cut: empty interval")
        p0, i0 = self.point_at(c0)
        p1, i1 = self.point_at(c1)
        out = [p0] + [self.xy[k] for k in range(i0 + 1, i1 + 1)] + [p1]
        dedup = [out[0]]
        for p in out[1:]:
            if math.dist(p, dedup[-1]) > 1e-6:
                dedup.append(p)
        return [self.proj.to_ll(p) for p in dedup]


def split_by_lengths(pts: Sequence[LatLon], lengths: Sequence[float], proj: LocalProjection) -> List[List[LatLon]]:
    """Split a polyline into consecutive pieces of the given nominal lengths.

    The nominal lengths (e.g. provider-reported sub-segment lengths) are
    rescaled to the geometric length of the polyline so rounding differences
    do not leave a gap or overshoot at the end.
    """
    line = ProjectedPolyline(pts, proj)
    total = float(sum(lengths))
    if total <= 0:
        raise ValueError("split_by_lengths: non-positive total length")
    scale = line.length / total
    pieces: List[List[LatLon]] = []
    c = 0.0
    for n, ln in enumerate(lengths):
        c_next = line.length if n == len(lengths) - 1 else c + ln * scale
        if c_next - c > 0.01:
            pieces.append(line.cut(c, c_next))
        c = c_next
    return pieces


def point_distance_to_polyline_m(p: LatLon, pts: Sequence[LatLon]) -> float:
    proj = LocalProjection(p[0], p[1])
    return ProjectedPolyline(pts, proj).nearest(proj.to_xy(p))[0]


def bbox_expand(b: Tuple[float, float, float, float], m: float) -> Tuple[float, float, float, float]:
    return (b[0] - m, b[1] - m, b[2] + m, b[3] + m)


def bbox_intersects(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def optional_float(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None
