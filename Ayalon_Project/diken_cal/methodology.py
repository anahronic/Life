# Methodology.py: Ayalon Real-Time Physical Impact Model
# Version: 1.0 (Freeze)
# Layer: L5 — Transport / Physical Truth
# Scope: Highway 20 (Ayalon), Israel

class AyalonModel:
    """Ayalon Real-Time Physical Impact Model

    Version: 1.0-freeze

    Implements unit-safe calculations and returns provenance metadata.
    """
    def __init__(self):
        # Protocol Constants (Appendix A)
        self.V_free_kmh = 90.0  # km/h (posted free-flow speed)
        self.Fuel_idle_rate_L_per_h = 0.8  # L/hour
        self.StopGo_factor = 1.5
        self.Value_of_Time_ILS_per_h = 62.50  # ILS/hour
        # P_fuel should be provided from fuel source; fallback to env/config when absent
        self.P_fuel_ILS_per_L = None
        self.CO2_per_liter = 2.31  # kg/L
        # Versions
        self.model_version = "1.0-freeze"
        self.constants_version = "AppendixA-v1.2"

    def calculate_time_dissipation(self, segments):
        """
        segments: list of canonical dicts with keys:
          - segment_id
          - length_km
          - observed_travel_time_s
          - vehicle_count

        Returns delta_T_total in human-hours (float)
        """
        # Convert constants
        V_free_mps = (self.V_free_kmh / 3.6)
        delta_T_total_seconds = 0.0
        for seg in segments:
            L_m = seg['length_km'] * 1000.0
            T_obs_s = float(seg['observed_travel_time_s'])
            Vehicles = float(seg['vehicle_count'])
            T_free_s = L_m / V_free_mps if V_free_mps > 0 else float('inf')
            delta_T_segment_s = max(0.0, T_obs_s - T_free_s)
            delta_T_total_seconds += delta_T_segment_s * Vehicles
        # convert seconds to hours
        return delta_T_total_seconds / 3600.0

    def calculate_fuel_excess(self, segments):
        """
        Returns fuel excess in liters (L)

        Fuel_excess = sum( Vehicles * delta_T_segment_s/3600 * Fuel_idle_rate_L_per_h * StopGo_factor )
        """
        fuel_excess_L = 0.0
        for seg in segments:
            T_obs_s = float(seg['observed_travel_time_s'])
            L_m = seg['length_km'] * 1000.0
            V_free_mps = (self.V_free_kmh / 3.6)
            T_free_s = L_m / V_free_mps if V_free_mps > 0 else float('inf')
            delta_T_segment_s = max(0.0, T_obs_s - T_free_s)
            Vehicles = float(seg['vehicle_count'])
            fuel_excess_L += Vehicles * (delta_T_segment_s / 3600.0) * self.Fuel_idle_rate_L_per_h * self.StopGo_factor
        return fuel_excess_L

    def calculate_leakage_ils(self, fuel_excess_L, p_fuel_ils_per_l=None):
        p = p_fuel_ils_per_l if p_fuel_ils_per_l is not None else self.P_fuel_ILS_per_L
        if p is None:
            raise RuntimeError("Fuel price (ILS/L) not set; provide p_fuel_ils_per_l or set model.P_fuel_ILS_per_L")
        return fuel_excess_L * p

    def calculate_co2_emissions(self, fuel_excess_L):
        return fuel_excess_L * self.CO2_per_liter

    def run_model(self, segments, data_timestamp_utc: str, source_ids: dict, p_fuel_ils_per_l: float | None = None, pipeline_run_id: str | None = None, vehicle_count_mode: str | None = None):
        """
        Run the model over canonical segments and return physical counters with provenance.

        Args:
          - segments: list of canonical segment dicts (see calculate_time_dissipation doc)
          - data_timestamp_utc: ISO timestamp string representing the data window
          - source_ids: dict with keys like {'traffic': 'tomtom:resp_id', 'air': 'sviva:station_2', 'fuel': 'gov:2026-01'}
          - p_fuel_ils_per_l: optional override for fuel price
          - pipeline_run_id: optional UUID for this pipeline run

        Returns dict including provenance fields required by PTL.
        """
        import uuid
        from datetime import datetime

        pipeline_id = pipeline_run_id or str(uuid.uuid4())
        delta_T_total_h = self.calculate_time_dissipation(segments)
        fuel_excess_L = self.calculate_fuel_excess(segments)
        leakage_ils = self.calculate_leakage_ils(fuel_excess_L, p_fuel_ils_per_l)
        co2_kg = self.calculate_co2_emissions(fuel_excess_L)

        result = {
            'delta_T_total_h': float(delta_T_total_h),
            'fuel_excess_L': float(fuel_excess_L),
            'leakage_ils': float(leakage_ils),
            'co2_emissions_kg': float(co2_kg),
            # provenance
            'model_version': self.model_version,
            'constants_version': self.constants_version,
            'data_timestamp_utc': data_timestamp_utc,
            'data_source_ids': source_ids,
            'pipeline_run_id': pipeline_id,
            'generated_at_utc': datetime.utcnow().isoformat() + 'Z',
            'vehicle_count_mode': vehicle_count_mode or 'unknown',
        }
        return result

if __name__ == "__main__":
    import json
    model = AyalonModel()
    # Canonical schema demo
    segments = [
        {'segment_id': 's1', 'length_km': 5.0, 'observed_travel_time_s': 300.0, 'vehicle_count': 1000},
        {'segment_id': 's2', 'length_km': 5.0, 'observed_travel_time_s': 720.0, 'vehicle_count': 1000},
        {'segment_id': 's3', 'length_km': 10.0, 'observed_travel_time_s': 1800.0, 'vehicle_count': 2000},
    ]
    data_ts = "2026-01-08T00:00:00Z"
    source_ids = {'traffic': 'tomtom:sample', 'air': 'sviva:sample', 'fuel': 'gov.il:fuel-notice:2026-01'}
    results = model.run_model(segments, data_timestamp_utc=data_ts, source_ids=source_ids, p_fuel_ils_per_l=7.5, vehicle_count_mode='sample')
    print(json.dumps(results, ensure_ascii=False, indent=2))