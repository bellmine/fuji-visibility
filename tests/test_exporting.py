from __future__ import annotations

import json
from datetime import date, datetime

from fuji_visibility.consensus import ConsensusHour, ConsensusResult
from fuji_visibility.exporting import export_consensus_text, export_text, select_rows
from fuji_visibility.open_meteo import OpenMeteoClient


def test_normalized_csv_and_json_exports(forecast_payload):
    result = OpenMeteoClient.parse_forecast_response(
        forecast_payload,
        requested_model="auto",
        requested_lat=35.52,
        requested_lon=138.75,
    )
    rows = select_rows(result, result.hours[0].valid_time.date(), hours=(5, 6))
    csv_text = export_text(result, rows, export_format="csv")
    assert "valid_time,temperature_c" in csv_text
    assert "visibility_km" in csv_text
    json_payload = json.loads(export_text(result, rows, export_format="json"))
    assert len(json_payload["rows"]) == 2
    assert json_payload["rows"][0]["fuji_proxy_score"] is not None


def test_consensus_export_contains_member_and_aggregate_rows():
    hour = ConsensusHour(
        valid_time=datetime.fromisoformat("2026-08-26T09:00:00+09:00"),
        model_count=3,
        full_model_count=3,
        partial_model_count=0,
        proxy_median=84,
        proxy_min=80,
        proxy_max=88,
        proxy_stddev=3,
        mid_cloud_median=8,
        mid_cloud_min=5,
        mid_cloud_max=12,
        mid_cloud_stddev=3,
        visibility_median_km=35,
        visibility_min_km=30,
        visibility_max_km=40,
        visibility_stddev_km=4,
        precip_median=5,
        humidity_median=60,
        models_good_proxy=3,
        models_good_mid_cloud=3,
        models_good_visibility=3,
        consensus_label="HIGH",
        outlier_models=(),
        members=(),
    )
    result = ConsensusResult(
        requested_models=("a", "b", "c"),
        members=(),
        failures=(),
        hours=(hour,),
        requested_lat=35.52,
        requested_lon=138.75,
    )
    csv_text = export_consensus_text(
        [(date(2026, 8, 26), result)], export_format="csv", hours=(9, 9)
    )
    assert "CONSENSUS_MEDIAN" in csv_text
    assert "consensus_label" in csv_text
