"""
traffic_app.py — Ayalon monitoring dashboard (Streamlit UI), methodology v2.

ARCHITECTURAL INVARIANT:
  This UI is STRICTLY READ-ONLY.  It never calls a traffic API.  All traffic
  data is read from SQLite (segment_observations / collection_cycles)
  written by collector.py.

  Values are shown as current only if the measurement they refer to is at
  most health.TRAFFIC_FRESH_S old.  Older values are labelled historical.
  v1 figures (methodology 1.0-freeze) are shown only in the archive, flagged.
"""

import time
from datetime import datetime, timezone

import streamlit as st

from sources.dashboard_data import (
    DIRECTIONS,
    corridor_now,
    corridor_series,
    daily_rows,
    fmt_local,
    iso,
    period_summary,
    segment_state,
)
from sources.health import compute_traffic_health
from sources.history_store import HistoryStore
from sources.official_stats import fetch_official_reference_card
from sources.segment_matcher import load_reference_segments
from methodology_v2 import MAX_HOLD_S, METHODOLOGY_VERSION, parse_ts
from ui_text import t as _t

st.set_page_config(page_title="Ayalon traffic delay (v2)", layout="wide")

LANG_CHOICES = [("עברית", "he"), ("English", "en"), ("العربية", "ar"), ("Русский", "ru")]
lang_display = st.sidebar.selectbox(
    _t("language_label", "he") + " / " + _t("language_label", "en"),
    options=[d for d, _c in LANG_CHOICES],
    index=0,
    key="lang_display",
)
lang = dict(LANG_CHOICES).get(lang_display, "he")


def T(key: str, **kw) -> str:
    s = _t(key, lang)
    return s.format(**kw) if kw else s


if lang in ("he", "ar"):
    st.markdown(
        "<style>.stApp{direction:rtl}.stSidebar{direction:rtl}.stMarkdown,.stText,.stCaption{text-align:right}"
        "[data-testid='stMetricLabel'],[data-testid='stMetricValue']{text-align:right}</style>",
        unsafe_allow_html=True,
    )

st.title(T("app_title"))
st.caption(T("app_subtitle"))

store = HistoryStore(migrate=False)
refs = load_reference_segments()
ref_by_id = {r.segment_id: r for r in refs}
now_ts = time.time()
health = compute_traffic_health(str(store.db_path), now_ts=now_ts)


def _fmt_min_s(seconds):
    if seconds is None:
        return T("no_value")
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def _section_label(seg_id: str) -> str:
    r = ref_by_id.get(seg_id)
    return f"{r.meta.get('from')} → {r.meta.get('to')}" if r else seg_id


def _cause_text(error):
    if not error:
        return None
    if "no_coverage" in error:
        return T("cause_no_coverage")
    if "no traffic provider configured" in error or "not_configured" in error:
        return T("cause_not_configured")
    return None


# ── Status banner (always visible) ─────────────────────────────────────
status = health["status"]
age_min = None if health["age_s"] is None else max(0, int(health["age_s"] // 60))
last_ts_local = fmt_local(health["last_traffic_ts"]) if health["last_traffic_ts"] else T("no_value")
if status == "healthy":
    st.success(T("status_healthy", ok=health["segments_ok"], total=health["segments_total"], time=last_ts_local, age=age_min))
elif status == "partial":
    st.warning(T("status_partial", ok=health["segments_ok"], total=health["segments_total"], time=fmt_local(health["last_cycle_ts"])))
elif status == "stale":
    st.warning(T("status_stale", time=last_ts_local, age=age_min))
elif status == "collector_down":
    st.error(T("status_collector_down", time=fmt_local(health["last_cycle_ts"]) if health["last_cycle_ts"] else T("no_value")))
elif status == "no_data":
    st.error(T("status_no_data", time=last_ts_local))
else:
    st.info(T("status_empty"))
cause = _cause_text(health.get("last_cycle_error"))
if status != "healthy" and (cause or health.get("last_cycle_error")):
    st.caption(f"{T('last_error')}: {cause or health.get('last_cycle_error')}")

st.sidebar.markdown(f"**Status:** `{status}`")
st.sidebar.caption(f"{T('col_measured')}: {last_ts_local}")
st.sidebar.caption(f"Methodology {METHODOLOGY_VERSION}")

tab_now, tab_stats, tab_quality, tab_method = st.tabs([T("tab_now"), T("tab_stats"), T("tab_quality"), T("tab_method")])

state_rows = segment_state(refs, store.latest_observation_per_segment(), store.latest_ok_observation_per_segment(), now_ts)


def _state_table(rows, only_fresh_values: bool):
    import pandas as pd

    out = []
    for r in rows:
        show = r["freshness"] == "current" or not only_fresh_values
        out.append({
            T("col_section"): _section_label(r["segment_id"]),
            T("col_direction"): T("direction_" + r["direction"]),
            T("col_length"): round(r["length_m"]),
            T("col_state"): T("state_" + r["freshness"]),
            T("col_measured"): fmt_local(r["observed_at_utc"]) if r["observed_at_utc"] else T("no_value"),
            T("col_tt"): r["travel_time_s"] if show else None,
            T("col_ff"): r["freeflow_time_s"] if show else None,
            T("col_delay"): r["delay_s"] if show else None,
            T("col_speed"): r["speed_kmh"] if show else None,
            T("col_ffspeed"): r["freeflow_kmh"] if show else None,
            T("col_coverage"): None if r["coverage"] is None or not show else f"{100 * r['coverage']:.0f}%",
        })
    return pd.DataFrame(out)


def _map(rows):
    try:
        import pydeck as pdk
    except ImportError:
        return
    colors = {"current": [0, 140, 70], "stale": [230, 150, 0], "old": [150, 150, 150], "none": [150, 150, 150]}
    data = []
    for r in rows:
        ref = ref_by_id[r["segment_id"]]
        offset = 0.00012 if r["direction"] == "northbound" else -0.00012  # separate carriageways visually
        data.append({
            "path": [[p[1] + offset, p[0]] for p in ref.geometry],
            "color": colors[r["freshness"]],
            "name": f"{_section_label(r['segment_id'])} ({T('direction_' + r['direction'])}) — {T('state_' + r['freshness'])}",
        })
    layer = pdk.Layer("PathLayer", data, get_path="path", get_color="color", width_min_pixels=4, pickable=True)
    view = pdk.ViewState(latitude=32.068, longitude=34.792, zoom=12.3)
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, map_provider="carto", map_style="light",
                             tooltip={"text": "{name}"}))


# ── Tab: now ───────────────────────────────────────────────────────────
with tab_now:
    corr = corridor_now(state_rows)
    if any(r["freshness"] == "current" for r in state_rows):
        for d in DIRECTIONS:
            st.subheader(T("direction_" + d))
            c = corr[d]
            if c is None:
                st.info(T("direction_incomplete"))
                continue
            a, b, cc, dd = st.columns(4)
            a.metric(T("metric_travel_time"), _fmt_min_s(c["travel_time_s"]))
            b.metric(T("metric_freeflow_time"), _fmt_min_s(c["freeflow_time_s"]))
            cc.metric(T("metric_delay"), _fmt_min_s(c["delay_s"]))
            dd.metric(T("metric_speed"), f"{c['speed_kmh']:.0f} km/h" if c["speed_kmh"] else T("no_value"))
        st.subheader(T("sections_header"))
        st.dataframe(_state_table(state_rows, only_fresh_values=True), use_container_width=True, hide_index=True)
    elif any(r["observed_at_utc"] for r in state_rows):
        with st.expander(T("last_valid_header"), expanded=False):
            st.dataframe(_state_table(state_rows, only_fresh_values=False), use_container_width=True, hide_index=True)
    _map(state_rows)


# ── Tab: statistics v2 ─────────────────────────────────────────────────
with tab_stats:
    import pandas as pd

    opts = [("window_24h", 1), ("window_7d", 7), ("window_30d", 30), ("window_all", None)]
    choice = st.selectbox(T("window_label"), [T(k) for k, _d in opts], index=1)
    days = dict((T(k), d) for k, d in opts)[choice]
    end_ts = now_ts
    start_ts = end_ts - days * 86400 if days else end_ts - 3650 * 86400
    obs = store.observations_between(iso(start_ts), iso(end_ts), status="ok")
    if not obs:
        st.info(T("stats_no_data"))
        st.subheader(T("econ_header"))
        st.info(T("econ_unavailable"))
    else:
        if not days:
            start_ts = min(parse_ts(o["observed_at_utc"]) for o in obs)
        last_cycle = store.last_cycle_with_status(["ok", "partial"])
        fuel_price = last_cycle.get("fuel_price_ils_per_l") if last_cycle else None
        summ = period_summary(obs, refs, (start_ts, end_ts), fuel_price)
        for col, d in zip(st.columns(2), DIRECTIONS):
            s = summ["corridor"][d]
            with col:
                st.subheader(T("direction_" + d))
                if s.observed_s <= 0:
                    st.info(T("stats_no_data"))
                    continue
                st.metric(T("stats_mean_delay"), _fmt_min_s(s.mean_delay_s))
                st.metric(T("stats_max_delay"), _fmt_min_s(s.max_delay_s))
                st.metric(T("stats_observed"), f"{s.observed_s / 3600:,.1f} h")
                st.metric(T("stats_coverage"), f"{100 * s.coverage:.0f}%")
                st.metric(T("stats_congested"), f"{s.congested_s / 3600:,.1f} h")
        st.caption(T("stats_caption", hold=int(MAX_HOLD_S // 60)))

        st.subheader(T("chart_header"))
        try:
            import altair as alt

            chart_rows = []
            for d in DIRECTIONS:
                prev = None
                for p in corridor_series(obs, refs, d):
                    if prev is not None and p["observed_at_ts"] - prev > MAX_HOLD_S:
                        # break the line at gaps instead of interpolating across them
                        chart_rows.append({"t": datetime.fromtimestamp(prev + 1, tz=timezone.utc), "delay_s": None, "direction": T("direction_" + d)})
                    chart_rows.append({"t": datetime.fromtimestamp(p["observed_at_ts"], tz=timezone.utc),
                                       "delay_s": max(0.0, p["travel_time_s"] - p["freeflow_time_s"]),
                                       "direction": T("direction_" + d)})
                    prev = p["observed_at_ts"]
            if chart_rows:
                st.altair_chart(
                    alt.Chart(pd.DataFrame(chart_rows)).mark_line().encode(
                        x=alt.X("t:T", title=None), y=alt.Y("delay_s:Q", title="s / veh"), color=alt.Color("direction:N", title=None)
                    ).properties(height=260),
                    use_container_width=True,
                )
        except Exception:
            pass

        st.subheader(T("daily_header"))
        dr = pd.DataFrame(daily_rows(obs, refs, start_ts, end_ts))
        if not dr.empty:
            dr["direction"] = dr["direction"].map(lambda d: T("direction_" + d))
            st.dataframe(dr, use_container_width=True, hide_index=True)
            st.download_button(T("download_csv"), dr.to_csv(index=False), file_name="ayalon_v2_daily.csv", mime="text/csv")

        st.subheader(T("econ_header"))
        econ = summ["economic"]
        if econ is None:
            st.info(T("econ_unavailable"))
        else:
            e1, e2, e3, e4, e5 = st.columns(5)
            e1.metric(T("econ_vh"), f"{econ['vehicle_hours']:,.0f}")
            e2.metric(T("econ_fuel"), f"{econ['fuel_excess_l']:,.0f}")
            e3.metric(T("econ_co2"), f"{econ['co2_kg']:,.0f}")
            e4.metric(T("econ_cost"), T("no_value") if econ["fuel_cost_ils"] is None else f"₪ {econ['fuel_cost_ils']:,.0f}")
            e5.metric(T("econ_time"), f"₪ {econ['time_value_ils']:,.0f}")
            st.caption(T("econ_estimate_note", source=econ["volume_source"], citation=econ["volume_citation"]))

    st.subheader(T("official_card_title"))
    st.caption(T("official_card_subtitle_context_only"))
    official = fetch_official_reference_card(cache_ttl_s=24 * 3600)
    if not bool(official.get("configured")):
        st.info(T("official_not_configured"))
    else:
        left, right = st.columns([2, 1])
        with left:
            if official.get("source_label"):
                st.caption(f"{T('official_source_label')}: {official.get('source_label')}")
            if official.get("report_year") is not None:
                st.caption(f"{T('official_report_year')}: {official.get('report_year')}")
            if official.get("report_url"):
                st.markdown(f"[{official.get('report_url')}]({official.get('report_url')})")
            label = str(official.get("metric_label") or "")
            if label:
                st.caption(f"{T('official_metric_label')}: {T(label) if label.startswith('official_') else label}")
        with right:
            value = float(official.get("value") or 0.0)
            unit = str(official.get("unit") or "")
            shown = f"₪ {value:,.0f} / {T('official_unit_ils_per_year')}" if unit == "ILS_per_year" else f"{value:,.0f} {unit}"
            st.metric(T("official_value_label"), shown)
    st.markdown(T("official_disclaimer_not_comparable"))


# ── Tab: data quality & archive ────────────────────────────────────────
with tab_quality:
    import pandas as pd

    st.subheader(T("quality_periods_header"))
    periods = store.quality_periods()
    if periods:
        st.dataframe(pd.DataFrame([{
            T("col_period"): f"{fmt_local(p['start_utc'])} … {fmt_local(p['end_utc']) if p['end_utc'] else '…'}",
            T("col_severity"): p["severity"],
            T("col_description"): p["description"],
        } for p in periods]), use_container_width=True, hide_index=True)

    st.subheader(T("cycles_header"))
    cycles = store.latest_cycles(50)
    if cycles:
        st.dataframe(pd.DataFrame([{
            "started (IL)": fmt_local(c["started_at_utc"]),
            "status": c["status"],
            "provider": c["provider"],
            "provider_status": c["provider_status"],
            "segments": f"{c['segments_ok']}/{c['segments_total']} (new {c['segments_new']})",
            "error": (c["error"] or "")[:160],
        } for c in cycles]), use_container_width=True, hide_index=True)

    st.subheader(T("v1_header"))
    q = store.v1_quality_summary()
    st.warning(T("v1_body", reuse=q["cache_reuse"]))
    st.caption(T("v1_counts", runs=q["runs"], first=fmt_local(q["first"]), last=fmt_local(q["last"]), reuse=q["cache_reuse"], stale=q["stale_source"]))
    if st.checkbox(T("v1_download"), value=False):
        v1 = store.fetch_runs_df(limit=None)
        st.download_button(T("v1_download"), v1.to_csv(index=False), file_name="ayalon_v1_archive_flagged.csv", mime="text/csv")


# ── Tab: sections & methodology ────────────────────────────────────────
with tab_method:
    import pandas as pd

    st.subheader(T("method_header"))
    st.markdown(T("method_body"))
    st.subheader(T("sections_def_header"))
    st.dataframe(pd.DataFrame([{
        "segment_id": r.segment_id,
        "version": r.segment_version,
        T("col_direction"): T("direction_" + r.direction),
        T("col_section"): _section_label(r.segment_id),
        T("col_length"): round(r.length_m),
        "start": str(r.meta.get("start")),
        "end": str(r.meta.get("end")),
    } for r in refs]), use_container_width=True, hide_index=True)
    st.caption("Geometry © OpenStreetMap contributors, ODbL 1.0")

    st.subheader(T("sources_header"))
    latest = store.latest_cycles(1)
    if latest:
        c = latest[0]
        c1, c2, c3 = st.columns(3)
        c1.metric(T("provider_header"), c.get("provider") or T("no_value"))
        c1.caption(f"{c.get('provider_status')} · {fmt_local(c.get('started_at_utc'))}")
        c2.metric(T("fuel_price_source"), str(c.get("fuel_source_id") or T("no_value")))
        c2.caption(f"{T('price_ils_per_l')}: {c.get('fuel_price_ils_per_l') or T('no_value')}")
        c3.metric(T("air_quality_source"), str(c.get("air_source_id") or T("no_value")))
        c3.caption(f"{T('updated')}: {fmt_local(c.get('air_fetched_at_utc')) if c.get('air_fetched_at_utc') else T('no_value')}")
