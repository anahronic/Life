"""Mathematical checks of methodology v2 (units, zero-at-free-flow, sampling invariance)."""

import json

import pytest

import methodology_v2 as m


def _series(step_s, hours=2.0, tt=150.0, ff=100.0, t0=1_800_000_000.0):
    n = int(hours * 3600 / step_s)
    return [{"observed_at_ts": t0 + k * step_s, "travel_time_s": tt, "freeflow_time_s": ff} for k in range(n)], (t0, t0 + hours * 3600)


def test_delay_zero_at_free_flow():
    assert m.delay_per_vehicle_s(100.0, 100.0) == 0.0
    assert m.delay_per_vehicle_s(95.0, 100.0) == 0.0  # faster than reference is not negative delay
    assert m.delay_per_vehicle_s(130.0, 100.0) == 30.0
    assert m.delay_per_vehicle_s(None, 100.0) is None


def test_summary_independent_of_sampling_rate():
    a, w = _series(300)
    b, _ = _series(60)
    sa, sb = m.summarize_series(a, w), m.summarize_series(b, w)
    assert sa.mean_delay_s == pytest.approx(50.0)
    assert sb.mean_delay_s == pytest.approx(50.0)
    assert sa.observed_s == pytest.approx(sb.observed_s)
    assert sa.coverage == pytest.approx(1.0)


def test_gaps_are_not_filled():
    rows, w = _series(300, hours=1.0)
    rows = rows[:4] + rows[-2:]  # 3 observations missing in the middle
    s = m.summarize_series(rows, w)
    # 4 obs x 300 s + gap hold of 600 s max (ends at next obs anyway) ...
    assert s.observed_s < 3600
    held = m.step_hold_intervals([r["observed_at_ts"] for r in rows], w, max_hold_s=600)
    assert max(b - a for _i, a, b in held) <= 600


def test_single_stale_observation_holds_at_most_max_hold():
    rows = [{"observed_at_ts": 0.0, "travel_time_s": 200.0, "freeflow_time_s": 100.0}]
    s = m.summarize_series(rows, (0.0, 86400.0))
    assert s.observed_s == pytest.approx(m.MAX_HOLD_S)
    assert s.coverage == pytest.approx(m.MAX_HOLD_S / 86400)


def _profile(tmp_path, vph=1000.0):
    p = tmp_path / "vol.json"
    p.write_text(json.dumps({"source": "test", "citation": "unit test", "weekday_vph": [vph] * 24, "weekend_vph": [vph] * 24}))
    return m.load_volume_profile(p)


def test_vehicle_hours_units_and_sampling_invariance(tmp_path):
    prof = _profile(tmp_path, 1000.0)
    a, w = _series(300, hours=2.0, tt=160.0, ff=100.0)
    b, _ = _series(60, hours=2.0, tt=160.0, ff=100.0)
    # d = 60 s/veh = 1/60 h/veh ; q = 1000 veh/h ; 2 h -> 1000 * 2 / 60 = 33.33 veh*h
    assert m.vehicle_hours(a, w, prof) == pytest.approx(1000 * 2 / 60, rel=1e-6)
    assert m.vehicle_hours(b, w, prof) == pytest.approx(1000 * 2 / 60, rel=1e-6)


def test_vehicle_hours_zero_at_free_flow(tmp_path):
    prof = _profile(tmp_path)
    rows, w = _series(300, tt=100.0, ff=100.0)
    assert m.vehicle_hours(rows, w, prof) == 0.0


def test_economic_chain():
    e = m.economic_estimates(10.0, 7.5)
    assert e["fuel_excess_l"] == pytest.approx(10.0 * 0.8 * 1.5)
    assert e["co2_kg"] == pytest.approx(e["fuel_excess_l"] * 2.31)
    assert e["fuel_cost_ils"] == pytest.approx(e["fuel_excess_l"] * 7.5)
    assert e["time_value_ils"] == pytest.approx(10.0 * 62.5)


def test_volume_profile_requires_documentation(tmp_path):
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"weekday_vph": [1] * 24, "weekend_vph": [1] * 24}))
    assert m.load_volume_profile(p) is None
    assert m.load_volume_profile(tmp_path / "missing.json") is None


def test_v1_defect_reproduced_and_fixed():
    """v1 on the real 2026-01-10 free-flow response reported ~858 h; v2 gives 0 delay."""
    from methodology import AyalonModel

    segs = [
        {"segment_id": "la_guardia", "length_km": 1.142, "observed_travel_time_s": 980.0, "vehicle_count": 1675},
        {"segment_id": "ha_shalom", "length_km": 0.382, "observed_travel_time_s": 341.0, "vehicle_count": 2375},
        {"segment_id": "arlozorov", "length_km": 0.615, "observed_travel_time_s": 341.0, "vehicle_count": 2375},
    ]
    assert AyalonModel().calculate_time_dissipation(segs) == pytest.approx(858, abs=1)
    # v2: currentSpeed == freeFlowSpeed in that response -> equal times over the same stretch
    assert m.delay_per_vehicle_s(980.0, 980.0) == 0.0
