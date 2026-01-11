import pytest
from sources import tomtom
from ui_messages import normalization_banner_text


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    monkeypatch.setattr("sources.tomtom.cache_read", lambda *a, **k: None)
    monkeypatch.setattr("sources.tomtom.cache_write", lambda *a, **k: None)


def test_tomtom_normalized_when_no_api_key_sample_mode():
    data = tomtom.get_ayalon_segments(api_key=None, cache_ttl_s=0, mode="sample")
    assert data["vehicle_count_mode"] == "normalized_per_probe"
    assert data["source_id"].startswith("tomtom_flow_v4")
    for seg in data["segments"]:
        assert seg["vehicle_count"] == 1
        assert seg["vehicle_count_mode"] == "normalized_per_probe"
        assert seg["source_id"].startswith("tomtom_flow_v4")


def test_tomtom_flow_estimated_with_coordinates(monkeypatch):
    fake_json = {
        "flowSegmentData": {
            "currentSpeed": 60.0,  # km/h
            "currentTravelTime": 120.0,  # s
            "freeFlowSpeed": 90.0,
            "freeFlowTravelTime": 80.0,
            "confidence": 0.9,
            "roadClosure": False,
            "coordinates": {
                "coordinate": [
                    {"latitude": 32.064, "longitude": 34.791},
                    {"latitude": 32.065, "longitude": 34.792},
                ]
            },
        }
    }
    headers = {"tracking-id": "abc-123"}
    monkeypatch.setattr(tomtom, "_call_tomtom", lambda api_key, lat, lon, unit="KMPH": (fake_json, headers, "url_no_key", 200))
    data = tomtom.get_ayalon_segments(api_key="key", cache_ttl_s=0)
    assert data["vehicle_count_mode"] == "flow_estimated"
    first = data["segments"][0]
    assert first["vehicle_count_mode"] == "flow_estimated"
    # With DEFAULT_DENSITY_VEH_PER_KM=25, flow_vph = 60*25=1500
    assert first["vehicle_count"] == 60 * int(tomtom.DEFAULT_DENSITY_VEH_PER_KM)
    assert first["observed_travel_time_s"] == pytest.approx(120.0)
    assert first["raw"]["tracking_id"] == "abc-123"


def test_tomtom_windowed_polyline_length(monkeypatch):
    # Build a long polyline (~200 points) along latitude; probe is near the middle
    coords = [{"latitude": 32.060 + i * 0.0001, "longitude": 34.791} for i in range(200)]
    fake_json = {
        "flowSegmentData": {
            "currentSpeed": 50.0,
            "currentTravelTime": 100.0,
            "freeFlowSpeed": 90.0,
            "freeFlowTravelTime": 80.0,
            "confidence": 0.9,
            "roadClosure": False,
            "coordinates": {"coordinate": coords},
        }
    }
    headers = {"tracking-id": "win-123"}
    monkeypatch.setattr(tomtom, "_call_tomtom", lambda api_key, lat, lon, unit="KMPH": (fake_json, headers, "url_no_key", 200))

    full_len_km = tomtom._polyline_length_km(coords)
    data = tomtom.get_ayalon_segments(api_key="key", cache_ttl_s=0)
    seg = data["segments"][1]  # ha_shalom probe (lat ~32.064)
    assert seg["raw"]["polyline_points_total"] == 200
    assert seg["raw"]["polyline_points_used"] == 2 * tomtom.POLYLINE_HALF_WINDOW + 1
    assert seg["raw"]["polyline_window_half"] == tomtom.POLYLINE_HALF_WINDOW
    assert seg["length_km"] < full_len_km / 5


def test_fail_closed_on_low_confidence(monkeypatch):
    bad_json = {
        "flowSegmentData": {
            "currentSpeed": 60.0,
            "currentTravelTime": 120.0,
            "freeFlowSpeed": 90.0,
            "freeFlowTravelTime": 80.0,
            "confidence": 0.2,
            "roadClosure": False,
            "coordinates": {"coordinate": [{"latitude": 32.064, "longitude": 34.791}, {"latitude": 32.065, "longitude": 34.792}]},
        }
    }
    monkeypatch.setattr(tomtom, "_call_tomtom", lambda api_key, lat, lon, unit="KMPH": (bad_json, {}, "url_no_key", 200))
    with pytest.raises(RuntimeError):
        tomtom.get_ayalon_segments(api_key="key", cache_ttl_s=0)


def test_ui_banner_text_for_normalized_mode():
    msg = normalization_banner_text("normalized_per_probe")
    assert "Normalized metrics" in msg
    assert normalization_banner_text("flow_estimated") is None
