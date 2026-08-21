"""HTML and JSON routes for the lightweight dashboard."""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..open_meteo import OpenMeteoError
from ..services import DashboardService, RefreshCooldownError
from ..stability import consensus_stability
from ..storage import StorageError, ForecastStore
from ..time_utils import JST, parse_clock, parse_date
from .refresh import RefreshBusyError
from .schemas import RefreshResponse
from .viewmodels import dashboard_payload, trend_payload

logger = logging.getLogger(__name__)


def register_routes(app: FastAPI, templates: Jinja2Templates) -> None:
    def service(request: Request) -> DashboardService:
        return request.app.state.dashboard_service

    @app.get("/health", response_class=JSONResponse)
    async def health(request: Request) -> JSONResponse:
        try:
            return JSONResponse(service(request).health())
        except (StorageError, ValueError) as exc:
            logger.exception("health check failed")
            return JSONResponse(
                {"status": "error", "database": "unavailable", "message": str(exc)},
                status_code=503,
            )

    @app.get("/", response_class=HTMLResponse)
    async def homepage(
        request: Request,
        dates: str | None = Query(None, description="Comma-separated ISO dates."),
        selected_date: str | None = Query(None, alias="date"),
        location: str | None = Query(None),
        arrival_after: str | None = Query(None),
        hours: str | None = Query(None, description="Inclusive hour range such as 5-12."),
    ) -> HTMLResponse:
        dashboard_service = service(request)
        try:
            selected_dates = _parse_dates(dates, dashboard_service)
            hour_range = _parse_hours(hours, dashboard_service)
            chosen_date = parse_date(selected_date) if selected_date else None
            selected_location = dashboard_service.location_for(location)
            selected_arrival = (
                parse_clock(arrival_after)
                if arrival_after
                else dashboard_service.settings.default_arrival_after
            )
            data = dashboard_service.dashboard_data(
                dates=selected_dates,
                arrival_after=arrival_after,
                hours=hour_range,
                location=location,
            )
            payload = dashboard_payload(data, selected_date=chosen_date)
            selected = payload.get("selected_date")
            selected_day = next(
                (item for item in payload["days"] if item["date"] == selected),
                payload["days"][0] if payload["days"] else None,
            )
            context = {
                "request": request,
                "payload": payload,
                "selected_day": selected_day,
                "settings": dashboard_service.settings,
                "location": selected_location,
                "filter_hours": hour_range,
                "filter_arrival_after": selected_arrival,
                "version": payload["status"].get("version"),
                "error": None,
            }
        except (ValueError, StorageError) as exc:
            logger.exception("dashboard render failed")
            context = {
                "request": request,
                "payload": {"status": {"version": "unknown"}, "days": [], "decision": {}},
                "selected_day": None,
                "settings": dashboard_service.settings,
                "location": dashboard_service.location,
                "filter_hours": dashboard_service.settings.hours,
                "filter_arrival_after": dashboard_service.settings.default_arrival_after,
                "version": "unknown",
                "error": "Forecast data could not be loaded. Stored data may still be available.",
            }
        return templates.TemplateResponse(request, "dashboard.html", context)

    @app.get("/diagnostics", response_class=HTMLResponse)
    async def diagnostics(request: Request) -> HTMLResponse:
        dashboard_service = service(request)
        try:
            payload: dict[str, Any] = dashboard_service.diagnostics()
            error = None
        except (StorageError, ValueError) as exc:
            logger.exception("diagnostics render failed")
            payload = {}
            error = "Diagnostics are temporarily unavailable."
        return templates.TemplateResponse(
            request,
            "diagnostics.html",
            {
                "request": request,
                "diagnostics": payload,
                "settings": dashboard_service.settings,
                "error": error,
            },
        )

    @app.get("/api/status")
    async def api_status(request: Request) -> dict[str, object]:
        try:
            return service(request).status()
        except (StorageError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="Dashboard status unavailable") from exc

    @app.get("/api/days")
    async def api_days(
        request: Request,
        dates: str | None = Query(None),
        location: str | None = Query(None),
        arrival_after: str | None = Query(None),
        hours: str | None = Query(None),
    ) -> dict[str, object]:
        data = _dashboard_data(request, dates, arrival_after, hours, location)
        return dashboard_payload(data)

    @app.get("/api/forecast")
    async def api_forecast(
        request: Request,
        date_value: str | None = Query(None, alias="date"),
        dates: str | None = Query(None),
        location: str | None = Query(None),
        arrival_after: str | None = Query(None),
        hours: str | None = Query(None),
    ) -> dict[str, object]:
        data = _dashboard_data(request, dates, arrival_after, hours, location)
        chosen = parse_date(date_value) if date_value else None
        payload = dashboard_payload(data, selected_date=chosen)
        return {
            "date": payload.get("selected_date"),
            "day": next(
                (item for item in payload["days"] if item["date"] == payload.get("selected_date")),
                None,
            ),
            "status": payload["status"],
        }

    @app.get("/api/consensus")
    async def api_consensus(
        request: Request,
        date_value: str | None = Query(None, alias="date"),
        dates: str | None = Query(None),
        location: str | None = Query(None),
        arrival_after: str | None = Query(None),
        hours: str | None = Query(None),
    ) -> dict[str, object]:
        data = _dashboard_data(request, dates, arrival_after, hours, location)
        chosen = parse_date(date_value) if date_value else None
        payload = dashboard_payload(data, selected_date=chosen)
        return {
            "date": payload.get("selected_date"),
            "day": next(
                (item for item in payload["days"] if item["date"] == payload.get("selected_date")),
                None,
            ),
        }

    @app.get("/api/decision")
    async def api_decision(
        request: Request,
        dates: str | None = Query(None),
        location: str | None = Query(None),
        arrival_after: str | None = Query(None),
        hours: str | None = Query(None),
    ) -> dict[str, object]:
        data = _dashboard_data(request, dates, arrival_after, hours, location)
        return dashboard_payload(data)["decision"]

    @app.get("/api/trend")
    async def api_trend(
        request: Request,
        date_value: str = Query(..., alias="date"),
        hour: str = Query(...),
        variable: str = Query("proxy"),
        location: str | None = Query(None),
    ) -> dict[str, object]:
        dashboard_service = service(request)
        try:
            target_date = parse_date(date_value)
            target_time = parse_clock(hour)
            target = datetime.combine(target_date, target_time).replace(tzinfo=JST)
            selected_location = dashboard_service.location_for(location)
            with ForecastStore(dashboard_service.settings.database_path) as store:
                rows = store.trend(
                    target.isoformat(),
                    latitude=selected_location.latitude,
                    longitude=selected_location.longitude,
                )
            metrics = consensus_stability(
                rows,
                cloud_strategy=dashboard_service.settings.cloud_strategy,
            )
            return trend_payload(metrics, variable=variable)
        except (ValueError, StorageError) as exc:
            raise HTTPException(status_code=400, detail="Invalid trend request") from exc

    @app.post("/api/refresh", response_model=RefreshResponse)
    async def api_refresh(request: Request) -> RefreshResponse:
        try:
            result = service(request).refresh(manual=True)
            failures = [failure.__dict__ for failure in result.failures]
            status = "partial" if failures else "success"
            return RefreshResponse(
                status=status,
                message=(
                    "Forecast refreshed with partial model data."
                    if failures
                    else "Forecast refreshed successfully."
                ),
                snapshot_ids=list(result.snapshot_ids),
                successful_models=list(result.successful_models),
                failures=failures,
            )
        except RefreshBusyError as exc:
            return JSONResponse(
                {"status": "busy", "message": str(exc)}, status_code=409
            )
        except RefreshCooldownError as exc:
            return JSONResponse(
                {
                    "status": "cooldown",
                    "message": str(exc),
                    "retry_after_seconds": exc.retry_after_seconds,
                },
                status_code=429,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )
        except (OpenMeteoError, StorageError, OSError) as exc:
            logger.exception("manual refresh failed")
            return JSONResponse(
                {
                    "error": "refresh_failed",
                    "message": "Forecast refresh failed. Stored data is still available.",
                    "detail": str(exc),
                },
                status_code=502,
            )


def _dashboard_data(
    request: Request,
    dates: str | None,
    arrival_after: str | None,
    hours: str | None,
    location: str | None = None,
):
    dashboard_service: DashboardService = request.app.state.dashboard_service
    try:
        return dashboard_service.dashboard_data(
            dates=_parse_dates(dates, dashboard_service),
            arrival_after=arrival_after,
            hours=_parse_hours(hours, dashboard_service),
            location=location,
        )
    except (ValueError, StorageError) as exc:
        raise HTTPException(status_code=400, detail="Invalid dashboard request") from exc


def _parse_dates(value: str | None, service: DashboardService) -> tuple[date, ...]:
    if not value:
        return service.upcoming_dates()
    parsed = tuple(parse_date(item.strip()) for item in value.split(",") if item.strip())
    if not parsed:
        raise ValueError("dates must contain at least one ISO date")
    return tuple(dict.fromkeys(parsed))


def _parse_hours(value: str | None, service: DashboardService) -> tuple[int, int]:
    if not value:
        return service.settings.hours
    if "-" not in value:
        parsed = int(value)
        if not 0 <= parsed <= 23:
            raise ValueError("hour must be between 0 and 23")
        return parsed, parsed
    start, end = value.split("-", 1)
    parsed = int(start), int(end)
    if not (0 <= parsed[0] <= parsed[1] <= 23):
        raise ValueError("hours must be an inclusive range from 0 to 23")
    return parsed
