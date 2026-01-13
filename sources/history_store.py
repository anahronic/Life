import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


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


class HistoryStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

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

    def fetch_runs(self, limit: int = 2000) -> List[Dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM runs ORDER BY recorded_at_utc DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    def fetch_runs_df(self, limit: int = 2000):
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
