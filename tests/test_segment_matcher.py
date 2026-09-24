"""Geographic matching tests on REAL TomTom responses of 2026-09-15 09:42 UTC.

Fixtures (tests/fixtures/tomtom_2026-09-15) are the last successful v1
responses copied from the production cache.
"""

import json
from pathlib import Path

import pytest

from sources.geo import haversine_m
from sources.segment_matcher import (
    FlowPiece,
    load_reference_segments,
    match_all,
    match_segment,
    mps,
)

FIX = Path(__file__).parent / "fixtures" / "tomtom_2026-09-15"


def _piece(name):
    f = next(FIX.glob(f"tt_v4_abs10_flow_{name}_*.json"))
    d = json.loads(f.read_text())["data"]
    fsd = d["raw"]["response"]["flowSegmentData"]
    pts = [(c["latitude"], c["longitude"]) for c in fsd["coordinates"]["coordinate"]]
    return FlowPiece(pts, mps(fsd["currentSpeed"]), mps(fsd["freeFlowSpeed"]), name, confidence=fsd["confidence"]), fsd


@pytest.fixture(scope="module")
def refs():
    return load_reference_segments()


@pytest.fixture(scope="module")
def by_id(refs):
    return {r.segment_id: r for r in refs}


def test_reference_definitions(refs):
    assert len(refs) == 6
    ids = [r.segment_id for r in refs]
    assert len(set(ids)) == 6
    for r in refs:
        # declared length equals geometric length
        geo = sum(haversine_m(r.geometry[i], r.geometry[i + 1]) for i in range(len(r.geometry) - 1))
        assert abs(geo - r.length_m) / r.length_m < 0.002
        assert 1500 < r.length_m < 3000
    for d in ("northbound", "southbound"):
        seq = [r for r in refs if r.direction == d]
        # contiguous: each section starts where the previous ended
        for a, b in zip(seq, seq[1:]):
            assert haversine_m(a.geometry[-1], b.geometry[0]) < 1.0
    north = [r for r in refs if r.direction == "northbound"]
    assert all(r.meta["mean_bearing_deg"] < 45 for r in north)
    assert all(170 < r.meta["mean_bearing_deg"] < 230 for r in refs if r.direction == "southbound")


def test_route44_piece_is_rejected(refs):
    """v1 probe 'la_guardia' received Route 44 (FRC2); it must not match Ayalon."""
    p, fsd = _piece("la_guardia")
    assert fsd["frc"] == "FRC2"
    for m in match_all(refs, [p]):
        assert m.status == "no_data" and m.coverage == 0.0


def test_ayalon_north_piece_matches_northbound_only(refs):
    p, fsd = _piece("arlozorov")
    res = {m.segment_id: m for m in match_all(refs, [p])}
    for sid in ("ayalon_n_laguardia_arlozorov", "ayalon_n_arlozorov_rokach"):
        m = res[sid]
        assert m.status == "ok" and m.coverage == 1.0
        assert m.max_offset_m < 20
        # travel time = length / speed, free-flow time over the SAME stretch
        # (stored values are rounded to 0.01 s / 0.01 km/h)
        assert m.travel_time_s == pytest.approx(m.length_m / mps(fsd["currentSpeed"]), abs=0.01)
        assert m.freeflow_time_s == pytest.approx(m.length_m / mps(fsd["freeFlowSpeed"]), abs=0.01)
        assert m.speed_kmh == pytest.approx(fsd["currentSpeed"], abs=0.01)
    # TomTom segment starts north of Holon: not enough coverage -> no value
    assert res["ayalon_n_holon_laguardia"].status == "insufficient_coverage"
    assert res["ayalon_n_holon_laguardia"].travel_time_s is None
    for sid, m in res.items():
        if sid.startswith("ayalon_s_"):
            assert m.status == "no_data"


def test_v1_shared_polyline_is_one_measurement(refs):
    """ha_shalom and arlozorov got the identical polyline: matching both adds nothing."""
    a, _ = _piece("arlozorov")
    b, _ = _piece("ha_shalom")
    assert a.points == b.points
    one = {m.segment_id: m.travel_time_s for m in match_all(refs, [a])}
    both = {m.segment_id: m.travel_time_s for m in match_all(refs, [a, b])}
    assert one == both


def test_opposite_direction_rejected(by_id):
    p, _ = _piece("arlozorov")
    reversed_piece = FlowPiece(list(reversed(p.points)), p.speed_mps, p.freeflow_mps, "rev", confidence=1.0)
    m = match_segment(by_id["ayalon_n_arlozorov_rokach"], [reversed_piece])
    assert m.status == "no_data"


def test_parallel_offset_road_rejected(by_id):
    ref = by_id["ayalon_n_arlozorov_rokach"]
    shifted = [(lat, lon + 0.0006) for lat, lon in ref.geometry]  # ~57 m east
    m = match_segment(ref, [FlowPiece(shifted, 20.0, 25.0, "shift", confidence=1.0)])
    assert m.status == "no_data"


def test_free_flow_gives_zero_delay(by_id):
    ref = by_id["ayalon_s_rokach_arlozorov"]
    m = match_segment(ref, [FlowPiece(ref.geometry, 25.0, 25.0, "ff", confidence=1.0)])
    assert m.status == "ok"
    assert m.travel_time_s == pytest.approx(m.freeflow_time_s)
    assert m.travel_time_s == pytest.approx(ref.length_m / 25.0, rel=1e-3)


def test_mixed_speeds_are_harmonic(by_id):
    """Half the section at 10 m/s, half at 30 m/s -> T = L/2/10 + L/2/30."""
    ref = by_id["ayalon_s_rokach_arlozorov"]
    mid = len(ref.geometry) // 2
    p1 = FlowPiece(ref.geometry[: mid + 1], 10.0, 30.0, "a", confidence=1.0)
    p2 = FlowPiece(ref.geometry[mid:], 30.0, 30.0, "b", confidence=1.0)
    m = match_segment(ref, [p1, p2])
    covered = ref.line.cum[mid]
    expected = covered / 10.0 + (ref.line.length - covered) / 30.0
    assert m.travel_time_s == pytest.approx(expected, rel=0.01)
    assert m.freeflow_time_s == pytest.approx(ref.line.length / 30.0, rel=1e-3)


def test_closed_road(by_id):
    ref = by_id["ayalon_s_rokach_arlozorov"]
    m = match_segment(ref, [FlowPiece(ref.geometry, 0.0, 25.0, "closed", closed=True)])
    assert m.status == "closed" and m.travel_time_s is None
