import pytest
from methodology import AyalonModel


def test_model_math_values():
    model = AyalonModel()
    segments = [
        {'segment_id': 's1', 'length_km': 5.0, 'observed_travel_time_s': 300.0, 'vehicle_count': 1000},
        {'segment_id': 's2', 'length_km': 5.0, 'observed_travel_time_s': 720.0, 'vehicle_count': 1000},
        {'segment_id': 's3', 'length_km': 10.0, 'observed_travel_time_s': 1800.0, 'vehicle_count': 2000},
    ]
    # Use known fuel price override
    res = model.run_model(segments, data_timestamp_utc='2026-01-08T00:00:00Z', source_ids={'traffic':'test'}, p_fuel_ils_per_l=7.5, pipeline_run_id='test')
    # expected values computed analytically
    assert abs(res['delta_T_total_h'] - 950.0) < 1e-6
    assert abs(res['fuel_excess_L'] - 1140.0) < 1e-6
    assert abs(res['leakage_ils'] - 8550.0) < 1e-6
    assert abs(res['co2_emissions_kg'] - 2633.4) < 1e-6
    assert 'model_version' in res and res['model_version'] == '1.0-freeze'
    assert 'constants_version' in res and res['constants_version'] == 'AppendixA-v1.2'
