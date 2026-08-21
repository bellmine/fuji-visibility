from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from fuji_visibility.models import ForecastResult, HourlyForecast
from fuji_visibility.services import snapshot_all_models
from fuji_visibility.storage import ForecastStore
from fuji_visibility.time_utils import JST


def _forecast(model: str, start: date, end: date) -> ForecastResult:
    rows: list[HourlyForecast] = []
    current = start
    retrieved_at = datetime(2026, 8, 21, 7, 35, tzinfo=JST)
    while current <= end:
        for hour in range(24):
            valid_time = datetime(current.year, current.month, current.day, hour, tzinfo=JST)
            rows.append(
                HourlyForecast(
                    model=model,
                    requested_lat=35.52,
                    requested_lon=138.75,
                    retrieved_at=retrieved_at,
                    valid_time=valid_time,
                    temperature_c=22.0,
                    relative_humidity_pct=70.0,
                    precipitation_probability_pct=5.0,
                    cloud_total_pct=10.0,
                    cloud_low_pct=5.0,
                    cloud_mid_pct=5.0,
                    cloud_high_pct=10.0,
                    visibility_m=42_500.0,
                    wind_speed_kmh=8.0,
                    wind_direction_deg=200.0,
                )
            )
        current += timedelta(days=1)
    return ForecastResult(
        model=model,
        resolved_model=model,
        requested_lat=35.52,
        requested_lon=138.75,
        timezone="Asia/Tokyo",
        retrieved_at=retrieved_at,
        hours=rows,
        raw_payload={"hourly": {"time": [row.valid_time.isoformat() for row in rows]}},
        raw_body=model.encode("utf-8"),
    )


def test_snapshot_collection_requests_and_persists_full_local_days(
    tmp_path: Path, monkeypatch
) -> None:
    collection_start = date(2026, 8, 21)
    collection_end = date(2026, 8, 22)
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def fetch_forecast(
            self,
            latitude: float,
            longitude: float,
            *,
            model: str,
            **kwargs: object,
        ) -> ForecastResult:
            del latitude, longitude
            calls.append((model, kwargs))
            return _forecast(model, kwargs["start_date"], kwargs["end_date"])

    monkeypatch.setattr("fuji_visibility.services.OpenMeteoClient", FakeClient)
    monkeypatch.setattr(
        "fuji_visibility.services.full_local_date_range",
        lambda days: (collection_start, collection_end),
    )

    database_path = tmp_path / "forecast.sqlite"
    raw_directory = tmp_path / "raw"
    result = snapshot_all_models(
        35.52,
        138.75,
        days=2,
        models=("auto", "jma_msm"),
        database_path=database_path,
        raw_directory=raw_directory,
    )

    assert result.successful_models == ("auto", "jma_msm")
    assert len(calls) == 2
    for _, kwargs in calls:
        assert kwargs == {"start_date": collection_start, "end_date": collection_end}

    with ForecastStore(database_path) as store:
        assert store.snapshot_count() == 2
        assert store.hourly_count() == 2 * 2 * 24
        for hour in (2, 8, 14, 18, 23):
            valid_time = f"2026-08-21T{hour:02d}:00:00+09:00"
            assert len(store.trend(valid_time, latitude=35.52, longitude=138.75)) == 2
