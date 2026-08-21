"""Normalized CSV and JSON export for hourly forecast data."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, time
from typing import Iterable

from .consensus import ConsensusResult
from .models import ForecastResult, HourlyForecast
from .scoring import proxy_score
from .time_utils import canonical_iso, to_jst

EXPORT_FIELDS = (
    "valid_time",
    "temperature_c",
    "cloud_total_pct",
    "cloud_low_pct",
    "cloud_mid_pct",
    "cloud_high_pct",
    "visibility_m",
    "visibility_km",
    "relative_humidity_pct",
    "precipitation_probability_pct",
    "wind_speed_kmh",
    "wind_direction_deg",
    "effective_cloud_pct",
    "fuji_proxy_score",
    "proxy_missing_fields",
)


def select_rows(
    result: ForecastResult,
    target_date: date,
    *,
    hours: tuple[int, int] = (0, 23),
) -> list[HourlyForecast]:
    start_hour, end_hour = hours
    return [
        row
        for row in result.hours
        if to_jst(row.valid_time).date() == target_date
        and start_hour <= to_jst(row.valid_time).hour <= end_hour
    ]


def row_dict(row: HourlyForecast, *, cloud_strategy: str = "mid") -> dict[str, object]:
    score = proxy_score(row, cloud_strategy)
    return {
        "valid_time": canonical_iso(row.valid_time),
        "temperature_c": row.temperature_c,
        "cloud_total_pct": row.cloud_total_pct,
        "cloud_low_pct": row.cloud_low_pct,
        "cloud_mid_pct": row.cloud_mid_pct,
        "cloud_high_pct": row.cloud_high_pct,
        "visibility_m": row.visibility_m,
        "visibility_km": row.visibility_km,
        "relative_humidity_pct": row.relative_humidity_pct,
        "precipitation_probability_pct": row.precipitation_probability_pct,
        "wind_speed_kmh": row.wind_speed_kmh,
        "wind_direction_deg": row.wind_direction_deg,
        "effective_cloud_pct": score.effective_cloud_pct,
        "fuji_proxy_score": score.score,
        "proxy_missing_fields": "; ".join(score.missing_fields),
    }


def export_text(
    result: ForecastResult,
    rows: Iterable[HourlyForecast],
    *,
    export_format: str,
    cloud_strategy: str = "mid",
) -> str:
    if export_format not in {"csv", "json"}:
        raise ValueError("export format must be csv or json")
    normalized = [row_dict(row, cloud_strategy=cloud_strategy) for row in rows]
    if export_format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(normalized)
        return output.getvalue()
    payload = {
        "provider": result.provider,
        "model": result.model,
        "resolved_model": result.resolved_model,
        "requested_lat": result.requested_lat,
        "requested_lon": result.requested_lon,
        "returned_lat": result.returned_lat,
        "returned_lon": result.returned_lon,
        "elevation_m": result.elevation_m,
        "timezone": result.timezone,
        "retrieved_at": canonical_iso(result.retrieved_at),
        "cloud_strategy": cloud_strategy,
        "rows": normalized,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


CONSENSUS_EXPORT_FIELDS = (
    "valid_time",
    "model",
    "proxy",
    "cloud_mid",
    "visibility_km",
    "precip_probability",
    "humidity",
    "reachable",
    "consensus_label",
    "model_count",
    "full_model_count",
    "full_proxy_model_count",
    "proxy_min",
    "proxy_max",
    "proxy_spread",
    "proxy_stddev",
    "proxy_agreement",
    "mid_cloud_model_count",
    "mid_cloud_support",
    "visibility_model_count",
    "visibility_support",
    "precip_model_count",
    "precip_support",
    "humidity_model_count",
    "humidity_support",
    "outlier",
)


def export_consensus_text(
    daily_results: Iterable[tuple[date, ConsensusResult]],
    *,
    export_format: str,
    hours: tuple[int, int] = (0, 23),
    arrival_after: time | None = None,
) -> str:
    """Export per-model rows plus one derived median row per valid hour."""

    if export_format not in {"csv", "json"}:
        raise ValueError("export format must be csv or json")
    rows: list[dict[str, object]] = []
    json_days: list[dict[str, object]] = []
    for target_date, result in daily_results:
        day_json: dict[str, object] = {"date": target_date.isoformat(), "hours": []}
        for hour in result.hours:
            local = to_jst(hour.valid_time)
            if local.date() != target_date or not (hours[0] <= local.hour <= hours[1]):
                continue
            reachable = arrival_after is None or local.time().replace(second=0, microsecond=0) >= arrival_after
            member_rows = []
            for member in hour.members:
                member_row = {
                    "valid_time": canonical_iso(hour.valid_time),
                    "model": member.model,
                    "proxy": member.proxy.score,
                    "cloud_mid": member.record.cloud_mid_pct,
                    "visibility_km": member.record.visibility_km,
                    "precip_probability": member.record.precipitation_probability_pct,
                    "humidity": member.record.relative_humidity_pct,
                    "reachable": reachable,
                    "consensus_label": hour.consensus_label,
                    "model_count": hour.model_count,
                    "full_model_count": hour.full_model_count,
                    "full_proxy_model_count": hour.full_proxy_model_count,
                    "proxy_min": hour.proxy_min,
                    "proxy_max": hour.proxy_max,
                    "proxy_spread": hour.proxy_spread,
                    "proxy_stddev": hour.proxy_stddev,
                    "proxy_agreement": hour.proxy_agreement,
                    "mid_cloud_model_count": hour.mid_cloud_model_count,
                    "mid_cloud_support": _field_support(hour, "mid_cloud"),
                    "visibility_model_count": hour.visibility_model_count,
                    "visibility_support": _field_support(hour, "visibility"),
                    "precip_model_count": hour.precip_model_count,
                    "precip_support": _field_support(hour, "precipitation"),
                    "humidity_model_count": hour.humidity_model_count,
                    "humidity_support": _field_support(hour, "humidity"),
                    "outlier": member.outlier,
                }
                rows.append(member_row)
                member_rows.append(member_row)
            aggregate_row = {
                "valid_time": canonical_iso(hour.valid_time),
                "model": "CONSENSUS_MEDIAN",
                "proxy": hour.proxy_median,
                "cloud_mid": hour.mid_cloud_median,
                "visibility_km": hour.visibility_median_km,
                "precip_probability": hour.precip_median,
                "humidity": hour.humidity_median,
                "reachable": reachable,
                "consensus_label": hour.consensus_label,
                "model_count": hour.model_count,
                "full_model_count": hour.full_model_count,
                "full_proxy_model_count": hour.full_proxy_model_count,
                "proxy_min": hour.proxy_min,
                "proxy_max": hour.proxy_max,
                "proxy_spread": hour.proxy_spread,
                "proxy_stddev": hour.proxy_stddev,
                "proxy_agreement": hour.proxy_agreement,
                "mid_cloud_model_count": hour.mid_cloud_model_count,
                "mid_cloud_support": _field_support(hour, "mid_cloud"),
                "visibility_model_count": hour.visibility_model_count,
                "visibility_support": _field_support(hour, "visibility"),
                "precip_model_count": hour.precip_model_count,
                "precip_support": _field_support(hour, "precipitation"),
                "humidity_model_count": hour.humidity_model_count,
                "humidity_support": _field_support(hour, "humidity"),
                "outlier": False,
            }
            rows.append(aggregate_row)
            day_json["hours"].append({"aggregate": aggregate_row, "models": member_rows})
        json_days.append(day_json)
    if export_format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=CONSENSUS_EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()
    return json.dumps({"days": json_days}, ensure_ascii=False, indent=2) + "\n"


def _field_support(hour, name: str) -> str:
    evidence = hour.field_consensus.get(name)
    return "" if evidence is None else evidence.support
