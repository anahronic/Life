import os
import time
import streamlit as st
from methodology import AyalonModel
from sources import tomtom
from sources.air_quality import get_air_quality_for_ayalon, get_cached_air_quality
from sources.fuel_govil import fetch_current_fuel_price_ils_per_l as fetch_current_fuel_price, get_cached_fuel_price
from sources.secure_config import SecureConfig
from sources.health import get_quick_status
from sources.analytics import get_dashboard_summary, record_request, record_stale_data
from sources.error_handler import ErrorHandler
from ui_messages import normalization_banner_text
from datetime import datetime
from sources.history_store import HistoryStore

st.set_page_config(page_title="Ayalon Real-Time Physical Impact Model", layout="wide")

st.title("Ayalon Real-Time Physical Impact Model — Monitor")
st.markdown("**Version:** 1.0 (Freeze) | **Layer:** L5 — Transport / Physical Truth | **Scope:** Highway 20 (Ayalon), Israel")

model = AyalonModel()
history = HistoryStore()


def _parse_iso_to_ts(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0.0


def _fetch_with_retries(label: str, fn, retries: int = 2, base_delay_s: float = 0.8):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return fn(), None
        except Exception as e:
            last_exc = e
            msg = str(e)
            # If rate-limited, don't hammer.
            if "rate-limited" in msg.lower() or "retry_after" in msg.lower():
                break
            if attempt < retries:
                time.sleep(base_delay_s * (2 ** attempt))
    return None, last_exc

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
tomtom_data, tomtom_exc = _fetch_with_retries(
    "tomtom",
    lambda: tomtom.get_ayalon_segments(api_key, cache_ttl_s=SecureConfig.get_cache_ttl(), mode=traffic_mode),
    retries=2,
)
if tomtom_data is None:
    # Fall back to stale cached traffic if available.
    cached = tomtom.get_cached_ayalon_segments(mode=traffic_mode, max_age_s=24 * 3600)
    if cached:
        cached = dict(cached)
        cached["errors"] = ["Using cached traffic due to live fetch failure"]
        tomtom_data = cached
    else:
        api_err = ErrorHandler.handle_api_call_error(tomtom_exc, service="tomtom") if tomtom_exc else ErrorHandler.handle_api_call_error(RuntimeError("TomTom fetch failed"), service="tomtom")
        tomtom_data = {"source_id": "tomtom:error", "segments": [], "errors": [api_err.message], "fetched_at": datetime.utcnow().isoformat() + "Z"}
    record_request(success=False, error_code="tomtom_fallback")
else:
    if tomtom_data.get("errors"):
        record_request(success=False, error_code=str(tomtom_data["errors"][0])[:60])
    else:
        record_request(success=True)

aq_data, aq_exc = _fetch_with_retries("air_quality", lambda: get_air_quality_for_ayalon(cache_ttl_s=600), retries=1)
if aq_data is None or aq_data.get("error"):
    cached_aq = get_cached_air_quality(max_age_s=24 * 3600)
    if cached_aq:
        aq_data = dict(cached_aq)
        aq_data["error"] = aq_data.get("error") or "Using cached air quality due to live fetch failure"
    elif aq_data is None:
        aq_data = {"source_id": "air-quality:error", "fetched_at": None, "metrics": {}, "error": str(aq_exc) if aq_exc else "Air quality fetch failed"}

fuel_data, fuel_exc = _fetch_with_retries("fuel", lambda: fetch_current_fuel_price(), retries=1, base_delay_s=1.2)
if fuel_data is None:
    cached_fuel = get_cached_fuel_price(max_age_s=14 * 86400)
    if cached_fuel:
        fuel_data = dict(cached_fuel)
        fuel_data["source_id"] = str(fuel_data.get("source_id", "fuel")) + ":cached"
    else:
        fuel_data = {"source_id": "fuel:error", "price_ils_per_l": None}

vehicle_count_mode = tomtom_data.get('vehicle_count_mode')

# Freshness and stale logic
now_ts = time.time()
tomtom_ts = _parse_iso_to_ts(tomtom_data.get('fetched_at', '1970-01-01T00:00:00Z'))
tomtom_age = now_ts - tomtom_ts
st.sidebar.write(f"Traffic age: {int(tomtom_age)}s")
if auto_refresh and tomtom_age > 300:
    st.rerun()

# Lightweight analytics summary
summary = get_dashboard_summary()
st.sidebar.metric("Success rate", summary.get("success_rate", "n/a"))
st.sidebar.metric("Cache hit ratio", summary.get("cache_hit_ratio", "n/a"))
st.sidebar.write(f"Errors (session): {summary.get('errors_this_session', 0)}")

tab_dashboard, tab_history, tab_sources = st.tabs(["Dashboard", "History & Stats", "Sources & Health"])

with tab_sources:
    st.header("Input Data Sources")
    col1, col2, col3 = st.columns(3)
    col1.metric("Traffic Source", tomtom_data.get('source_id', 'tomtom:unknown'))
    col1.write(f"Updated: {tomtom_data.get('fetched_at')}")
    if tomtom_data.get('errors'):
        col1.warning(str(tomtom_data.get('errors')[0])[:200])

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

    st.subheader("System")
    st.info(f"System health: {get_quick_status()}")

banner = normalization_banner_text(vehicle_count_mode)
if banner:
    st.warning(banner)

# Build canonical segments from tomtom_data
segments = tomtom_data.get('segments', [])
if not segments:
    if tomtom_data.get("errors"):
        with tab_dashboard:
            st.error(tomtom_data["errors"][0])
    else:
        with tab_dashboard:
            st.error("No traffic segments available; check configuration or network")

# Run model when data present
results = None
if segments and fuel_data.get('price_ils_per_l') is not None:
    src_ids = {
        'traffic': tomtom_data.get('source_id'),
        'air': aq_data.get('source_id'),
        'fuel': fuel_data.get('source_id'),
    }
    data_ts = tomtom_data.get('fetched_at')
    p_fuel = float(fuel_data['price_ils_per_l'])
    results = model.run_model(segments, data_timestamp_utc=data_ts, source_ids=src_ids, p_fuel_ils_per_l=p_fuel, vehicle_count_mode=vehicle_count_mode)

    # Persist history (for charts/tables)
    try:
        history.record_run(results=results, tomtom_data=tomtom_data, aq_data=aq_data, fuel_data=fuel_data, tomtom_age_s=tomtom_age)
    except Exception:
        # Never break UI on history persistence.
        pass

    with tab_dashboard:
        st.header("Losses — explained")
        delta_T = float(results['delta_T_total_h'])
        time_value_ils = delta_T * float(getattr(model, 'Value_of_Time_ILS_per_h', 62.5))
        colA, colB, colC, colD = st.columns(4)
        colA.metric("Vehicle-Hours (delay)", f"{delta_T:,.2f} h")
        colB.metric("CO₂ from excess fuel", f"{results['co2_emissions_kg']:,.2f} kg")
        colC.metric("Excess fuel burned", f"{results['fuel_excess_L']:,.2f} L")
        colD.metric("Direct fuel cost", f"₪ {results['leakage_ils']:,.2f}")

        st.caption(f"Indicative time-value loss (₪): ₪ {time_value_ils:,.0f} (assumes ₪{getattr(model,'Value_of_Time_ILS_per_h',62.5):.2f}/vehicle-hour)")

        with st.expander("What these numbers mean (plain language)", expanded=True):
            st.write(
                "- Vehicle-Hours (delay): total extra time all vehicles spend due to congestion vs free-flow.\n"
                "- Excess fuel (L): extra fuel burned while delayed (idle/stop-go).\n"
                "- CO₂ (kg): emissions implied by that extra fuel (using 2.31 kg CO₂ per liter).\n"
                "- Direct fuel cost (₪): fuel excess multiplied by current fuel price (ILS/L).\n"
                "These are system-level counters: they describe total impact, not a single driver."
            )

        st.subheader("Provenance")
        st.write(f"Model version: {results['model_version']}")
        st.write(f"Constants version: {results['constants_version']}")
        st.write(f"Data timestamp: {results['data_timestamp_utc']}")
        st.write(f"Pipeline run id: {results['pipeline_run_id']}")

        stale = tomtom_age > 600
        if stale:
            st.warning("Traffic data is STALE (older than 2×cadence)")
            record_stale_data()

        # Mini trend chart (last N runs)
        df = history.fetch_runs_df(limit=300)
        try:
            import pandas as pd  # type: ignore

            if isinstance(df, pd.DataFrame) and not df.empty:
                df2 = df.copy()
                df2 = df2.sort_values('recorded_at_utc')
                df2 = df2[['recorded_at_utc', 'leakage_ils', 'co2_emissions_kg', 'delta_T_total_h']].dropna()
                df2 = df2.set_index('recorded_at_utc')
                st.line_chart(df2)
        except Exception:
            pass
else:
    with tab_dashboard:
        st.info("Waiting for valid fuel price or traffic feed. Set FUEL_PRICE_ILS env var as fallback.")


with tab_history:
    st.header("History & Statistics")
    st.caption("Saved locally during monitoring (SQLite).")

    df = history.fetch_runs_df(limit=5000)
    try:
        import pandas as pd  # type: ignore

        if not isinstance(df, pd.DataFrame) or df.empty:
            st.info("No history yet. Enable auto-refresh or rerun a few times.")
        else:
            # Latest first for table readability
            df_table = df.copy()
            df_table = df_table.sort_values('recorded_at_utc', ascending=False)

            # Summary
            st.subheader("Summary")
            total_leak = float(df_table['leakage_ils'].dropna().sum()) if 'leakage_ils' in df_table else 0.0
            total_co2 = float(df_table['co2_emissions_kg'].dropna().sum()) if 'co2_emissions_kg' in df_table else 0.0
            avg_leak = float(df_table['leakage_ils'].dropna().mean()) if 'leakage_ils' in df_table and df_table['leakage_ils'].notna().any() else 0.0
            c1, c2, c3 = st.columns(3)
            c1.metric("Total fuel cost (₪)", f"₪ {total_leak:,.0f}")
            c2.metric("Total CO₂ (kg)", f"{total_co2:,.0f}")
            c3.metric("Avg fuel cost per run (₪)", f"₪ {avg_leak:,.0f}")

            st.subheader("Trend")
            df_plot = df.copy().sort_values('recorded_at_utc')
            df_plot = df_plot[['recorded_at_utc', 'leakage_ils', 'co2_emissions_kg', 'delta_T_total_h']].dropna()
            df_plot = df_plot.set_index('recorded_at_utc')
            st.line_chart(df_plot)

            st.subheader("Table")
            cols = [
                'recorded_at_utc',
                'data_timestamp_utc',
                'delta_T_total_h',
                'fuel_excess_L',
                'co2_emissions_kg',
                'leakage_ils',
                'traffic_source_id',
                'air_source_id',
                'fuel_source_id',
                'vehicle_count_mode',
                'tomtom_age_s',
            ]
            existing = [c for c in cols if c in df_table.columns]
            st.dataframe(df_table[existing], use_container_width=True)

            csv = df_table[existing].to_csv(index=False)
            st.download_button("Download CSV", data=csv, file_name="monitor_history.csv", mime="text/csv")
    except Exception:
        st.info("History is available but could not be rendered as a table in this environment.")

st.markdown("---")
st.markdown("**Modeling Note:** This model enforces canonical segment schema and attaches provenance to each run.")
st.caption(
    "Data sources: TomTom Traffic Flow (v4) for traffic, Sviva API for air quality, and government sources for fuel price. "
    "Update cadence is ~5 minutes (cache TTL). Vehicle counts are *estimated* from flow/speed and are not an official vehicle counter."
)