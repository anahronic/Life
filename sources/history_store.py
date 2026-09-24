import gzip
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 2

# Known data-quality periods (UTC).  Documented in docs/ayalon_v2_methodology.md.
KNOWN_PERIODS = [
    {
        "period_id": "v1_methodology",
        "start_utc": "2026-01-08T00:00:00Z",
        "end_utc": "2026-09-16T09:39:39Z",
        "scope": "runs",
        "severity": "invalid",
        "code": "v1_method_defect",
        "description": (
            "Methodology 1.0-freeze: provider travel time of a 9-18 km TomTom segment compared with the "
            "free-flow time of a 0.4-1.1 km polyline window (~858 vehicle-hours reported at free flow); "
            "vehicle counts = speed x 25 veh/km (not measured); probe 'la_guardia' measured Route 44, not "
            "Ayalon; probes 'ha_shalom' and 'arlozorov' reused one TomTom measurement; southbound Ayalon "
            "never measured. Values are not a measurement of congestion losses."
        ),
    },
    {
        "period_id": "tomtom_cache_reuse_2026-09-15",
        "start_utc": "2026-09-15T09:42:43Z",
        "end_utc": "2026-09-16T09:39:39Z",
        "scope": "runs",
        "severity": "invalid",
        "code": "cache_reuse",
        "description": "281 runs re-recorded the TomTom response fetched 2026-09-15T09:42:42Z after the API started returning HTTP 400.",
    },
    {
        "period_id": "tomtom_israel_coverage_removed",
        "start_utc": "2026-09-15T09:42:43Z",
        "end_utc": None,
        "scope": "source",
        "severity": "no_data",
        "code": "provider_no_coverage",
        "description": (
            "TomTom Traffic API returns 'Point too far from nearest existing segment' for every point in Israel "
            "(Amsterdam control point: HTTP 200). Israel was removed from TomTom's Traffic API market coverage page "
            "(last edit 2026-09-15; present in the 2026-06-06 archive). No real-time Ayalon measurements exist for this period."
        ),
    },
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_db_path() -> Path:
    # Local persistent store; safe to ignore in git.
    env = os.getenv("HISTORY_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data" / "monitor.sqlite3"


@dataclass
class HistoryRow:
    recorded_at_utc: str
    data_timestamp_utc: Optional[str]
    pipeline_run_id: Optional[str]
    traffic_source_id: Optional[str]
    air_source_id: Optional[str]
    fuel_source_id: Optional[str]
    vehicle_count_mode: Optional[str]
    delta_T_total_h: Optional[float]
    co2_emissions_kg: Optional[float]
    fuel_excess_L: Optional[float]
    leakage_ils: Optional[float]
    tomtom_fetched_at: Optional[str]
    tomtom_age_s: Optional[float]
    air_fetched_at: Optional[str]
    fuel_fetched_at: Optional[str]


_V2_DDL = [
    """
    CREATE TABLE IF NOT EXISTS collection_cycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cycle_id TEXT NOT NULL UNIQUE,
        methodology_version TEXT NOT NULL,
        started_at_utc TEXT NOT NULL,
        finished_at_utc TEXT,
        provider TEXT,
        provider_status TEXT,
        status TEXT NOT NULL,              -- ok | partial | failed
        segments_total INTEGER NOT NULL,
        segments_ok INTEGER NOT NULL,
        segments_new INTEGER NOT NULL DEFAULT 0,
        source_updated_utc TEXT,
        fetched_at_utc TEXT,
        response_id TEXT,
        raw_sha256 TEXT,
        error TEXT,
        diagnostics_json TEXT,
        fuel_price_ils_per_l REAL,
        fuel_source_id TEXT,
        fuel_fetched_at_utc TEXT,
        air_source_id TEXT,
        air_fetched_at_utc TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cycles_started ON collection_cycles(started_at_utc)",
    """
    CREATE TABLE IF NOT EXISTS segment_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cycle_id TEXT NOT NULL,
        segment_id TEXT NOT NULL,
        segment_version INTEGER NOT NULL,
        methodology_version TEXT NOT NULL,
        provider TEXT NOT NULL,
        provider_snapshot TEXT NOT NULL,   -- sourceUpdated (HERE) or HTTP response id (TomTom)
        observed_at_utc TEXT NOT NULL,     -- time the measurement refers to
        source_updated_utc TEXT,           -- provider's own data timestamp, if given
        fetched_at_utc TEXT NOT NULL,      -- HTTP response received
        processed_at_utc TEXT NOT NULL,    -- matching/computation finished
        recorded_at_utc TEXT NOT NULL,     -- row written
        status TEXT NOT NULL,              -- ok | insufficient_coverage | closed | no_data
        coverage REAL,
        length_m REAL,
        travel_time_s REAL,
        freeflow_time_s REAL,
        delay_s REAL,
        speed_kmh REAL,
        freeflow_kmh REAL,
        confidence REAL,
        jam_factor REAL,
        mean_offset_m REAL,
        max_offset_m REAL,
        piece_ids TEXT,
        raw_sha256 TEXT,
        UNIQUE(segment_id, segment_version, provider, provider_snapshot)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_obs_segment_time ON segment_observations(segment_id, observed_at_utc)",
    """
    CREATE TABLE IF NOT EXISTS raw_responses (
        sha256 TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        fetched_at_utc TEXT NOT NULL,
        body_gzip BLOB NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS data_quality_periods (
        period_id TEXT PRIMARY KEY,
        start_utc TEXT NOT NULL,
        end_utc TEXT,
        scope TEXT NOT NULL,
        severity TEXT NOT NULL,
        code TEXT NOT NULL,
        description TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at_utc TEXT NOT NULL,
        note TEXT
    )
    """,
]


class HistoryStore:
    def __init__(self, db_path: Optional[Path] = None, *, migrate: bool = True):
        self.db_path = Path(db_path) if db_path else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        if migrate:
            self.migrate()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at_utc TEXT NOT NULL,
                    data_timestamp_utc TEXT,
                    pipeline_run_id TEXT,
                    traffic_source_id TEXT,
                    air_source_id TEXT,
                    fuel_source_id TEXT,
                    vehicle_count_mode TEXT,
                    delta_T_total_h REAL,
                    co2_emissions_kg REAL,
                    fuel_excess_L REAL,
                    leakage_ils REAL,
                    tomtom_fetched_at TEXT,
                    tomtom_age_s REAL,
                    air_fetched_at TEXT,
                    fuel_fetched_at TEXT,
                    UNIQUE(pipeline_run_id)
                )
                """
            )

    # ── schema migration ───────────────────────────────────────────────

    def schema_version(self) -> int:
        with self._connect() as con:
            return int(con.execute("PRAGMA user_version").fetchone()[0])

    def backup_to(self, dest: Path) -> Dict[str, Any]:
        """Consistent online backup (sqlite backup API) + sha256 of the copy."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(str(self.db_path), timeout=30)
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        h = hashlib.sha256(dest.read_bytes()).hexdigest()
        with sqlite3.connect(f"file:{dest}?mode=ro", uri=True) as chk:
            ok = chk.execute("PRAGMA integrity_check").fetchone()[0]
            runs = chk.execute("SELECT count(*) FROM runs").fetchone()[0]
        return {"path": str(dest), "sha256": h, "integrity": ok, "runs": runs}

    def migrate(self) -> Optional[Dict[str, Any]]:
        """Idempotent migration to SCHEMA_VERSION.  Never deletes or rewrites v1 values.

        v1 -> v2: adds methodology/quality columns to `runs` (values are
        flagged, not changed), creates the v2 tables and registers the known
        data-quality periods.  A verified backup is taken first.
        """
        if self.schema_version() >= SCHEMA_VERSION:
            return None
        backup = None
        with self._connect() as con:
            has_rows = con.execute("SELECT count(*) FROM runs").fetchone()[0] > 0
        if has_rows:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = self.backup_to(self.db_path.parent / "backups" / f"monitor.pre_v2.{stamp}.sqlite3")
            if backup["integrity"] != "ok":
                raise RuntimeError(f"backup integrity check failed: {backup}")
        with self._connect() as con:
            cols = {r[1] for r in con.execute("PRAGMA table_info(runs)")}
            for col in ("methodology_version", "quality_flags", "quality_note"):
                if col not in cols:
                    con.execute(f"ALTER TABLE runs ADD COLUMN {col} TEXT")
            for ddl in _V2_DDL:
                con.execute(ddl)
            # Flag v1 rows.  Every v1 row carries the methodology defect;
            # rows re-using an earlier TomTom response are cache re-use.
            con.execute("CREATE INDEX IF NOT EXISTS idx_runs_tomtom_fetched ON runs(tomtom_fetched_at, id)")
            con.execute("UPDATE runs SET methodology_version = '1.0-freeze' WHERE methodology_version IS NULL")
            con.execute(
                """
                UPDATE runs SET quality_flags = 'v1_method_defect' ||
                    CASE WHEN id > (SELECT min(r2.id) FROM runs r2 WHERE r2.tomtom_fetched_at = runs.tomtom_fetched_at)
                         THEN ',cache_reuse' ELSE '' END ||
                    CASE WHEN tomtom_age_s > 600 THEN ',stale_source' ELSE '' END
                WHERE quality_flags IS NULL
                """
            )
            con.execute(
                "UPDATE runs SET quality_note = 'Not a valid congestion measurement; see data_quality_periods.v1_methodology' "
                "WHERE quality_note IS NULL"
            )
            for p in KNOWN_PERIODS:
                con.execute(
                    "INSERT OR REPLACE INTO data_quality_periods VALUES (?,?,?,?,?,?,?)",
                    (p["period_id"], p["start_utc"], p["end_utc"], p["scope"], p["severity"], p["code"], p["description"]),
                )
            con.execute(
                "INSERT OR REPLACE INTO schema_migrations VALUES (?,?,?)",
                (SCHEMA_VERSION, _utc_now_iso(), json.dumps({"backup": backup}) if backup else None),
            )
            con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return {"migrated_to": SCHEMA_VERSION, "backup": backup}

    # ── v1 (legacy, read-only in production) ───────────────────────────

    def record_run(self, *, results: Dict[str, Any], tomtom_data: Dict[str, Any], aq_data: Dict[str, Any], fuel_data: Dict[str, Any], tomtom_age_s: Optional[float]) -> None:
        row = HistoryRow(
            recorded_at_utc=_utc_now_iso(),
            data_timestamp_utc=results.get("data_timestamp_utc"),
            pipeline_run_id=results.get("pipeline_run_id"),
            traffic_source_id=(results.get("data_source_ids") or {}).get("traffic"),
            air_source_id=(results.get("data_source_ids") or {}).get("air"),
            fuel_source_id=(results.get("data_source_ids") or {}).get("fuel"),
            vehicle_count_mode=results.get("vehicle_count_mode"),
            delta_T_total_h=float(results.get("delta_T_total_h")) if results.get("delta_T_total_h") is not None else None,
            co2_emissions_kg=float(results.get("co2_emissions_kg")) if results.get("co2_emissions_kg") is not None else None,
            fuel_excess_L=float(results.get("fuel_excess_L")) if results.get("fuel_excess_L") is not None else None,
            leakage_ils=float(results.get("leakage_ils")) if results.get("leakage_ils") is not None else None,
            tomtom_fetched_at=tomtom_data.get("fetched_at"),
            tomtom_age_s=float(tomtom_age_s) if tomtom_age_s is not None else None,
            air_fetched_at=aq_data.get("fetched_at"),
            fuel_fetched_at=fuel_data.get("fetched_at_utc") or fuel_data.get("fetched_at"),
        )

        with self._connect() as con:
            con.execute(
                """
                INSERT OR IGNORE INTO runs (
                    recorded_at_utc,
                    data_timestamp_utc,
                    pipeline_run_id,
                    traffic_source_id,
                    air_source_id,
                    fuel_source_id,
                    vehicle_count_mode,
                    delta_T_total_h,
                    co2_emissions_kg,
                    fuel_excess_L,
                    leakage_ils,
                    tomtom_fetched_at,
                    tomtom_age_s,
                    air_fetched_at,
                    fuel_fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row.recorded_at_utc,
                    row.data_timestamp_utc,
                    row.pipeline_run_id,
                    row.traffic_source_id,
                    row.air_source_id,
                    row.fuel_source_id,
                    row.vehicle_count_mode,
                    row.delta_T_total_h,
                    row.co2_emissions_kg,
                    row.fuel_excess_L,
                    row.leakage_ils,
                    row.tomtom_fetched_at,
                    row.tomtom_age_s,
                    row.air_fetched_at,
                    row.fuel_fetched_at,
                ),
            )

    def fetch_runs(self, limit: Optional[int] = 2000) -> List[Dict[str, Any]]:
        with self._connect() as con:
            if limit is None:
                rows = con.execute("SELECT * FROM runs ORDER BY recorded_at_utc DESC").fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM runs ORDER BY recorded_at_utc DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
        return [dict(r) for r in rows]

    def fetch_runs_df(self, limit: Optional[int] = 2000):
        # pandas is a transitive dependency of streamlit; keep optional.
        rows = self.fetch_runs(limit=limit)
        try:
            import pandas as pd  # type: ignore

            df = pd.DataFrame(rows)
            return df
        except Exception:
            return rows

    def latest_pipeline_run_id(self) -> Optional[str]:
        with self._connect() as con:
            row = con.execute("SELECT pipeline_run_id FROM runs ORDER BY recorded_at_utc DESC LIMIT 1").fetchone()
        return row[0] if row and row[0] else None

    def fetch_latest_run(self) -> Optional[Dict[str, Any]]:
        """Return the most recent v1 run as a dict, or None if no runs exist."""
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM runs ORDER BY recorded_at_utc DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def fetch_latest_traffic_run(self) -> Optional[Dict[str, Any]]:
        """Return the most recent v1 run with a valid traffic source."""
        with self._connect() as con:
            row = con.execute(
                """
                SELECT * FROM runs
                WHERE traffic_source_id IS NOT NULL
                  AND traffic_source_id NOT LIKE '%:error%'
                  AND tomtom_fetched_at IS NOT NULL
                ORDER BY recorded_at_utc DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def fetch_latest_n_runs(self, n: int = 300) -> List[Dict[str, Any]]:
        """Return the *n* most recent v1 runs (newest first)."""
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM runs ORDER BY recorded_at_utc DESC LIMIT ?",
                (int(n),),
            ).fetchall()
        return [dict(r) for r in rows]

    def v1_quality_summary(self) -> Dict[str, Any]:
        with self._connect() as con:
            total = con.execute("SELECT count(*), min(recorded_at_utc), max(recorded_at_utc) FROM runs").fetchone()
            reuse = con.execute("SELECT count(*) FROM runs WHERE quality_flags LIKE '%cache_reuse%'").fetchone()[0]
            stale = con.execute("SELECT count(*) FROM runs WHERE quality_flags LIKE '%stale_source%'").fetchone()[0]
        return {"runs": total[0], "first": total[1], "last": total[2], "cache_reuse": reuse, "stale_source": stale}

    # ── v2 writes ──────────────────────────────────────────────────────

    def store_raw(self, sha256: Optional[str], provider: str, fetched_at: Optional[str], body_gzip: Optional[bytes]) -> None:
        if not sha256 or not body_gzip:
            return
        with self._connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO raw_responses (sha256, provider, fetched_at_utc, body_gzip) VALUES (?,?,?,?)",
                (sha256, provider, fetched_at or _utc_now_iso(), body_gzip),
            )

    def insert_observation(self, obs: Dict[str, Any]) -> bool:
        """Insert one segment observation; False if this provider snapshot was already recorded."""
        obs = dict(obs)
        obs["recorded_at_utc"] = _utc_now_iso()
        cols = [
            "cycle_id", "segment_id", "segment_version", "methodology_version", "provider", "provider_snapshot",
            "observed_at_utc", "source_updated_utc", "fetched_at_utc", "processed_at_utc", "recorded_at_utc",
            "status", "coverage", "length_m", "travel_time_s", "freeflow_time_s", "delay_s", "speed_kmh",
            "freeflow_kmh", "confidence", "jam_factor", "mean_offset_m", "max_offset_m", "piece_ids", "raw_sha256",
        ]
        with self._connect() as con:
            cur = con.execute(
                f"INSERT OR IGNORE INTO segment_observations ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [obs.get(c) for c in cols],
            )
            return cur.rowcount == 1

    def record_cycle(self, cycle: Dict[str, Any]) -> None:
        cols = [
            "cycle_id", "methodology_version", "started_at_utc", "finished_at_utc", "provider", "provider_status",
            "status", "segments_total", "segments_ok", "segments_new", "source_updated_utc", "fetched_at_utc",
            "response_id", "raw_sha256", "error", "diagnostics_json", "fuel_price_ils_per_l", "fuel_source_id",
            "fuel_fetched_at_utc", "air_source_id", "air_fetched_at_utc",
        ]
        defaults = {"segments_new": 0}
        with self._connect() as con:
            con.execute(
                f"INSERT INTO collection_cycles ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [cycle.get(c, defaults.get(c)) for c in cols],
            )

    def prune_raw(self, older_than_utc: str) -> int:
        with self._connect() as con:
            cur = con.execute("DELETE FROM raw_responses WHERE fetched_at_utc < ?", (older_than_utc,))
            return cur.rowcount

    # ── v2 reads ───────────────────────────────────────────────────────

    def latest_cycles(self, n: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute("SELECT * FROM collection_cycles ORDER BY started_at_utc DESC LIMIT ?", (int(n),)).fetchall()
        return [dict(r) for r in rows]

    def last_cycle_with_status(self, statuses: List[str]) -> Optional[Dict[str, Any]]:
        q = ",".join("?" * len(statuses))
        with self._connect() as con:
            row = con.execute(
                f"SELECT * FROM collection_cycles WHERE status IN ({q}) ORDER BY started_at_utc DESC LIMIT 1", statuses
            ).fetchone()
        return dict(row) if row else None

    def latest_observation_per_segment(self) -> Dict[str, Dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT o.* FROM segment_observations o
                JOIN (SELECT segment_id, max(observed_at_utc) m FROM segment_observations GROUP BY segment_id) x
                  ON o.segment_id = x.segment_id AND o.observed_at_utc = x.m
                """
            ).fetchall()
        return {r["segment_id"]: dict(r) for r in rows}

    def latest_ok_observation_per_segment(self) -> Dict[str, Dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT o.* FROM segment_observations o
                JOIN (SELECT segment_id, max(observed_at_utc) m FROM segment_observations
                      WHERE status = 'ok' GROUP BY segment_id) x
                  ON o.segment_id = x.segment_id AND o.observed_at_utc = x.m
                WHERE o.status = 'ok'
                """
            ).fetchall()
        return {r["segment_id"]: dict(r) for r in rows}

    def observations_between(self, start_utc: str, end_utc: str, status: Optional[str] = "ok") -> List[Dict[str, Any]]:
        q = "SELECT * FROM segment_observations WHERE observed_at_utc >= ? AND observed_at_utc < ?"
        args: List[Any] = [start_utc, end_utc]
        if status:
            q += " AND status = ?"
            args.append(status)
        with self._connect() as con:
            rows = con.execute(q + " ORDER BY observed_at_utc", args).fetchall()
        return [dict(r) for r in rows]

    def quality_periods(self) -> List[Dict[str, Any]]:
        with self._connect() as con:
            try:
                rows = con.execute("SELECT * FROM data_quality_periods ORDER BY start_utc").fetchall()
            except sqlite3.OperationalError:
                return []
        return [dict(r) for r in rows]


def gunzip_json(blob: bytes) -> Any:
    return json.loads(gzip.decompress(blob).decode("utf-8"))
