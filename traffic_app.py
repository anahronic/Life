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

LANG_CHOICES = [
    ("עברית", "he"),
    ("English", "en"),
    ("العربية", "ar"),
    ("Русский", "ru"),
]
_lang_display_to_code = {d: c for d, c in LANG_CHOICES}

_I18N = {
    "he": {
        "app_title": "מודל השפעה פיזיקלית בזמן אמת — איילון",
        "app_subtitle": "**גרסה:** 1.0 (Freeze) | **שכבה:** L5 — תחבורה / אמת פיזיקלית | **תחום:** כביש 20 (איילון), ישראל",
        "language_label": "שפה",
        "sidebar_data_refresh": "נתונים ורענון",
        "auto_refresh": "רענון אוטומטי כל 5 דקות",
        "loss_display_header": "תצוגת הפסדים",
        "loss_display_label": "הצג הפסדים כ",
        "history_window_label": "חלון היסטוריה",
        "system_health": "בריאות מערכת",
        "traffic_mode": "מצב תנועה",
        "traffic_mode_help": "Flow דורש TOMTOM_API_KEY (סוד בצד השרת). Sample הוא סינתטי לדמו/בדיקות.",
        "tab_dashboard": "לוח מחוונים",
        "tab_history": "היסטוריה וסטטיסטיקה",
        "tab_sources": "מקורות ובריאות",
    },
    "en": {
        "app_title": "Ayalon Real-Time Physical Impact Model — Monitor",
        "app_subtitle": "**Version:** 1.0 (Freeze) | **Layer:** L5 — Transport / Physical Truth | **Scope:** Highway 20 (Ayalon), Israel",
        "language_label": "Language",
        "sidebar_data_refresh": "Data & Refresh",
        "auto_refresh": "Auto-refresh every 5 minutes",
        "loss_display_header": "Loss Display",
        "loss_display_label": "Show losses as",
        "history_window_label": "History window",
        "system_health": "System health",
        "traffic_mode": "Traffic mode",
        "traffic_mode_help": "Flow requires TOMTOM_API_KEY (server-side secret). Sample is synthetic for demos/testing.",
        "tab_dashboard": "Dashboard",
        "tab_history": "History & Stats",
        "tab_sources": "Sources & Health",
    },
    "ar": {
        "app_title": "نموذج الأثر الفيزيائي اللحظي — أيالون",
        "app_subtitle": "**الإصدار:** 1.0 (Freeze) | **الطبقة:** L5 — النقل / الحقيقة الفيزيائية | **النطاق:** الطريق السريع 20 (أيالون)، إسرائيل",
        "language_label": "اللغة",
        "sidebar_data_refresh": "البيانات والتحديث",
        "auto_refresh": "تحديث تلقائي كل 5 دقائق",
        "loss_display_header": "عرض الخسائر",
        "loss_display_label": "اعرض الخسائر كـ",
        "history_window_label": "نافذة السجل",
        "system_health": "صحة النظام",
        "traffic_mode": "وضع المرور",
        "traffic_mode_help": "وضع Flow يتطلب TOMTOM_API_KEY (سر على الخادم). Sample بيانات اصطناعية للعرض/الاختبار.",
        "tab_dashboard": "لوحة التحكم",
        "tab_history": "السجل والإحصاءات",
        "tab_sources": "المصادر والصحة",
    },
    "ru": {
        "app_title": "Ayalon — монитор физического воздействия",
        "app_subtitle": "**Версия:** 1.0 (Freeze) | **Слой:** L5 — Транспорт / Физическая истина | **Область:** трасса 20 (Аялон), Израиль",
        "language_label": "Язык",
        "sidebar_data_refresh": "Данные и обновление",
        "auto_refresh": "Автообновление каждые 5 минут",
        "loss_display_header": "Отображение потерь",
        "loss_display_label": "Показывать потери как",
        "history_window_label": "Окно истории",
        "system_health": "Состояние системы",
        "traffic_mode": "Режим трафика",
        "traffic_mode_help": "Flow требует TOMTOM_API_KEY (секрет на сервере). Sample — синтетика для демо/тестов.",
        "tab_dashboard": "Дашборд",
        "tab_history": "История и статистика",
        "tab_sources": "Источники и здоровье",
    },
}


def _t(key: str, lang: str) -> str:
    table = _I18N.get((lang or "en").lower(), _I18N["en"])
    return str(table.get(key, _I18N["en"].get(key, key)))


# Language selector (above Data & Refresh)
default_lang_display = LANG_CHOICES[0][0]  # Hebrew
lang_display = st.sidebar.selectbox(
    _t("language_label", "he") + " / " + _t("language_label", "en"),
    options=[d for d, _c in LANG_CHOICES],
    index=0,
    key="lang_display",
)
lang = _lang_display_to_code.get(lang_display, "he")

st.title(_t("app_title", lang))
st.markdown(_t("app_subtitle", lang))

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


def _history_window_seconds(choice: str) -> int | None:
    mapping = {
        "Last 1 hour": 3600,
        "Last 24 hours": 24 * 3600,
        "Last 7 days": 7 * 24 * 3600,
        "Last 30 days": 30 * 24 * 3600,
        "All time": None,
    }
    return mapping.get(choice)


def _compute_aggregates_from_history(df, window_s: int | None):
    """Return (df_window, totals_dict, duration_hours) using recorded_at_utc."""
    import pandas as pd  # type: ignore

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None, {}, 0.0

    d = df.copy()
    d['recorded_at_utc'] = pd.to_datetime(d['recorded_at_utc'], errors='coerce', utc=True)
    d = d.dropna(subset=['recorded_at_utc'])
    if d.empty:
        return None, {}, 0.0

    now = pd.Timestamp.utcnow().tz_localize('UTC')
    if window_s is not None:
        start = now - pd.Timedelta(seconds=int(window_s))
        d = d[d['recorded_at_utc'] >= start]
        if d.empty:
            return None, {}, 0.0

    d = d.sort_values('recorded_at_utc')
    duration_h = (d['recorded_at_utc'].max() - d['recorded_at_utc'].min()).total_seconds() / 3600.0
    duration_h = max(duration_h, 1e-6)

    def total(col: str) -> float:
        if col not in d.columns:
            return 0.0
        s = pd.to_numeric(d[col], errors='coerce').dropna()
        return float(s.sum()) if not s.empty else 0.0

    totals = {
        'delta_T_total_h': total('delta_T_total_h'),
        'fuel_excess_L': total('fuel_excess_L'),
        'co2_emissions_kg': total('co2_emissions_kg'),
        'leakage_ils': total('leakage_ils'),
    }
    return d, totals, duration_h

# Controls
st.sidebar.header(_t("sidebar_data_refresh", lang))
api_key = SecureConfig.get_tomtom_api_key()
auto_refresh = st.sidebar.checkbox(_t("auto_refresh", lang), value=True)

st.sidebar.subheader(_t("loss_display_header", lang))
loss_display = st.sidebar.selectbox(
    _t("loss_display_label", lang),
    options=["Per hour", "Per day", "Per year", "Total (window)"],
    index=1,
)
history_window_choice = st.sidebar.selectbox(
    _t("history_window_label", lang),
    options=["Last 1 hour", "Last 24 hours", "Last 7 days", "Last 30 days", "All time"],
    index=1,
)

# Public-friendly system status (no secrets)
st.sidebar.info(f"{_t('system_health', lang)}: {get_quick_status()}")

# Traffic mode selection
default_sample = api_key is None and SecureConfig.get_enable_sample_mode()
traffic_mode = "sample" if default_sample else "flow"
traffic_mode = st.sidebar.selectbox(
    _t("traffic_mode", lang),
    options=["flow", "sample"],
    index=0 if traffic_mode == "flow" else 1,
    help=_t("traffic_mode_help", lang),
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

tab_dashboard, tab_history, tab_sources = st.tabs([
    _t("tab_dashboard", lang),
    _t("tab_history", lang),
    _t("tab_sources", lang),
])

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

banner = normalization_banner_text(vehicle_count_mode, lang=lang)
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
        # Use monitoring history to scale numbers for non-technical users (per hour/day/year/total)
        totals = None
        duration_h = 0.0
        try:
            import pandas as pd  # type: ignore

            df_hist = history.fetch_runs_df(limit=5000)
            window_s = _history_window_seconds(history_window_choice)
            _dfw, totals, duration_h = _compute_aggregates_from_history(df_hist, window_s)
        except Exception:
            totals = None

        def scale(total_value: float) -> float:
            if loss_display == "Total (window)":
                return float(total_value)
            rate_per_h = float(total_value) / float(duration_h or 1e-6)
            if loss_display == "Per hour":
                return rate_per_h
            if loss_display == "Per day":
                return rate_per_h * 24.0
            if loss_display == "Per year":
                return rate_per_h * 24.0 * 365.0
            return float(total_value)

        use_history = isinstance(totals, dict) and bool(totals)
        colA, colB, colC, colD = st.columns(4)
        if use_history:
            colA.metric(f"Vehicle-Hours ({loss_display})", f"{scale(totals.get('delta_T_total_h', 0.0)):,.2f} h")
            colB.metric(f"CO₂ ({loss_display})", f"{scale(totals.get('co2_emissions_kg', 0.0)):,.2f} kg")
            colC.metric(f"Excess fuel ({loss_display})", f"{scale(totals.get('fuel_excess_L', 0.0)):,.2f} L")
            colD.metric(f"Fuel cost ({loss_display})", f"₪ {scale(totals.get('leakage_ils', 0.0)):,.2f}")
            if loss_display != "Total (window)":
                st.caption(
                    f"Extrapolated from {history_window_choice}. Observed duration: {duration_h:.2f} hours."
                )
        else:
            colA.metric("Vehicle-Hours (delay)", f"{delta_T:,.2f} h")
            colB.metric("CO₂ from excess fuel", f"{results['co2_emissions_kg']:,.2f} kg")
            colC.metric("Excess fuel burned", f"{results['fuel_excess_L']:,.2f} L")
            colD.metric("Direct fuel cost", f"₪ {results['leakage_ils']:,.2f}")

        st.caption(
            f"Indicative time-value loss (₪): ₪ {time_value_ils:,.0f} "
            f"(assumes ₪{float(getattr(model,'Value_of_Time_ILS_per_h',62.5)):.2f}/vehicle-hour)"
        )

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
            window_s = _history_window_seconds(history_window_choice)
            dfw, totals, duration_h = _compute_aggregates_from_history(df, window_s)

            # Latest first for table readability
            df_table = df.copy()
            df_table = df_table.sort_values('recorded_at_utc', ascending=False)

            # Summary
            st.subheader("Summary")
            total_leak_all = float(df_table['leakage_ils'].dropna().sum()) if 'leakage_ils' in df_table else 0.0
            total_co2_all = float(df_table['co2_emissions_kg'].dropna().sum()) if 'co2_emissions_kg' in df_table else 0.0
            avg_leak_all = float(df_table['leakage_ils'].dropna().mean()) if 'leakage_ils' in df_table and df_table['leakage_ils'].notna().any() else 0.0

            # Window-based scaling
            window_leak = float((totals or {}).get('leakage_ils', 0.0))
            window_co2 = float((totals or {}).get('co2_emissions_kg', 0.0))
            window_delay_h = float((totals or {}).get('delta_T_total_h', 0.0))
            rate_per_h = (window_leak / duration_h) if duration_h else 0.0
            leak_per_day = rate_per_h * 24.0
            leak_per_year = rate_per_h * 24.0 * 365.0

            c1, c2, c3 = st.columns(3)
            c1.metric("Total fuel cost (all time, ₪)", f"₪ {total_leak_all:,.0f}")
            c2.metric("Total CO₂ (all time, kg)", f"{total_co2_all:,.0f}")
            c3.metric("Avg fuel cost per run (all time, ₪)", f"₪ {avg_leak_all:,.0f}")

            st.caption(f"Selected window: {history_window_choice} | Observed duration: {duration_h:.2f} hours")
            w1, w2, w3, w4 = st.columns(4)
            w1.metric(f"Fuel cost (Total window, ₪)", f"₪ {window_leak:,.0f}")
            w2.metric(f"Fuel cost (Per hour, ₪/h)", f"₪ {rate_per_h:,.0f}")
            w3.metric(f"Fuel cost (Per day, ₪/day)", f"₪ {leak_per_day:,.0f}")
            w4.metric(f"Fuel cost (Per year, ₪/yr)", f"₪ {leak_per_year:,.0f}")

            st.caption(f"Window totals: delay={window_delay_h:,.1f} vehicle-hours, CO₂={window_co2:,.0f} kg")

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