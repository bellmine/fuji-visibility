"""Open-Meteo HTTP client and response normalization."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .config import (
    FORECAST_URL,
    HOURLY_VARIABLES,
    PREVIOUS_RUNS_URL,
    PROVIDER,
    REQUEST_TIMEOUT_SECONDS,
    SINGLE_RUNS_URL,
    TIMEZONE,
)
from .models import ForecastResult, HourlyForecast, PreviousRunPoint
from .time_utils import canonical_iso, ensure_aware, parse_datetime, to_jst

logger = logging.getLogger(__name__)


class OpenMeteoError(RuntimeError):
    """An actionable API or response error."""


def _api_time(value: datetime | date | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return to_jst(ensure_aware(value)).isoformat(timespec="minutes")
    return value.isoformat()


def _json_value(values: Any, index: int) -> float | None:
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _response_model(payload: dict[str, Any], requested_model: str) -> str | None:
    for key in ("model", "model_id"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    value = payload.get("models")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if isinstance(value, dict):
        return ",".join(f"{key}:{item}" for key, item in value.items())
    return requested_model if requested_model != "auto" else None


def _timezone_from_payload(payload: dict[str, Any]) -> ZoneInfo | timezone:
    name = payload.get("timezone")
    if isinstance(name, str):
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            pass
    offset = payload.get("utc_offset_seconds")
    if isinstance(offset, (int, float)):
        return timezone(timedelta(seconds=int(offset)))
    return ZoneInfo(TIMEZONE)


class OpenMeteoClient:
    """Small synchronous client; an httpx client can be injected for tests."""

    def __init__(
        self,
        *,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        http_client: httpx.Client | None = None,
        verbose: bool = False,
    ) -> None:
        self.timeout = timeout
        self._owns_client = http_client is None
        self.http_client = http_client or httpx.Client(timeout=timeout)
        self.verbose = verbose

    def close(self) -> None:
        if self._owns_client:
            self.http_client.close()

    def __enter__(self) -> OpenMeteoClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def build_params(
        latitude: float,
        longitude: float,
        *,
        model: str = "auto",
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        start_hour: datetime | str | None = None,
        end_hour: datetime | str | None = None,
        forecast_days: int | None = None,
        hourly_variables: Iterable[str] = HOURLY_VARIABLES,
        pressure_levels: Iterable[int] | None = None,
        run: datetime | str | None = None,
    ) -> dict[str, str | int | float]:
        if (start_date is not None or end_date is not None) and (
            start_hour is not None or end_hour is not None
        ):
            raise ValueError("use either start/end date or start/end hour, not both")
        if (start_date is None) != (end_date is None):
            raise ValueError("start_date and end_date must be supplied together")
        if (start_hour is None) != (end_hour is None):
            raise ValueError("start_hour and end_hour must be supplied together")
        if forecast_days is not None and forecast_days <= 0:
            raise ValueError("forecast_days must be positive")

        params: dict[str, str | int | float] = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": TIMEZONE,
            "timeformat": "iso8601",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "hourly": ",".join(hourly_variables),
        }
        if model != "auto":
            params["models"] = model
        if start_date is not None and end_date is not None:
            params["start_date"] = _api_time(start_date)
            params["end_date"] = _api_time(end_date)
        if start_hour is not None and end_hour is not None:
            params["start_hour"] = _api_time(start_hour)
            params["end_hour"] = _api_time(end_hour)
        if forecast_days is not None:
            params["forecast_days"] = forecast_days
        if pressure_levels:
            levels = list(pressure_levels)
            params["hourly"] = (
                str(params["hourly"])
                + ","
                + ",".join(f"cloud_cover_{level}hPa" for level in levels)
                + ","
                + ",".join(f"relative_humidity_{level}hPa" for level in levels)
            )
        if run is not None:
            if isinstance(run, str):
                run_dt = parse_datetime(run)
                if "+" not in run and not run.endswith("Z"):
                    run_dt = run_dt.replace(tzinfo=timezone.utc)
            else:
                run_dt = ensure_aware(run)
            run_dt = run_dt.astimezone(timezone.utc)
            params["run"] = run_dt.isoformat(timespec="minutes").replace("+00:00", "")
        return params

    def _request_json(
        self,
        url: str,
        params: dict[str, str | int | float],
        *,
        operation: str,
    ) -> tuple[dict[str, Any], bytes]:
        if self.verbose:
            logger.info("GET %s params=%s", url, params)
        try:
            response = self.http_client.get(url, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenMeteoError(
                f"Open-Meteo {operation} timed out after {self.timeout:g}s; "
                "try again or increase the configured timeout."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                body = exc.response.json()
                if isinstance(body, dict) and body.get("reason"):
                    detail = f" {body['reason']}"
            except (ValueError, json.JSONDecodeError):
                pass
            raise OpenMeteoError(
                f"Open-Meteo {operation} failed with HTTP {exc.response.status_code}.{detail}"
            ) from exc
        except httpx.RequestError as exc:
            raise OpenMeteoError(f"Could not reach Open-Meteo for {operation}: {exc}") from exc

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise OpenMeteoError("Open-Meteo returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise OpenMeteoError("Open-Meteo returned an unexpected JSON shape.")
        if payload.get("error"):
            reason = payload.get("reason") or "the API reported an unspecified error"
            raise OpenMeteoError(f"Open-Meteo rejected the request: {reason}")
        return payload, response.content

    def fetch_forecast(
        self,
        latitude: float,
        longitude: float,
        *,
        model: str = "auto",
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        start_hour: datetime | str | None = None,
        end_hour: datetime | str | None = None,
        forecast_days: int | None = None,
        pressure_levels: Iterable[int] | None = None,
        retrieved_at: datetime | None = None,
    ) -> ForecastResult:
        params = self.build_params(
            latitude,
            longitude,
            model=model,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            forecast_days=forecast_days,
            pressure_levels=pressure_levels,
        )
        payload, raw_body = self._request_json(FORECAST_URL, params, operation="forecast request")
        return self.parse_forecast_response(
            payload,
            requested_model=model,
            requested_lat=latitude,
            requested_lon=longitude,
            retrieved_at=retrieved_at,
            raw_body=raw_body,
        )

    def fetch_single_run(
        self,
        latitude: float,
        longitude: float,
        run: datetime | str,
        *,
        model: str = "auto",
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        forecast_days: int | None = None,
        retrieved_at: datetime | None = None,
    ) -> ForecastResult:
        if (start_date is None) != (end_date is None):
            raise ValueError("start_date and end_date must be supplied together")
        if forecast_days is None:
            forecast_days = _forecast_days_until(run, end_date) if end_date is not None else 7
        params = self.build_params(
            latitude,
            longitude,
            model=model,
            forecast_days=forecast_days,
            run=run,
        )
        payload, raw_body = self._request_json(SINGLE_RUNS_URL, params, operation="single-run request")
        return self.parse_forecast_response(
            payload,
            requested_model=model,
            requested_lat=latitude,
            requested_lon=longitude,
            retrieved_at=retrieved_at,
            raw_body=raw_body,
        )

    @staticmethod
    def parse_forecast_response(
        payload: dict[str, Any],
        *,
        requested_model: str,
        requested_lat: float,
        requested_lon: float,
        retrieved_at: datetime | None = None,
        raw_body: bytes | None = None,
    ) -> ForecastResult:
        hourly = payload.get("hourly")
        if not isinstance(hourly, dict):
            reason = payload.get("reason") or "the response did not contain hourly data"
            raise OpenMeteoError(f"Open-Meteo returned no usable hourly data: {reason}")
        times = hourly.get("time")
        if not isinstance(times, list) or not times:
            raise OpenMeteoError("Open-Meteo returned an empty hourly time series.")

        api_zone = _timezone_from_payload(payload)
        retrieved = to_jst(ensure_aware(retrieved_at or datetime.now(timezone.utc)))
        returned_lat = _as_float(payload.get("latitude"))
        returned_lon = _as_float(payload.get("longitude"))
        elevation = _as_float(payload.get("elevation"))
        resolved_model = _response_model(payload, requested_model)

        rows: list[HourlyForecast] = []
        for index, raw_time in enumerate(times):
            if not isinstance(raw_time, str):
                raise OpenMeteoError(f"Open-Meteo returned a non-string time at index {index}.")
            parsed_time = parse_datetime(raw_time, default_zone=api_zone)
            valid_time = to_jst(parsed_time)
            rows.append(
                HourlyForecast(
                    provider=PROVIDER,
                    model=requested_model,
                    requested_lat=requested_lat,
                    requested_lon=requested_lon,
                    returned_lat=returned_lat,
                    returned_lon=returned_lon,
                    elevation_m=elevation,
                    retrieved_at=retrieved,
                    valid_time=valid_time,
                    temperature_c=_json_value(hourly.get("temperature_2m"), index),
                    relative_humidity_pct=_json_value(hourly.get("relative_humidity_2m"), index),
                    precipitation_probability_pct=_json_value(
                        hourly.get("precipitation_probability"), index
                    ),
                    cloud_total_pct=_json_value(hourly.get("cloud_cover"), index),
                    cloud_low_pct=_json_value(hourly.get("cloud_cover_low"), index),
                    cloud_mid_pct=_json_value(hourly.get("cloud_cover_mid"), index),
                    cloud_high_pct=_json_value(hourly.get("cloud_cover_high"), index),
                    visibility_m=_json_value(hourly.get("visibility"), index),
                    wind_speed_kmh=_json_value(hourly.get("wind_speed_10m"), index),
                    wind_direction_deg=_json_value(hourly.get("wind_direction_10m"), index),
                )
            )

        known_keys = {
            "time",
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation_probability",
            "cloud_cover",
            "cloud_cover_low",
            "cloud_cover_mid",
            "cloud_cover_high",
            "visibility",
            "wind_speed_10m",
            "wind_direction_10m",
        }
        extra_hourly = {key: value for key, value in hourly.items() if key not in known_keys}
        return ForecastResult(
            provider=PROVIDER,
            model=requested_model,
            resolved_model=resolved_model,
            requested_lat=requested_lat,
            requested_lon=requested_lon,
            returned_lat=returned_lat,
            returned_lon=returned_lon,
            elevation_m=elevation,
            timezone=str(payload.get("timezone") or TIMEZONE),
            retrieved_at=retrieved,
            hours=rows,
            raw_payload=payload,
            raw_body=raw_body,
            extra_hourly=extra_hourly,
        )

    def fetch_previous_runs(
        self,
        latitude: float,
        longitude: float,
        *,
        model: str = "auto",
        start_date: date | str,
        end_date: date | str,
        max_day: int = 7,
    ) -> list[PreviousRunPoint]:
        if max_day < 0 or max_day > 7:
            raise ValueError("max_day must be between 0 and 7")
        variables: list[str] = []
        base_variables = (
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation_probability",
            "cloud_cover",
            "cloud_cover_mid",
            "visibility",
        )
        for offset in range(max_day + 1):
            suffix = "" if offset == 0 else f"_previous_day{offset}"
            variables.extend(f"{name}{suffix}" for name in base_variables)
        params = self.build_params(
            latitude,
            longitude,
            model=model,
            start_date=start_date,
            end_date=end_date,
            hourly_variables=variables,
        )
        payload, _ = self._request_json(PREVIOUS_RUNS_URL, params, operation="previous-runs request")
        hourly = payload.get("hourly")
        if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
            raise OpenMeteoError("Previous Runs API returned no usable hourly data.")
        api_zone = _timezone_from_payload(payload)
        result: list[PreviousRunPoint] = []
        for index, raw_time in enumerate(hourly["time"]):
            if not isinstance(raw_time, str):
                continue
            valid_time = to_jst(parse_datetime(raw_time, default_zone=api_zone))
            for offset in range(max_day + 1):
                suffix = "" if offset == 0 else f"_previous_day{offset}"
                result.append(
                    PreviousRunPoint(
                        valid_time=valid_time,
                        day_offset=offset,
                        temperature_c=_json_value(hourly.get(f"temperature_2m{suffix}"), index),
                        relative_humidity_pct=_json_value(
                            hourly.get(f"relative_humidity_2m{suffix}"), index
                        ),
                        precipitation_probability_pct=_json_value(
                            hourly.get(f"precipitation_probability{suffix}"), index
                        ),
                        cloud_total_pct=_json_value(hourly.get(f"cloud_cover{suffix}"), index),
                        cloud_mid_pct=_json_value(hourly.get(f"cloud_cover_mid{suffix}"), index),
                        visibility_m=_json_value(hourly.get(f"visibility{suffix}"), index),
                    )
                )
        return result


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _forecast_days_until(run: datetime | str, end_date: date | str) -> int:
    """Single Runs currently accepts forecast_days, not start/end_date."""

    if isinstance(run, str):
        run_dt = parse_datetime(run)
        if "+" not in run and not run.endswith("Z"):
            run_dt = run_dt.replace(tzinfo=timezone.utc)
    else:
        run_dt = ensure_aware(run)
    run_local_date = run_dt.astimezone(ZoneInfo(TIMEZONE)).date()
    target_date = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    # Add one day for a target date's late-evening hours and clamp to the
    # Forecast/Single Runs API's documented 16-day maximum.
    return max(1, min(16, (target_date - run_local_date).days + 2))
