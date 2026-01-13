import os
import time
import streamlit as st
from methodology import AyalonModel
from sources import tomtom
from sources.air_quality import get_air_quality_for_ayalon
from sources.fuel_govil import fetch_current_fuel_price_ils_per_l as fetch_current_fuel_price
from sources.secure_config import SecureConfig
from sources.health import get_quick_status
from sources.analytics import get_dashboard_summary, record_request, record_stale_data
from sources.error_handler import ErrorHandler
from ui_messages import normalization_banner_text
from datetime import datetime

st.set_page_config(page_title="Ayalon Real-Time Physical Impact Model", layout="wide")

st.title("Ayalon Real-Time Physical Impact Model — Monitor")
st.markdown("**Version:** 1.0 (Freeze) | **Layer:** L5 — Transport / Physical Truth | **Scope:** Highway 20 (Ayalon), Israel")

model = AyalonModel()

# Controls
st.sidebar.header("Data & Refresh")
api_key = SecureConfig.get_tomtom_api_key()
auto_refresh = st.sidebar.checkbox("Auto-refresh every 5 minutes", value=True)

# Public-friendly system status (no secrets)
st.sidebar.info(f"System health: {get_quick_status()}")

# Traffic mode selection
default_sample = api_key is None and SecureConfig.get_enable_sample_mode()
traffic_mode = "sample" if default_sample else "flow"
traffic_mode = st.sidebar.selectbox(
    "Traffic mode",
    options=["flow", "sample"],
    index=0 if traffic_mode == "flow" else 1,
    help="Flow requires TOMTOM_API_KEY (server-side secret). Sample is synthetic for demos/testing.",
)
if traffic_mode == "flow" and not api_key:
    err = ErrorHandler.handle_missing_key_error()
    st.sidebar.error(err.message)

# Fetch sources (cached inside sources module)
try:
    tomtom_data = tomtom.get_ayalon_segments(api_key, cache_ttl_s=SecureConfig.get_cache_ttl(), mode=traffic_mode)
    if tomtom_data.get("errors"):
        record_request(success=False, error_code=str(tomtom_data["errors"][0])[:60])
    else:
        record_request(success=True)
except Exception as e:
    api_err = ErrorHandler.handle_api_call_error(e, service="tomtom")
    tomtom_data = {"source_id": "tomtom:error", "segments": [], "errors": [api_err.message], "fetched_at": datetime.utcnow().isoformat() + "Z"}
    record_request(success=False, error_code=api_err.code.value)

aq_data = get_air_quality_for_ayalon(cache_ttl_s=600)
fuel_data = fetch_current_fuel_price()
vehicle_count_mode = tomtom_data.get('vehicle_count_mode')

# Freshness and stale logic
def parse_iso_to_ts(s: str):
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except:
        return 0

now_ts = time.time()
tomtom_ts = parse_iso_to_ts(tomtom_data.get('fetched_at', '1970-01-01T00:00:00Z'))
tomtom_age = now_ts - tomtom_ts
st.sidebar.write(f"Traffic age: {int(tomtom_age)}s")
if auto_refresh and tomtom_age > 300:
    st.rerun()

# Lightweight analytics summary
summary = get_dashboard_summary()
st.sidebar.metric("Success rate", summary.get("success_rate", "n/a"))
st.sidebar.metric("Cache hit ratio", summary.get("cache_hit_ratio", "n/a"))
st.sidebar.write(f"Errors (session): {summary.get('errors_this_session', 0)}")

st.header("Input Data Sources")
col1, col2, col3 = st.columns(3)
col1.metric("Traffic Source", tomtom_data.get('source_id', 'tomtom:unknown'))
col1.write(f"Updated: {tomtom_data.get('fetched_at')}")
col2.metric("Air Quality Source", aq_data.get('source_id', 'air:unknown'))
col2.write(f"Updated: {aq_data.get('fetched_at')}")
aq_metrics = aq_data.get('metrics') or {}
if aq_metrics.get('pm2_5_ug_m3') is not None:
    col2.write(f"PM2.5 (µg/m³): {aq_metrics.get('pm2_5_ug_m3')}")
if aq_metrics.get('us_aqi') is not None:
    col2.write(f"US AQI: {aq_metrics.get('us_aqi')}")
if aq_data.get('error'):
    col2.warning(str(aq_data.get('error'))[:200])
col3.metric("Fuel Price Source", fuel_data.get('source_id', 'gov-or-env'))
col3.write(f"Price (ILS/L): {fuel_data.get('price_ils_per_l', 'n/a')}")

banner = normalization_banner_text(vehicle_count_mode)
if banner:
    st.warning(banner)

# Build canonical segments from tomtom_data
segments = tomtom_data.get('segments', [])
if not segments:
    if tomtom_data.get("errors"):
        st.error(tomtom_data["errors"][0])
    else:
        st.error("No traffic segments available; check configuration or network")

# Run model when data present
if segments and 'price_ils_per_l' in fuel_data:
    src_ids = {
        'traffic': tomtom_data.get('source_id'),
        'air': aq_data.get('source_id'),
        'fuel': fuel_data.get('source_id'),
    }
    data_ts = tomtom_data.get('fetched_at')
    p_fuel = float(fuel_data['price_ils_per_l'])
    results = model.run_model(segments, data_timestamp_utc=data_ts, source_ids=src_ids, p_fuel_ils_per_l=p_fuel, vehicle_count_mode=vehicle_count_mode)

    st.header("Physical Counters")
    # Vehicle-Hours (not human-hours)
    delta_T = results['delta_T_total_h']
    col1, col2 = st.columns(2)
    col1.metric("Vehicle-Hours (h)", f"{delta_T:.2f}")
    col2.metric("CO2 Emissions (kg)", f"{results['co2_emissions_kg']:.2f}")

    st.subheader("Resource Incinerator")
    st.metric("Excess Fuel (L)", f"{results['fuel_excess_L']:.2f}")
    st.metric("Energy-to-Capital (₪)", f"{results['leakage_ils']:.2f}")
    if vehicle_count_mode == 'normalized_per_probe':
        st.caption("Normalized (per probe)")

    st.subheader("Provenance")
    st.write(f"Model version: {results['model_version']}")
    st.write(f"Constants version: {results['constants_version']}")
    st.write(f"Data timestamp: {results['data_timestamp_utc']}")
    st.write(f"Pipeline run id: {results['pipeline_run_id']}")

    # STALE indicators
    stale = tomtom_age > 600
    if stale:
        st.warning("Traffic data is STALE (older than 2×cadence)")
        record_stale_data()
else:
    st.info("Waiting for valid fuel price or traffic feed. Set FUEL_PRICE_ILS env var as fallback.")

st.markdown("---")
st.markdown("**Modeling Note:** This model enforces canonical segment schema and attaches provenance to each run.")
st.caption(
    "Data sources: TomTom Traffic Flow (v4) for traffic, Sviva API for air quality, and government sources for fuel price. "
    "Update cadence is ~5 minutes (cache TTL). Vehicle counts are *estimated* from flow/speed and are not an official vehicle counter."
)