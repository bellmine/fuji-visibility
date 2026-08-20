from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from fuji_visibility.models import HourlyForecast

JST = ZoneInfo("Asia/Tokyo")
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "forecast.json"


@pytest.fixture
def forecast_payload() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _make_hour(
    valid_time: str,
    *,
    retrieved_at: str = "2026-08-21T07:35:00+09:00",
    model: str = "auto",
    requested_lat: float = 35.52,
    requested_lon: float = 138.75,
    temperature_c: float | None = 27.2,
    relative_humidity_pct: float | None = 70,
    precipitation_probability_pct: float | None = 5,
    cloud_total_pct: float | None = 10,
    cloud_low_pct: float | None = 5,
    cloud_mid_pct: float | None = 5,
    cloud_high_pct: float | None = 10,
    visibility_m: float | None = 42500,
    wind_speed_kmh: float | None = 8,
    wind_direction_deg: float | None = 200,
) -> HourlyForecast:
    return HourlyForecast(
        model=model,
        requested_lat=requested_lat,
        requested_lon=requested_lon,
        retrieved_at=datetime.fromisoformat(retrieved_at),
        valid_time=datetime.fromisoformat(valid_time),
        temperature_c=temperature_c,
        relative_humidity_pct=relative_humidity_pct,
        precipitation_probability_pct=precipitation_probability_pct,
        cloud_total_pct=cloud_total_pct,
        cloud_low_pct=cloud_low_pct,
        cloud_mid_pct=cloud_mid_pct,
        cloud_high_pct=cloud_high_pct,
        visibility_m=visibility_m,
        wind_speed_kmh=wind_speed_kmh,
        wind_direction_deg=wind_direction_deg,
    )


@pytest.fixture
def make_hour():
    return _make_hour
