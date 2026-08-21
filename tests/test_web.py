from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from fuji_visibility.models import ForecastResult, HourlyForecast
from fuji_visibility.open_meteo import OpenMeteoError
from fuji_visibility.services import (
    DashboardService,
    LAST_REFRESH_ATTEMPT,
    RefreshCooldownError,
)
from fuji_visibility.storage import ForecastStore
from fuji_visibility.web.app import create_app
from fuji_visibility.web.refresh import RefreshBusyError, refresh_lock
from fuji_visibility.web.settings import DashboardSettings

JST = ZoneInfo("Asia/Tokyo")
MODELS = ("auto", "jma_seamless", "gfs_seamless")


def _settings(tmp_path: Path, *, models: tuple[str, ...] = MODELS) -> DashboardSettings:
    data_dir = tmp_path / "data"
    return DashboardSettings(
        default_location="kawaguchiko",
        default_start_hour=5,
        default_end_hour=12,
        database_path=data_dir / "forecast.sqlite",
        raw_data_dir=data_dir / "raw",
        refresh_lock_path=data_dir / "refresh.lock",
        upcoming_days=7,
        configured_models=models,
        manual_refresh_cooldown_seconds=300,
    )


def _hour(model: str, valid_time: str, *, retrieved_at: str, partial: bool = False) -> HourlyForecast:
    return HourlyForecast(
        model=model,
        requested_lat=35.520,
        requested_lon=138.750,
        retrieved_at=datetime.fromisoformat(retrieved_at),
        valid_time=datetime.fromisoformat(valid_time),
        temperature_c=22.0,
        relative_humidity_pct=70.0,
        precipitation_probability_pct=5.0,
        cloud_total_pct=10.0,
        cloud_low_pct=5.0,
        cloud_mid_pct=5.0,
        cloud_high_pct=10.0,
        visibility_m=None if partial else 42_500.0,
        wind_speed_kmh=8.0,
        wind_direction_deg=200.0,
    )


def _seed(
    settings: DashboardSettings,
    *,
    dates: tuple[str, ...] = ("2026-08-26", "2026-08-27"),
    partial_model: str | None = None,
    retrieved_at: str = "2026-08-20T05:30:00+09:00",
) -> None:
    with ForecastStore(settings.database_path) as store:
        for model in settings.configured_models:
            rows = [
                _hour(
                    model,
                    f"{target_date}T{hour:02d}:00:00+09:00",
                    retrieved_at=retrieved_at,
                    partial=model == partial_model,
                )
                for target_date in dates
                for hour in (8, 9)
            ]
            result = ForecastResult(
                model=model,
                resolved_model=model,
                requested_lat=35.520,
                requested_lon=138.750,
                timezone="Asia/Tokyo",
                retrieved_at=datetime.fromisoformat(retrieved_at),
                hours=rows,
                raw_payload={"hourly": {"time": [row.valid_time.isoformat() for row in rows]}},
                raw_body=f"{model}:{retrieved_at}".encode("utf-8"),
            )
            store.save_forecast(result, raw_directory=settings.raw_data_dir)


def _request(app, method: str, path: str) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path)

    return asyncio.run(send())


def _get(app, path: str) -> httpx.Response:
    return _request(app, "GET", path)


def _post(app, path: str) -> httpx.Response:
    return _request(app, "POST", path)


def test_homepage_and_json_apis_use_stored_consensus(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, dates=("2026-08-26",))
    app = create_app(settings)

    page = _get(
        app,
        "/?dates=2026-08-26&date=2026-08-26&hours=8-9&arrival_after=08:00"
    )
    assert page.status_code == 200
    assert '<html lang="zh-CN">' in page.text
    assert "推荐" in page.text
    assert "可到达时段逐小时预测" in page.text
    assert "数据状态" in page.text  # fixture is intentionally stale
    assert "8月26日 周三" in page.text
    assert "window.__FUJI_DASHBOARD__" in page.text
    assert '<link rel="stylesheet" href="./static/app.css">' in page.text
    assert '<script src="./static/app.js" defer></script>' in page.text
    assert "http://fuji.wangdi.store/static/" not in page.text

    decision = _get(
        app,
        "/api/decision?dates=2026-08-26&hours=8-9&arrival_after=08:00"
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "RECOMMENDED"
    assert decision.json()["status_label"] == "推荐"
    assert decision.json()["winner_date"] == "2026-08-26"

    forecast = _get(app, "/api/forecast?date=2026-08-26&dates=2026-08-26&hours=8-9")
    assert forecast.status_code == 200
    assert len(forecast.json()["day"]["hours"]) == 2
    assert forecast.json()["day"]["hours"][0]["full_model_count"] == 3
    hour_payload = forecast.json()["day"]["hours"][0]
    assert hour_payload["proxy"]["model_count"] == 3
    assert "mid_cloud" in hour_payload["field_consensus"]
    assert hour_payload["status_label"] == "符合条件"

    trend = _get(app, "/api/trend?date=2026-08-26&hour=09:00&variable=proxy")
    assert trend.status_code == 200
    assert trend.json()["points"]
    assert trend.json()["trend_label"] == "未知"
    assert trend.json()["confidence_label"] == "未知"


def test_no_clear_winner_and_no_qualifying_window_are_explicit(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings)
    app = create_app(settings)

    ambiguous = _get(
        app,
        "/api/decision?dates=2026-08-26,2026-08-27&hours=8-9&arrival_after=08:00"
    )
    assert ambiguous.status_code == 200
    assert ambiguous.json()["status"] == "NO CLEAR WINNER"
    assert ambiguous.json()["status_label"] == "暂无明确优选"
    assert ambiguous.json()["winner_date"] is None

    no_window = _get(
        app,
        "/api/decision?dates=2026-08-28&hours=8-9&arrival_after=08:00"
    )
    assert no_window.status_code == 200
    assert no_window.json()["status"] == "INSUFFICIENT EVIDENCE"
    assert no_window.json()["status_label"] == "核心数据不足"


def test_partial_model_diagnostics_and_health_status(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, dates=("2026-08-26",), partial_model="gfs_seamless")
    app = create_app(settings)

    page = _get(app, "/?dates=2026-08-26&date=2026-08-26")
    assert page.status_code == 200
    assert "部分可用" in page.text
    assert "值得关注" in page.text
    assert "目前只有 2 个模型具备完整评分所需数据。" in page.text
    assert "完整评分" in page.text
    assert "综合评分" in page.text and "中层云" in page.text and "降水" in page.text

    health = _get(app, "/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["last_snapshot"]

    status = _get(app, "/api/status")
    assert status.status_code == 200
    assert status.json()["configured_models"] == 3
    assert status.json()["freshness"] == "STALE"

    with ForecastStore(settings.database_path) as store:
        journal_mode = store._connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(journal_mode).lower() == "wal"


def test_refresh_lock_contention_and_manual_cooldown(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with refresh_lock(settings.refresh_lock_path):
        with pytest.raises(RefreshBusyError):
            with refresh_lock(settings.refresh_lock_path):
                pass

    now = datetime.now(JST)
    with ForecastStore(settings.database_path) as store:
        store.set_metadata(LAST_REFRESH_ATTEMPT, now.isoformat())
    service = DashboardService(settings)
    with pytest.raises(RefreshCooldownError, match="refreshed recently"):
        service.refresh(manual=True)

    app = create_app(settings)
    response = _post(app, "/api/refresh")
    assert response.status_code == 429
    assert response.json()["status"] == "cooldown"
    assert "预报最近已刷新" in response.json()["message"]
    assert response.headers["retry-after"]


def test_refresh_api_failure_keeps_error_structured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)

    def fail_refresh(*, manual: bool = True):
        raise OpenMeteoError("provider timeout")

    monkeypatch.setattr(app.state.dashboard_service, "refresh", fail_refresh)
    response = _post(app, "/api/refresh")
    assert response.status_code == 502
    assert response.json()["error"] == "refresh_failed"
    assert response.json()["message"] == "预报刷新失败，已保存的数据仍然可用。"
    assert "traceback" not in response.text.lower()


def test_dashboard_normal_view_uses_chinese_labels_only(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, dates=("2026-08-26",))
    page = _get(app=create_app(settings), path="/?dates=2026-08-26&date=2026-08-26")

    english_ui_labels = (
        "Mt. Fuji Visibility",
        "When is Mt. Fuji most likely to be visible?",
        "Decision",
        "Upcoming conditions",
        "Reachable hourly forecast",
        "Consensus snapshot",
        "Forecast drift",
        "Is the view changing?",
        "Model coverage and failures",
        "Refresh forecast",
        "Apply",
        "Location",
        "Hours",
        "Arrival after",
        "Proxy median",
        "Cloud mid",
        "Visibility",
        "Models",
        "RECOMMENDED",
        "NO CLEAR WINNER",
        "NO QUALIFYING WINDOW",
        "HIGH",
        "MEDIUM",
        "LOW",
        "INSUFFICIENT_DATA",
        "IMPROVING",
        "WORSENING",
        "STABLE",
        "VOLATILE",
        "FULL",
        "PARTIAL",
    )
    assert page.status_code == 200
    assert all(label not in page.text for label in english_ui_labels)


def test_static_assets_are_relative_and_served_without_mixed_content(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, dates=("2026-08-26",))
    app = create_app(settings)
    page = _get(app, "/?dates=2026-08-26&date=2026-08-26")
    assert '<link rel="stylesheet" href="./static/app.css">' in page.text
    assert '<script src="./static/app.js" defer></script>' in page.text
    assert "http://fuji.wangdi.store/static/" not in page.text


def test_decision_state_labels_are_localized(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings)
    app = create_app(settings)

    ambiguous = _get(
        app,
        "/?dates=2026-08-26,2026-08-27&date=2026-08-26&hours=8-9&arrival_after=08:00",
    )
    assert "暂无明确优选" in ambiguous.text

    no_window = _get(
        app,
        "/?dates=2026-08-28&date=2026-08-28&hours=8-9&arrival_after=08:00",
    )
    assert "核心数据不足" in no_window.text
    assert "目前核心数据不足，暂时无法做出可靠判断。" in no_window.text
