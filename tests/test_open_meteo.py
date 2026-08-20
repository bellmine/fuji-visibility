from __future__ import annotations

import httpx

from fuji_visibility.open_meteo import OpenMeteoClient


def test_forecast_response_is_normalized_and_jst(forecast_payload):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=forecast_payload, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = OpenMeteoClient(http_client=client).fetch_forecast(
            35.52,
            138.75,
            model="auto",
            start_date="2026-08-25",
            end_date="2026-08-25",
        )
    finally:
        client.close()

    assert len(requests) == 1
    assert "models" not in dict(requests[0].url.params)
    assert requests[0].url.params["timezone"] == "Asia/Tokyo"
    assert requests[0].url.params["wind_speed_unit"] == "kmh"
    assert result.hours[0].valid_time.isoformat() == "2026-08-25T05:00:00+09:00"
    assert result.hours[5].visibility_km == 42.5
    assert result.hours[5].wind_speed_kmh == 8
    assert result.resolved_model == "jma_seamless"
    assert result.raw_body is not None


def test_missing_hourly_arrays_remain_none(forecast_payload):
    del forecast_payload["hourly"]["visibility"]
    del forecast_payload["hourly"]["cloud_cover_mid"]
    result = OpenMeteoClient.parse_forecast_response(
        forecast_payload,
        requested_model="jma_msm",
        requested_lat=35.52,
        requested_lon=138.75,
    )
    assert result.hours[0].visibility_m is None
    assert result.hours[0].cloud_mid_pct is None


def test_single_run_parameter_is_utc_aligned():
    params = OpenMeteoClient.build_params(
        35.52,
        138.75,
        model="jma_gsm",
        run="2026-08-20T18:00:00Z",
        forecast_days=7,
    )
    assert params["models"] == "jma_gsm"
    assert params["run"] == "2026-08-20T18:00"


def test_previous_runs_uses_base_fields_for_current_run():
    payload = {
        "latitude": 35.52,
        "longitude": 138.75,
        "timezone": "Asia/Tokyo",
        "hourly": {
            "time": ["2026-08-26T09:00"],
            "temperature_2m": [27.2],
            "temperature_2m_previous_day1": [26.0],
            "relative_humidity_2m": [70],
            "relative_humidity_2m_previous_day1": [75],
            "precipitation_probability": [10],
            "precipitation_probability_previous_day1": [20],
            "cloud_cover": [5],
            "cloud_cover_previous_day1": [20],
            "cloud_cover_mid": [0],
            "cloud_cover_mid_previous_day1": [10],
            "visibility": [42500],
            "visibility_previous_day1": [30000],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        points = OpenMeteoClient(http_client=client).fetch_previous_runs(
            35.52,
            138.75,
            start_date="2026-08-26",
            end_date="2026-08-26",
            max_day=1,
        )
    finally:
        client.close()
    current = next(point for point in points if point.day_offset == 0)
    previous = next(point for point in points if point.day_offset == 1)
    assert current.temperature_c == 27.2
    assert current.visibility_km == 42.5
    assert previous.temperature_c == 26.0
    assert previous.visibility_km == 30.0
