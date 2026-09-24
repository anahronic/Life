"""Render the Streamlit dashboard headlessly (streamlit.testing AppTest) in key states."""

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

from sources.history_store import HistoryStore  # noqa: E402
from sources.segment_matcher import load_reference_segments  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "traffic_app.py")


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _run(db, lang="English"):
    at = st_testing.AppTest.from_file(APP, default_timeout=60)
    at.session_state["lang_display"] = lang
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "monitor.sqlite3"
    monkeypatch.setenv("HISTORY_DB_PATH", str(path))
    return HistoryStore(db_path=path)


def _texts(at):
    out = []
    for kind in ("success", "warning", "error", "info", "caption", "markdown"):
        out += [e.value for e in getattr(at, kind)]
    return " ".join(str(x) for x in out)


def test_empty_db_renders(db):
    at = _run(db)
    assert "No v2 measurements recorded yet" in _texts(at)


def test_no_coverage_state(db):
    now = time.time()
    db.record_cycle({"cycle_id": "c1", "methodology_version": "2.0", "started_at_utc": _iso(now - 60), "status": "failed",
                     "segments_total": 6, "segments_ok": 0, "provider": "tomtom_flow_v4", "provider_status": "no_coverage",
                     "error": "tomtom_flow_v4: no_coverage: Point too far from nearest existing segment."})
    at = _run(db)
    txt = _texts(at)
    assert "No real-time traffic measurements are available" in txt
    assert "TomTom no longer serves traffic flow for Israel" in txt
    assert not at.metric or all("Travel time" not in m.label for m in at.metric)
    assert "Not published" in txt  # economic totals withdrawn


def test_live_state_shows_corridor(db):
    now = time.time()
    for r in load_reference_segments():
        tt = r.length_m / 20.0
        ff = r.length_m / 25.0
        db.insert_observation({
            "cycle_id": "c1", "segment_id": r.segment_id, "segment_version": 2, "methodology_version": "2.0",
            "provider": "here_traffic_v7", "provider_snapshot": "s1", "observed_at_utc": _iso(now - 120),
            "fetched_at_utc": _iso(now - 110), "processed_at_utc": _iso(now - 110), "status": "ok", "coverage": 1.0,
            "length_m": r.length_m, "travel_time_s": tt, "freeflow_time_s": ff, "delay_s": tt - ff,
            "speed_kmh": 72.0, "freeflow_kmh": 90.0,
        })
    db.record_cycle({"cycle_id": "c1", "methodology_version": "2.0", "started_at_utc": _iso(now - 110), "status": "ok",
                     "segments_total": 6, "segments_ok": 6, "segments_new": 6, "provider": "here_traffic_v7", "provider_status": "ok"})
    at = _run(db)
    assert "Live: all 6/6 sections measured" in _texts(at)
    labels = [m.label for m in at.metric]
    assert labels.count("Delay per vehicle") == 2  # one per direction
    for lang in ("עברית", "العربية", "Русский"):
        _run(db, lang)


def test_stale_values_not_shown_as_current(db):
    now = time.time()
    r = load_reference_segments()[0]
    db.insert_observation({
        "cycle_id": "c0", "segment_id": r.segment_id, "segment_version": 2, "methodology_version": "2.0",
        "provider": "here_traffic_v7", "provider_snapshot": "old", "observed_at_utc": _iso(now - 3600),
        "fetched_at_utc": _iso(now - 3600), "processed_at_utc": _iso(now - 3600), "status": "ok",
        "length_m": r.length_m, "travel_time_s": 200.0, "freeflow_time_s": 100.0, "delay_s": 100.0,
    })
    db.record_cycle({"cycle_id": "c2", "methodology_version": "2.0", "started_at_utc": _iso(now - 30), "status": "failed",
                     "segments_total": 6, "segments_ok": 0})
    at = _run(db)
    assert "No current measurement" in _texts(at)
    assert all(m.label != "Travel time" for m in at.metric)
