"""Environment-backed settings for the dashboard and snapshot worker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path

from ..config import (
    BEST_BLOCK_HOURS,
    CANDIDATE_MODELS,
    DEFAULT_DATABASE_PATH,
    DEFAULT_LOCATION,
    DEFAULT_RAW_DATA_PATH,
    GOOD_HUMIDITY_MAX,
    GOOD_MID_CLOUD_MAX,
    GOOD_PRECIP_MAX,
    GOOD_VISIBILITY_MIN_KM,
    MAX_PROXY_SPREAD_FOR_STRONG_SUPPORT,
    MAX_PROXY_SPREAD_FOR_WEAK_SUPPORT,
    MIN_FULL_PROXY_MODELS,
    MIN_PROXY,
    FORECAST_COLLECTION_HOURS,
    TIMEZONE,
)
from ..time_utils import parse_clock


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or not value.strip() else value.strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


@dataclass(frozen=True)
class DashboardSettings:
    timezone: str = TIMEZONE
    default_location: str = DEFAULT_LOCATION
    default_start_hour: int = 8
    default_end_hour: int = 17
    default_arrival_after: time = time(8, 0)
    snapshot_interval_hours: int = 3
    manual_refresh_cooldown_seconds: int = 300
    database_path: Path = DEFAULT_DATABASE_PATH
    raw_data_dir: Path = DEFAULT_RAW_DATA_PATH
    refresh_lock_path: Path = DEFAULT_DATABASE_PATH.parent / "refresh.lock"
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    upcoming_days: int = 7
    raw_retention_days: int = 30
    configured_models: tuple[str, ...] = CANDIDATE_MODELS
    cloud_strategy: str = "mid"
    min_proxy: float = MIN_PROXY
    min_full_proxy_models: int = MIN_FULL_PROXY_MODELS
    max_proxy_spread_strong: float = MAX_PROXY_SPREAD_FOR_STRONG_SUPPORT
    max_proxy_spread_weak: float = MAX_PROXY_SPREAD_FOR_WEAK_SUPPORT
    good_mid_cloud_max: float = GOOD_MID_CLOUD_MAX
    good_visibility_min_km: float = GOOD_VISIBILITY_MIN_KM
    good_precip_max: float = GOOD_PRECIP_MAX
    good_humidity_max: float = GOOD_HUMIDITY_MAX
    min_window_hours: int = 2
    best_block_hours: int = BEST_BLOCK_HOURS

    @classmethod
    def from_env(cls) -> "DashboardSettings":
        timezone_name = _env("FUJI_TIMEZONE", TIMEZONE)
        arrival_text = _env("FUJI_DEFAULT_ARRIVAL_AFTER", "08:00")
        try:
            arrival_after = parse_clock(arrival_text)
        except ValueError as exc:
            raise ValueError("FUJI_DEFAULT_ARRIVAL_AFTER must use HH:MM") from exc
        database_path = Path(_env("FUJI_DB_PATH", str(DEFAULT_DATABASE_PATH))).expanduser()
        raw_data_dir = Path(_env("FUJI_RAW_DATA_DIR", str(DEFAULT_RAW_DATA_PATH))).expanduser()
        lock_path = Path(
            _env("FUJI_REFRESH_LOCK_PATH", str(database_path.parent / "refresh.lock"))
        ).expanduser()
        model_text = _env("FUJI_MODELS", ",".join(CANDIDATE_MODELS))
        configured_models = tuple(item.strip() for item in model_text.split(",") if item.strip())
        if not configured_models:
            configured_models = CANDIDATE_MODELS
        return cls(
            timezone=timezone_name,
            default_location=_env("FUJI_DEFAULT_LOCATION", DEFAULT_LOCATION).lower(),
            default_start_hour=_env_int("FUJI_DEFAULT_START_HOUR", 8),
            default_end_hour=_env_int("FUJI_DEFAULT_END_HOUR", 17),
            default_arrival_after=arrival_after,
            snapshot_interval_hours=max(1, _env_int("FUJI_SNAPSHOT_INTERVAL_HOURS", 3)),
            manual_refresh_cooldown_seconds=max(
                0, _env_int("FUJI_MANUAL_REFRESH_COOLDOWN_SECONDS", 300)
            ),
            database_path=database_path,
            raw_data_dir=raw_data_dir,
            refresh_lock_path=lock_path,
            web_host=_env("FUJI_WEB_HOST", "0.0.0.0"),
            web_port=_env_int("FUJI_WEB_PORT", 8000),
            upcoming_days=max(1, _env_int("FUJI_UPCOMING_DAYS", 7)),
            raw_retention_days=max(0, _env_int("FUJI_RAW_RETENTION_DAYS", 30)),
            configured_models=configured_models,
            cloud_strategy=_env("FUJI_CLOUD_STRATEGY", "mid"),
            min_proxy=_env_float("FUJI_MIN_PROXY", MIN_PROXY),
            min_full_proxy_models=max(
                1, _env_int("FUJI_MIN_FULL_PROXY_MODELS", MIN_FULL_PROXY_MODELS)
            ),
            max_proxy_spread_strong=_env_float(
                "FUJI_MAX_PROXY_SPREAD_STRONG", MAX_PROXY_SPREAD_FOR_STRONG_SUPPORT
            ),
            max_proxy_spread_weak=_env_float(
                "FUJI_MAX_PROXY_SPREAD_WEAK", MAX_PROXY_SPREAD_FOR_WEAK_SUPPORT
            ),
            good_mid_cloud_max=_env_float("FUJI_GOOD_MID_CLOUD_MAX", GOOD_MID_CLOUD_MAX),
            good_visibility_min_km=_env_float(
                "FUJI_GOOD_VISIBILITY_MIN_KM", GOOD_VISIBILITY_MIN_KM
            ),
            good_precip_max=_env_float("FUJI_GOOD_PRECIP_MAX", GOOD_PRECIP_MAX),
            good_humidity_max=_env_float("FUJI_GOOD_HUMIDITY_MAX", GOOD_HUMIDITY_MAX),
            min_window_hours=max(1, _env_int("FUJI_MIN_WINDOW_HOURS", 2)),
            best_block_hours=max(1, _env_int("FUJI_BEST_BLOCK_HOURS", BEST_BLOCK_HOURS)),
        )

    @property
    def hours(self) -> tuple[int, int]:
        if not (0 <= self.default_start_hour <= self.default_end_hour <= 23):
            raise ValueError("FUJI_DEFAULT_START_HOUR and END_HOUR must be an inclusive 0-23 range")
        return self.default_start_hour, self.default_end_hour

    @property
    def collection_hours(self) -> tuple[int, int]:
        """The fixed local-day range used by forecast collection/storage."""

        return FORECAST_COLLECTION_HOURS

    @property
    def location_preset(self):
        from ..config import LOCATION_PRESETS

        try:
            return LOCATION_PRESETS[self.default_location]
        except KeyError as exc:
            raise ValueError(f"unknown FUJI_DEFAULT_LOCATION: {self.default_location}") from exc
