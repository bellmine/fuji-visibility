"""Typed normalized data models used throughout the application."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HourlyForecast(BaseModel):
    """One local-time hourly forecast row with source values preserved."""

    model_config = ConfigDict(extra="ignore")

    provider: str = "open-meteo"
    model: str
    requested_lat: float
    requested_lon: float
    returned_lat: float | None = None
    returned_lon: float | None = None
    elevation_m: float | None = None

    retrieved_at: datetime
    valid_time: datetime

    temperature_c: float | None = None
    relative_humidity_pct: float | None = None
    precipitation_probability_pct: float | None = None

    cloud_total_pct: float | None = None
    cloud_low_pct: float | None = None
    cloud_mid_pct: float | None = None
    cloud_high_pct: float | None = None

    visibility_m: float | None = None

    # Open-Meteo returns km/h when wind_speed_unit=kmh is requested.
    wind_speed_kmh: float | None = None
    wind_direction_deg: float | None = None

    @field_validator("retrieved_at", "valid_time")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("forecast timestamps must be timezone-aware")
        return value

    @property
    def visibility_km(self) -> float | None:
        return None if self.visibility_m is None else self.visibility_m / 1000.0


class ForecastResult(BaseModel):
    """A complete API response plus normalized hourly rows."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: str = "open-meteo"
    model: str
    resolved_model: str | None = None
    requested_lat: float
    requested_lon: float
    returned_lat: float | None = None
    returned_lon: float | None = None
    elevation_m: float | None = None
    timezone: str
    retrieved_at: datetime
    hours: list[HourlyForecast] = Field(default_factory=list)
    raw_payload: dict[str, Any]
    raw_body: bytes | None = None
    extra_hourly: dict[str, list[Any]] = Field(default_factory=dict)

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value


class ModelCapability(BaseModel):
    """Variables observed for one model during the current process."""

    model: str
    supported: bool
    variables_available: set[str] = Field(default_factory=set)
    missing_required: set[str] = Field(default_factory=set)
    missing_optional: set[str] = Field(default_factory=set)
    error: str | None = None

    @property
    def full_forecast_available(self) -> bool:
        return not self.missing_required and "visibility" in self.variables_available


class FingerprintObservation(BaseModel):
    valid_time: datetime
    temperature_c: float | None = None
    displayed_cloud_pct: float | None = None
    visibility_km: float | None = None
    rank: int | None = None
    label: str | None = None
    notes: str | None = None

    @field_validator("valid_time")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fingerprint valid_time must include a timezone offset")
        return value


class Fingerprint(BaseModel):
    source: str = "unknown"
    observed_at: datetime | None = None
    observations: list[FingerprintObservation]


class ComponentScores(BaseModel):
    visibility: float | None = None
    cloud: float | None = None
    precipitation: float | None = None
    humidity: float | None = None


class ProxyScore(BaseModel):
    """The explicit, approximate Fuji Proxy Score."""

    score: float | None = None
    cloud_strategy: str
    effective_cloud_pct: float | None = None
    components: ComponentScores = Field(default_factory=ComponentScores)
    missing_fields: tuple[str, ...] = ()


class StoredForecast(HourlyForecast):
    """Hourly row read back from SQLite, retaining its snapshot id."""

    snapshot_id: int


class PreviousRunPoint(BaseModel):
    valid_time: datetime
    day_offset: int
    temperature_c: float | None = None
    relative_humidity_pct: float | None = None
    precipitation_probability_pct: float | None = None
    cloud_total_pct: float | None = None
    cloud_mid_pct: float | None = None
    visibility_m: float | None = None

    @field_validator("valid_time")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("previous-run timestamps must be timezone-aware")
        return value

    @property
    def visibility_km(self) -> float | None:
        return None if self.visibility_m is None else self.visibility_m / 1000.0
