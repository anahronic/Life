"""Provider parsing/HTTP handling and collector cycle semantics (no network)."""

import json
import sqlite3
from pathlib import Path

import pytest
import requests

import collector
from sources import traffic_providers as tp
from sources.history_store import HistoryStore
from sources.segment_matcher import FlowPiece, load_reference_segments, mps

SECRET = "SECRETKEY0123456789abcdefSECRETKEY"
FIX = Path(__file__).parent / "fixtures" / "tomtom_2026-09-15"


@pytest.fixture(scope="module")
def refs():
    return load_reference_segments()


class FakeResp:
    def __init__(self, status, body, headers=None):
        self.status_code = status
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.headers = headers or {}

    def json(self):
        return self._body if not isinstance(self._body, str) else json.loads(self._body)


def _here_body(refs, confidence=0.9, speed=15.0, ff=25.0, direction=None, subsegments=False):
    """SYNTHETIC body following the documented HERE v7 /flow schema (no real HERE data)."""
    results = []
    for r in refs:
        if direction and r.direction != direction:
            continue
        cf = {"speed": speed, "speedUncapped": speed, "freeFlow": ff, "jamFactor": 3.0, "confidence": confidence, "traversability": "open"}
        if subsegments:
            half = r.length_m / 2
            cf["subSegments"] = [
                {"length": half, "speed": speed, "freeFlow": ff, "jamFactor": 3.0, "confidence": confidence, "traversability": "open"},
                {"length": half, "speed": ff, "freeFlow": ff, "jamFactor": 0.0, "confidence": confidence, "traversability": "open"},
            ]
        results.append({
            "location": {"description": r.segment_id, "length": r.length_m,
                         "shape": {"links": [{"points": [{"lat": p[0], "lng": p[1]} for p in r.geometry], "length": r.length_m, "functionalClass": 1}]}},
            "currentFlow": cf,
        })
    return {"sourceUpdated": "2026-09-24T12:00:00Z", "results": results}


# ── HERE parser ────────────────────────────────────────────────────────

def test_here_parser_confidence_threshold(refs):
    pieces, dropped = tp.parse_here_flow(_here_body(refs, confidence=0.7))
    assert pieces == [] and dropped == 6  # 0.7 = historical speeds, not real time
    pieces, dropped = tp.parse_here_flow(_here_body(refs, confidence=0.71))
    assert len(pieces) == 6 and dropped == 0


def test_here_parser_subsegments(refs):
    pieces, _ = tp.parse_here_flow(_here_body(refs, subsegments=True))
    assert len(pieces) == 12
    assert {p.speed_mps for p in pieces} == {15.0, 25.0}


def test_here_fetch_ok_and_key_not_leaked(monkeypatch, refs):
    seen = {}

    def fake_get(url, params, headers, timeout):
        seen.update(params)
        return FakeResp(200, _here_body(refs), {"X-Request-Id": "rid-1"})

    monkeypatch.setattr(tp.requests, "get", fake_get)
    res = tp.fetch_here(SECRET, refs)
    assert res.status == "ok" and len(res.pieces) == 6
    assert seen["apiKey"] == SECRET and seen["functionalClasses"] == "1,2"
    assert res.source_updated == "2026-09-24T12:00:00Z"
    assert SECRET not in json.dumps(res.summary())


def test_here_auth_error_scrubbed(monkeypatch, refs):
    monkeypatch.setattr(tp.requests, "get", lambda *a, **k: FakeResp(401, f"invalid apiKey {SECRET}"))
    res = tp.fetch_here(SECRET, refs)
    assert res.status == "auth_error"
    assert SECRET not in json.dumps(res.summary())


def test_timeout_retried_then_network_error(monkeypatch, refs):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise requests.Timeout(f"timed out key={SECRET}")

    monkeypatch.setattr(tp.requests, "get", boom)
    monkeypatch.setattr(tp.time, "sleep", lambda s: None)
    res = tp.fetch_here(SECRET, refs)
    assert res.status == "network_error"
    assert len(calls) == tp.HTTP_RETRIES + 1
    assert SECRET not in json.dumps(res.summary())


def test_tomtom_no_coverage_stops_after_first_request(monkeypatch, refs):
    calls = []
    body = '{"error":"Point too far from nearest existing segment.","httpStatusCode":400}'

    def fake_get(url, params, headers, timeout):
        calls.append(params["point"])
        return FakeResp(400, body)

    monkeypatch.setattr(tp.requests, "get", fake_get)
    res = tp.fetch_tomtom(SECRET, refs)
    assert res.status == "no_coverage"
    assert len(calls) == 1
    assert all("key=" not in a.url for a in res.attempts)


def test_tomtom_real_response_parsed_and_skips_covered_segments(monkeypatch, refs):
    body = json.loads(next(FIX.glob("*arlozorov*.json")).read_text())["data"]["raw"]["response"]
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append(params["point"])
        return FakeResp(200, body, {"Tracking-ID": f"t{len(calls)}"})

    monkeypatch.setattr(tp.requests, "get", fake_get)
    res = tp.fetch_tomtom(SECRET, refs)
    assert res.status == "ok"
    # the Ayalon-North piece covers 2 northbound sections, so those midpoints are not queried again
    assert len(calls) == 4


# ── collector cycle semantics ──────────────────────────────────────────

def _result(refs, direction=None, status="ok", snapshot="2026-09-24T12:00:00Z"):
    r = tp.ProviderResult(provider="here_traffic_v7", status=status, fetched_at="2026-09-24T12:00:05Z",
                          source_updated=snapshot, response_id="rid")
    if status == "ok":
        r.pieces, _ = tp.parse_here_flow(_here_body(refs, direction=direction))
        r.raw_gz, r.raw_sha256 = tp._pack_raw({"x": snapshot})
    else:
        r.error = "Point too far from nearest existing segment."
    return r


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "_fetch_fuel", lambda: {"price_ils_per_l": 7.5, "source_id": "test"})
    monkeypatch.setattr(collector, "_fetch_air", lambda: {})
    return HistoryStore(db_path=tmp_path / "m.sqlite3")


def _count(store, sql):
    with sqlite3.connect(store.db_path) as con:
        return con.execute(sql).fetchone()[0]


def test_full_cycle_ok(store, refs):
    out = collector.collect_once(store, refs, fetcher=lambda r: (_result(r), []))
    assert out["status"] == "ok" and out["segments_ok"] == 6 and out["segments_new"] == 6
    assert _count(store, "SELECT count(*) FROM segment_observations WHERE status='ok'") == 6
    row = store.latest_ok_observation_per_segment()["ayalon_n_arlozorov_rokach"]
    assert row["fetched_at_utc"] == "2026-09-24T12:00:05Z"
    assert row["observed_at_utc"] == row["source_updated_utc"] == "2026-09-24T12:00:00Z"
    assert row["processed_at_utc"] and row["recorded_at_utc"]
    assert row["delay_s"] == pytest.approx(row["travel_time_s"] - row["freeflow_time_s"])


def test_same_snapshot_is_not_recorded_twice(store, refs):
    collector.collect_once(store, refs, fetcher=lambda r: (_result(r), []))
    out = collector.collect_once(store, refs, fetcher=lambda r: (_result(r), []))
    assert out["segments_new"] == 0
    assert _count(store, "SELECT count(*) FROM segment_observations") == 6
    assert all(s.endswith("snapshot_already_recorded") for s in out["segments"].values())


def test_partial_cycle(store, refs):
    out = collector.collect_once(store, refs, fetcher=lambda r: (_result(r, direction="northbound"), []))
    assert out["status"] == "partial" and out["segments_ok"] == 3
    statuses = out["segments"]
    assert all(v == "ok" for k, v in statuses.items() if k.startswith("ayalon_n_"))
    assert all(v == "no_data" for k, v in statuses.items() if k.startswith("ayalon_s_"))


def test_provider_failure_writes_no_measurement(store, refs):
    collector.collect_once(store, refs, fetcher=lambda r: (_result(r), []))
    out = collector.collect_once(store, refs, fetcher=lambda r: (_result(r, status="no_coverage"), []))
    assert out["status"] == "failed" and out["segments_ok"] == 0
    assert "no_coverage" in out["error"]
    assert _count(store, "SELECT count(*) FROM segment_observations") == 6  # unchanged
    assert _count(store, "SELECT count(*) FROM collection_cycles") == 2


def test_no_provider_configured(store, refs, monkeypatch):
    monkeypatch.delenv("HERE_API_KEY", raising=False)
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    monkeypatch.setattr(collector.SecureConfig, "_get_value", staticmethod(lambda k: None))
    out = collector.collect_once(store, refs)
    assert out["status"] == "failed"
    assert "no traffic provider configured" in out["error"]
