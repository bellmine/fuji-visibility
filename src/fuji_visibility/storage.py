"""SQLite persistence for forecast snapshots and normalized hourly rows."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import ForecastResult, HourlyForecast, StoredForecast
from .time_utils import canonical_iso, parse_datetime, to_jst


class StorageError(RuntimeError):
    """An actionable local persistence error."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS forecast_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    retrieved_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    requested_lat REAL NOT NULL,
    requested_lon REAL NOT NULL,
    returned_lat REAL,
    returned_lon REAL,
    elevation_m REAL,
    raw_json_path TEXT,
    raw_sha256 TEXT
);

CREATE TABLE IF NOT EXISTS hourly_forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    valid_time TEXT NOT NULL,
    temperature_c REAL,
    relative_humidity_pct REAL,
    precipitation_probability_pct REAL,
    cloud_total_pct REAL,
    cloud_low_pct REAL,
    cloud_mid_pct REAL,
    cloud_high_pct REAL,
    visibility_m REAL,
    wind_speed_kmh REAL,
    wind_direction_deg REAL,
    FOREIGN KEY(snapshot_id) REFERENCES forecast_snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_hourly_valid_time
ON hourly_forecasts(valid_time);

CREATE INDEX IF NOT EXISTS idx_snapshot_retrieved
ON forecast_snapshots(retrieved_at);

CREATE INDEX IF NOT EXISTS idx_snapshots_model
ON forecast_snapshots(model);

CREATE INDEX IF NOT EXISTS idx_hourly_snapshot_time
ON hourly_forecasts(snapshot_id, valid_time);

CREATE INDEX IF NOT EXISTS idx_snapshot_location_model_time
ON forecast_snapshots(requested_lat, requested_lon, model, retrieved_at);

CREATE TABLE IF NOT EXISTS fingerprint_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    observed_at TEXT,
    valid_time TEXT NOT NULL,
    temperature_c REAL,
    displayed_cloud_pct REAL,
    visibility_km REAL,
    rank INTEGER,
    label TEXT,
    notes TEXT
);
"""


class ForecastStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(self.database_path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.executescript(SCHEMA)
            self._connection.commit()
        except sqlite3.OperationalError as exc:
            raise StorageError(
                f"Could not open SQLite database {self.database_path}: {exc}. "
                "If another process is writing, retry after it finishes."
            ) from exc

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> ForecastStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def save_forecast(
        self,
        result: ForecastResult,
        *,
        raw_directory: str | Path | None = None,
        save_raw: bool = True,
    ) -> int:
        body = result.raw_body
        if body is None:
            body = json.dumps(
                result.raw_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()

        existing = self._connection.execute(
            "SELECT id FROM forecast_snapshots WHERE raw_sha256 = ? LIMIT 1", (digest,)
        ).fetchone()
        if existing is not None:
            return int(existing["id"])

        raw_path: str | None = None
        if save_raw:
            if raw_directory is None:
                raise StorageError("raw_directory is required when save_raw=True")
            raw_dir = Path(raw_directory).expanduser()
            raw_dir.mkdir(parents=True, exist_ok=True)
            timestamp = to_jst(result.retrieved_at).strftime("%Y-%m-%dT%H%M%S%z")
            model_slug = _safe_filename(result.model)
            raw_file = raw_dir / (
                f"{timestamp}__{result.requested_lat:.3f}_{result.requested_lon:.3f}__"
                f"{model_slug}.json"
            )
            # A same-second request can have a different body. Keep both files
            # while still producing predictable names for ordinary snapshots.
            if raw_file.exists():
                raw_file = raw_dir / (
                    f"{timestamp}__{result.requested_lat:.3f}_{result.requested_lon:.3f}__"
                    f"{model_slug}__{digest[:12]}.json"
                )
            raw_file.write_bytes(body)
            raw_path = str(raw_file)

        retrieved_at = canonical_iso(result.retrieved_at)
        try:
            cursor = self._connection.cursor()
            cursor.execute("BEGIN")
            cursor.execute(
                """
                INSERT INTO forecast_snapshots (
                    retrieved_at, provider, model, requested_lat, requested_lon,
                    returned_lat, returned_lon, elevation_m, raw_json_path, raw_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    retrieved_at,
                    result.provider,
                    result.model,
                    result.requested_lat,
                    result.requested_lon,
                    result.returned_lat,
                    result.returned_lon,
                    result.elevation_m,
                    raw_path,
                    digest,
                ),
            )
            snapshot_id = int(cursor.lastrowid)
            cursor.executemany(
                """
                INSERT INTO hourly_forecasts (
                    snapshot_id, valid_time, temperature_c, relative_humidity_pct,
                    precipitation_probability_pct, cloud_total_pct, cloud_low_pct,
                    cloud_mid_pct, cloud_high_pct, visibility_m, wind_speed_kmh,
                    wind_direction_deg
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [_hour_row(snapshot_id, hour) for hour in result.hours],
            )
            self._connection.commit()
        except sqlite3.OperationalError as exc:
            self._connection.rollback()
            raise StorageError(
                f"Could not save forecast snapshot: {exc}. "
                "If the database is locked, retry after other writers finish."
            ) from exc
        return snapshot_id

    def save_fingerprint_observations(
        self,
        source: str,
        observations: Iterable[dict[str, object]],
        *,
        observed_at: str | None = None,
    ) -> int:
        rows = list(observations)
        try:
            cursor = self._connection.executemany(
                """
                INSERT INTO fingerprint_observations (
                    source, observed_at, valid_time, temperature_c, displayed_cloud_pct,
                    visibility_km, rank, label, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        source,
                        observed_at,
                        str(row["valid_time"]),
                        row.get("temperature_c"),
                        row.get("displayed_cloud_pct"),
                        row.get("visibility_km"),
                        row.get("rank"),
                        row.get("label"),
                        row.get("notes"),
                    )
                    for row in rows
                ],
            )
            self._connection.commit()
            return cursor.rowcount if cursor.rowcount != -1 else len(rows)
        except sqlite3.OperationalError as exc:
            self._connection.rollback()
            raise StorageError(f"Could not save fingerprint observations: {exc}") from exc

    def trend(
        self,
        valid_time: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        model: str | None = None,
    ) -> list[StoredForecast]:
        dt = parse_datetime(valid_time)
        canonical_time = canonical_iso(dt)
        clauses = ["h.valid_time = ?"]
        params: list[object] = [canonical_time]
        if latitude is not None:
            clauses.append("ABS(s.requested_lat - ?) < 0.000001")
            params.append(latitude)
        if longitude is not None:
            clauses.append("ABS(s.requested_lon - ?) < 0.000001")
            params.append(longitude)
        if model is not None:
            clauses.append("s.model = ?")
            params.append(model)
        query = f"""
            SELECT h.*, s.provider, s.model, s.requested_lat, s.requested_lon,
                   s.returned_lat, s.returned_lon, s.elevation_m, s.retrieved_at
            FROM hourly_forecasts AS h
            JOIN forecast_snapshots AS s ON s.id = h.snapshot_id
            WHERE {' AND '.join(clauses)}
            ORDER BY s.retrieved_at ASC, h.id ASC
        """
        try:
            rows = self._connection.execute(query, params).fetchall()
        except sqlite3.OperationalError as exc:
            raise StorageError(f"Could not read forecast trend: {exc}") from exc
        return [_stored_forecast(row) for row in rows]

    def snapshot_count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS count FROM forecast_snapshots").fetchone()
        return int(row["count"])

    def hourly_count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS count FROM hourly_forecasts").fetchone()
        return int(row["count"])


def _safe_filename(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
    return safe or "model"


def _hour_row(snapshot_id: int, hour: HourlyForecast) -> tuple[object, ...]:
    return (
        snapshot_id,
        canonical_iso(hour.valid_time),
        hour.temperature_c,
        hour.relative_humidity_pct,
        hour.precipitation_probability_pct,
        hour.cloud_total_pct,
        hour.cloud_low_pct,
        hour.cloud_mid_pct,
        hour.cloud_high_pct,
        hour.visibility_m,
        hour.wind_speed_kmh,
        hour.wind_direction_deg,
    )


def _stored_forecast(row: sqlite3.Row) -> StoredForecast:
    return StoredForecast(
        snapshot_id=int(row["snapshot_id"]),
        provider=str(row["provider"]),
        model=str(row["model"]),
        requested_lat=float(row["requested_lat"]),
        requested_lon=float(row["requested_lon"]),
        returned_lat=_optional_float(row["returned_lat"]),
        returned_lon=_optional_float(row["returned_lon"]),
        elevation_m=_optional_float(row["elevation_m"]),
        retrieved_at=parse_datetime(str(row["retrieved_at"])),
        valid_time=parse_datetime(str(row["valid_time"])),
        temperature_c=_optional_float(row["temperature_c"]),
        relative_humidity_pct=_optional_float(row["relative_humidity_pct"]),
        precipitation_probability_pct=_optional_float(row["precipitation_probability_pct"]),
        cloud_total_pct=_optional_float(row["cloud_total_pct"]),
        cloud_low_pct=_optional_float(row["cloud_low_pct"]),
        cloud_mid_pct=_optional_float(row["cloud_mid_pct"]),
        cloud_high_pct=_optional_float(row["cloud_high_pct"]),
        visibility_m=_optional_float(row["visibility_m"]),
        wind_speed_kmh=_optional_float(row["wind_speed_kmh"]),
        wind_direction_deg=_optional_float(row["wind_direction_deg"]),
    )


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)
