from __future__ import annotations

from datetime import datetime

from fuji_visibility.consensus import (
    ForecastMember,
    ModelCapabilityCache,
    build_consensus,
    capability_from_forecast,
)
from fuji_visibility.models import ForecastResult, ModelCapability
from fuji_visibility.open_meteo import OpenMeteoError


def _result(model, rows, *, raw_payload=None):
    return ForecastResult(
        model=model,
        resolved_model=model,
        requested_lat=35.52,
        requested_lon=138.75,
        timezone="Asia/Tokyo",
        retrieved_at=datetime.fromisoformat("2026-08-21T07:35:00+09:00"),
        hours=rows,
        raw_payload=raw_payload or {},
    )


def _capability(model, *, visibility=True):
    variables = {
        "cloud_cover_mid",
        "relative_humidity_2m",
        "precipitation_probability",
    }
    if visibility:
        variables.add("visibility")
    return ModelCapability(
        model=model,
        supported=True,
        variables_available=variables,
        missing_required=set(),
        missing_optional=set() if visibility else {"visibility"},
    )


def test_consensus_median_range_and_outlier(make_hour):
    models = []
    for index, visibility in enumerate((40000, 41000, 42000, 43000, 1000)):
        model = f"model_{index}"
        row = make_hour(
            "2026-08-26T09:00:00+09:00",
            model=model,
            visibility_m=visibility,
            cloud_mid_pct=5 if index < 4 else 90,
            relative_humidity_pct=50 if index < 4 else 100,
            precipitation_probability_pct=5 if index < 4 else 100,
        )
        models.append(ForecastMember(model, _result(model, [row]), _capability(model)))
    result = build_consensus(models)
    hour = result.hours[0]
    assert hour.model_count == 5
    assert hour.full_model_count == 5
    assert hour.full_proxy_model_count == 5
    assert len(hour.proxy_values) == 5
    assert hour.proxy_spread == hour.proxy_max - hour.proxy_min
    assert hour.proxy_median is not None
    assert hour.proxy_min is not None and hour.proxy_max is not None
    assert "model_4" in hour.outlier_models
    assert hour.consensus_label in {"LOW", "MEDIUM"}


def test_partial_model_contributes_cloud_but_not_full_proxy(make_hour):
    full = "cloud_cover_mid,relative_humidity_2m,precipitation_probability,visibility"
    rows = []
    members = []
    for model, has_visibility in (("a", True), ("b", True), ("c", True), ("d", True), ("partial", False)):
        row = make_hour(
            "2026-08-26T09:00:00+09:00",
            model=model,
            visibility_m=40000 if has_visibility else None,
            cloud_mid_pct=5,
        )
        members.append(
            ForecastMember(model, _result(model, [row]), _capability(model, visibility=has_visibility))
        )
    hour = build_consensus(members).hours[0]
    assert hour.model_count == 5
    assert hour.full_model_count == 4
    assert hour.partial_model_count == 1
    assert hour.mid_cloud_median == 5
    assert hour.mid_cloud_model_count == 5
    assert hour.visibility_model_count == 4
    assert hour.field_consensus["mid_cloud"].support == "STRONG_SUPPORT"
    assert hour.field_consensus["visibility"].model_count == 4


def test_capability_records_missing_fields_and_cache():
    payload = {
        "hourly": {
            "time": ["2026-08-26T09:00"],
            "cloud_cover_mid": [5],
            "relative_humidity_2m": [60],
        }
    }
    result = _result("synthetic", [], raw_payload=payload)
    capability = capability_from_forecast(result)
    assert capability.supported is True
    assert capability.missing_required == {"precipitation_probability"}
    assert "visibility" in capability.missing_optional
    cache = ModelCapabilityCache()
    cache.put(capability)
    assert cache.get("synthetic") == capability


def test_unsupported_model_is_cached_and_partial_failure_is_tolerated(make_hour):
    from fuji_visibility.consensus import ConsensusFetcher

    good_row = make_hour("2026-08-26T09:00:00+09:00", model="good")
    good_result = _result("good", [good_row], raw_payload={
        "hourly": {
            "time": ["2026-08-26T09:00"],
            "temperature_2m": [27],
            "relative_humidity_2m": [60],
            "precipitation_probability": [5],
            "cloud_cover_mid": [5],
            "visibility": [40000],
        }
    })

    class FakeClient:
        def __init__(self):
            self.calls = []

        def fetch_forecast(self, latitude, longitude, *, model, **kwargs):
            self.calls.append(model)
            if model == "bad":
                raise OpenMeteoError("unsupported model")
            return good_result

    client = FakeClient()
    fetcher = ConsensusFetcher(client)
    first = fetcher.fetch(35.52, 138.75, models=["bad", "good"])
    second = fetcher.fetch(35.52, 138.75, models=["bad", "good"])
    assert len(first.members) == 1
    assert len(first.failures) == 1
    assert client.calls.count("bad") == 1
    assert client.calls.count("good") == 2
    assert second.model_count == 1
