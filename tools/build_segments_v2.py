"""Build reference/ayalon_segments_v2.json from an OpenStreetMap snapshot.

Reproducible: the Overpass response used is committed under reference/osm/.

    python tools/build_segments_v2.py

Segments are interchange-to-interchange sections of Highway 20 (Ayalon),
one per carriageway direction, contiguous and non-overlapping, so that
per-direction sums of length and travel time are physically meaningful.

Geometry (c) OpenStreetMap contributors, ODbL 1.0.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sources.geo import LocalProjection, ProjectedPolyline, bearing_deg  # noqa: E402

OSM_SNAPSHOT = ROOT / "reference" / "osm" / "ayalon_route20_ways_2026-09-24.json"
OUT = ROOT / "reference" / "ayalon_segments_v2.json"

SEGMENT_VERSION = 2

# Interchange anchors: OSM highway=motorway_junction nodes on Route 20
# (retrieved 2026-09-24).  Boundaries are the projection of each anchor
# onto the respective carriageway centre line.
ANCHORS = {
    "holon": {"osm_node": 33961000, "lat": 32.04067, "lon": 34.78087, "name": "Holon (11)"},
    "laguardia": {"osm_node": 336295207, "lat": 32.06311, "lon": 34.78770, "name": "La Guardia (13)"},
    "arlozorov": {"osm_node": 1226869, "lat": 32.07864, "lon": 34.79660, "name": "Arlozorov"},
    "rokach": {"osm_node": 34132812, "lat": 32.09408, "lon": 34.80184, "name": "Rokach (17)"},
}

# (direction key, OSM name:en, ordered anchors in driving direction)
CARRIAGEWAYS = [
    ("n", "Ayalon North", "northbound", ["holon", "laguardia", "arlozorov", "rokach"]),
    ("s", "Ayalon South", "southbound", ["rokach", "arlozorov", "laguardia", "holon"]),
]


def _chain(ways):
    """Longest connected chain of oneway ways (follows node continuity)."""
    starts = defaultdict(list)
    for w in ways:
        starts[w["nodes"][0]].append(w)
    ends = {w["nodes"][-1] for w in ways}
    heads = [w for w in ways if w["nodes"][0] not in ends]
    best = None

    def length(w):
        g = w["geometry"]
        return sum(abs(g[i]["lat"] - g[i + 1]["lat"]) + abs(g[i]["lon"] - g[i + 1]["lon"]) for i in range(len(g) - 1))

    def dfs(w, path, total):
        nonlocal best
        path = path + [w]
        total += length(w)
        nxt = [x for x in starts[w["nodes"][-1]] if x not in path]
        if not nxt and (best is None or total > best[1]):
            best = (path, total)
        for x in nxt:
            dfs(x, path, total)

    for h in heads:
        dfs(h, [], 0.0)
    return best[0]


def build() -> dict:
    osm = json.loads(OSM_SNAPSHOT.read_text(encoding="utf-8"))
    ways = [e for e in osm["elements"] if e["type"] == "way"]
    proj = LocalProjection(32.07, 34.79)
    segments = []
    for dkey, osm_name, direction, order in CARRIAGEWAYS:
        chain = _chain([w for w in ways if w["tags"].get("name:en") == osm_name])
        pts = []
        for w in chain:
            g = [(p["lat"], p["lon"]) for p in w["geometry"]]
            pts.extend(g if not pts else g[1:])
        line = ProjectedPolyline(pts, proj)
        chain_ids = [w["id"] for w in chain]
        cuts = []
        for a in order:
            d, c, _ = line.nearest(proj.to_xy((ANCHORS[a]["lat"], ANCHORS[a]["lon"])))
            if d > 150:
                raise RuntimeError(f"anchor {a} is {d:.0f} m from {osm_name}")
            cuts.append(c)
        if cuts != sorted(cuts):
            raise RuntimeError(f"anchors out of driving order on {osm_name}: {cuts}")
        for a, b, c0, c1 in zip(order, order[1:], cuts, cuts[1:]):
            geom = line.cut(c0, c1)
            seg_id = f"ayalon_{dkey}_{a}_{b}"
            segments.append({
                "segment_id": seg_id,
                "segment_version": SEGMENT_VERSION,
                "road": "Highway 20 (Ayalon)",
                "carriageway": osm_name,
                "direction": direction,
                "from": ANCHORS[a]["name"],
                "to": ANCHORS[b]["name"],
                "length_m": round(c1 - c0, 1),
                "start": [round(geom[0][0], 7), round(geom[0][1], 7)],
                "end": [round(geom[-1][0], 7), round(geom[-1][1], 7)],
                "mean_bearing_deg": round(bearing_deg(geom[0], geom[-1]), 1),
                "geometry": [[round(p[0], 7), round(p[1], 7)] for p in geom],
                "osm_way_chain": chain_ids,
            })
    return {
        "schema": "ayalon-segments",
        "segment_version": SEGMENT_VERSION,
        "generated_from": str(OSM_SNAPSHOT.relative_to(ROOT)).replace("\\", "/"),
        "osm_retrieved_utc": "2026-09-24",
        "license": "Geometry (c) OpenStreetMap contributors, ODbL 1.0",
        "anchors": ANCHORS,
        "segments": segments,
    }


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for s in data["segments"]:
        print(f"{s['segment_id']:32s} {s['direction']:10s} {s['length_m']:8.1f} m  bearing {s['mean_bearing_deg']:5.1f}  pts {len(s['geometry'])}")
