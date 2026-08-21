from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fuji_visibility.config import LOCATION_PRESETS
from fuji_visibility.services import DashboardService, SnapshotRun
from fuji_visibility.storage import ForecastStore
from fuji_visibility.web.settings import DashboardSettings


def _settings(tmp_path: Path) -> DashboardSettings:
    data_dir = tmp_path / "data"
    return DashboardSettings(
        default_location="kawaguchiko",
        database_path=data_dir / "forecast.sqlite",
        raw_data_dir=data_dir / "raw",
        refresh_lock_path=data_dir / "refresh.lock",
        configured_models=("auto",),
        upcoming_days=1,
        manual_refresh_cooldown_seconds=0,
    )


def test_refresh_fetches_every_location_and_namespaces_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    calls: list[tuple[float, float]] = []

    def fake_snapshot(latitude: float, longitude: float, **kwargs: object) -> SnapshotRun:
        calls.append((latitude, longitude))
        return SnapshotRun(
            snapshot_ids=(len(calls),),
            successful_models=("auto",),
            failures=(),
            capabilities=(),
        )

    monkeypatch.setattr("fuji_visibility.services.snapshot_all_models", fake_snapshot)
    service = DashboardService(
        settings,
        now=lambda: datetime.fromisoformat("2026-08-21T12:00:00+09:00"),
    )

    result = service.refresh(manual=False)

    assert calls == [
        (preset.latitude, preset.longitude) for preset in LOCATION_PRESETS.values()
    ]
    assert len(result.snapshot_ids) == len(LOCATION_PRESETS)
    assert result.successful_models == ("auto",)

    with ForecastStore(settings.database_path) as store:
        metadata = store.get_metadata_map()
    for location_name in LOCATION_PRESETS:
        assert metadata[f"last_refresh_status:{location_name}"] == "success"
        assert metadata[f"last_model_capabilities:{location_name}"] == "[]"
