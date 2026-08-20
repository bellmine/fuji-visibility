from __future__ import annotations

from datetime import datetime

from fuji_visibility.models import ForecastResult
from fuji_visibility.open_meteo import OpenMeteoClient
from fuji_visibility.storage import ForecastStore


def test_snapshot_persistence_raw_hash_dedup_and_trend(tmp_path, forecast_payload):
    first = OpenMeteoClient.parse_forecast_response(
        forecast_payload,
        requested_model="auto",
        requested_lat=35.52,
        requested_lon=138.75,
        retrieved_at=datetime.fromisoformat("2026-08-21T07:35:00+09:00"),
        raw_body=b"first-body",
    )
    second = first.model_copy(
        update={
            "retrieved_at": datetime.fromisoformat("2026-08-21T13:35:00+09:00"),
            "raw_body": b"second-body",
            "hours": [
                hour.model_copy(
                    update={"retrieved_at": datetime.fromisoformat("2026-08-21T13:35:00+09:00")}
                )
                for hour in first.hours
            ],
        }
    )
    db_path = tmp_path / "forecast.sqlite"
    raw_dir = tmp_path / "raw"
    with ForecastStore(db_path) as store:
        first_id = store.save_forecast(first, raw_directory=raw_dir)
        duplicate_id = store.save_forecast(first, raw_directory=raw_dir)
        second_id = store.save_forecast(second, raw_directory=raw_dir)
        assert first_id == duplicate_id
        assert second_id != first_id
        assert store.snapshot_count() == 2
        assert store.hourly_count() == len(first.hours) * 2
        trend = store.trend("2026-08-25T10:00:00+09:00", latitude=35.52, longitude=138.75)
        assert len(trend) == 2
    assert len(list(raw_dir.glob("*.json"))) == 2
