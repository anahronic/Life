"""v1 -> v2 migration: verified backup, v1 values untouched, flags correct, idempotent."""

import sqlite3

from sources.history_store import HistoryStore


def _v1_db(path):
    store = HistoryStore(db_path=path, migrate=False)
    rows = [
        ("2026-09-15T09:37:00Z", "2026-09-15T09:37:00Z", 1.0, "a"),
        ("2026-09-15T09:42:43Z", "2026-09-15T09:42:42Z", 1.0, "b"),
        ("2026-09-15T09:47:43Z", "2026-09-15T09:42:42Z", 301.0, "c"),   # cache re-use
        ("2026-09-15T10:42:43Z", "2026-09-15T09:42:42Z", 3601.0, "d"),  # cache re-use + stale
    ]
    with sqlite3.connect(path) as con:
        for rec, fetched, age, rid in rows:
            con.execute(
                "INSERT INTO runs (recorded_at_utc, pipeline_run_id, traffic_source_id, delta_T_total_h, leakage_ils, tomtom_fetched_at, tomtom_age_s) "
                "VALUES (?,?,?,?,?,?,?)", (rec, rid, "tomtom_flow_v4", 866.26, 8025.06, fetched, age))
    return store


def test_migration(tmp_path):
    path = tmp_path / "monitor.sqlite3"
    _v1_db(path)
    store = HistoryStore(db_path=path, migrate=False)
    info = store.migrate()
    assert info["migrated_to"] == 2
    b = info["backup"]
    assert b["integrity"] == "ok" and b["runs"] == 4 and len(b["sha256"]) == 64
    with sqlite3.connect(b["path"]) as con:  # backup is the untouched v1 DB
        assert con.execute("PRAGMA user_version").fetchone()[0] == 0
        assert "quality_flags" not in {r[1] for r in con.execute("PRAGMA table_info(runs)")}
    with sqlite3.connect(path) as con:
        flags = dict(con.execute("SELECT pipeline_run_id, quality_flags FROM runs"))
        vals = con.execute("SELECT DISTINCT delta_T_total_h, leakage_ils FROM runs").fetchall()
    assert flags == {
        "a": "v1_method_defect",
        "b": "v1_method_defect",
        "c": "v1_method_defect,cache_reuse",
        "d": "v1_method_defect,cache_reuse,stale_source",
    }
    assert vals == [(866.26, 8025.06)]  # original values untouched
    assert store.schema_version() == 2
    assert {p["period_id"] for p in store.quality_periods()} >= {"v1_methodology", "tomtom_israel_coverage_removed"}
    assert store.migrate() is None  # idempotent
    assert store.v1_quality_summary()["cache_reuse"] == 2


def test_fresh_db_migrates_without_backup(tmp_path):
    store = HistoryStore(db_path=tmp_path / "new.sqlite3")
    assert store.schema_version() == 2
    assert not (tmp_path / "backups").exists()
