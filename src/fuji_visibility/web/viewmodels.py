"""JSON-safe view models for templates and dashboard API responses."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Iterable

from ..consensus import ConsensusHour, ConsensusResult
from ..decision import DecisionDay, DecisionHour, DecisionResult, DecisionWindow
from ..services import DashboardData
from ..stability import StabilityMetrics, StabilityPoint
from ..time_utils import canonical_iso, to_jst


def dashboard_payload(data: DashboardData, *, selected_date: date | None = None) -> dict[str, object]:
    result_by_date = {target_date: result for target_date, result in data.daily_results}
    day_by_date = {day.date: day for day in data.decision.days}
    selected = selected_date or _default_selected_date(data.decision, data.dates)
    selected_result = result_by_date.get(selected)
    return {
        "generated_at": canonical_iso(datetime.now().astimezone()),
        "selected_date": None if selected_result is None else selected.isoformat(),
        "status": data.status,
        "decision": decision_payload(data.decision),
        "days": [
            day_payload(
                target_date,
                result_by_date.get(target_date),
                day_by_date.get(target_date),
                data.stability_by_time,
            )
            for target_date in data.dates
        ],
    }


def decision_payload(result: DecisionResult) -> dict[str, object]:
    return {
        "status": result.status,
        "winner_date": None if result.winner is None else result.winner.date.isoformat(),
        "no_clear_winner": result.no_clear_winner,
        "min_proxy": result.min_proxy,
        "min_window_hours": result.min_window_hours,
        "rationale": list(result.rationale),
        "days": [
            {
                "date": day.date.isoformat(),
                "best_window": window_payload(day.best_window),
                "windows": [window_payload(window) for window in day.windows],
            }
            for day in result.days
        ],
    }


def day_payload(
    target_date: date,
    result: ConsensusResult | None,
    decision_day: DecisionDay | None,
    stability_by_time: dict[str, StabilityMetrics],
) -> dict[str, object]:
    if result is None:
        return {
            "date": target_date.isoformat(),
            "label": target_date.strftime("%a %b %-d"),
            "best_window": None,
            "hours": [],
            "models": [],
            "failures": [],
        }
    decision_hours = {
        canonical_iso(item.consensus.valid_time): item for item in (decision_day.hours if decision_day else ())
    }
    if decision_day is not None:
        selected_hours = [
            hour_payload(
                item.consensus,
                item,
                stability_by_time.get(canonical_iso(item.consensus.valid_time)),
            )
            for item in decision_day.hours
        ]
    else:
        selected_hours = [
            hour_payload(
                hour,
                decision_hours.get(canonical_iso(hour.valid_time)),
                stability_by_time.get(canonical_iso(hour.valid_time)),
            )
            for hour in result.hours
        ]
    return {
        "date": target_date.isoformat(),
        "label": target_date.strftime("%a %b %-d"),
        "best_window": window_payload(decision_day.best_window if decision_day else None),
        "hours": selected_hours,
        "models": model_diagnostics(result),
        "failures": [
            {"model": failure.model, "reason": failure.reason} for failure in result.failures
        ],
    }


def hour_payload(
    hour: ConsensusHour,
    decision_hour: DecisionHour | None,
    stability: StabilityMetrics | None,
) -> dict[str, object]:
    return {
        "valid_time": canonical_iso(hour.valid_time),
        "local_time": to_jst(hour.valid_time).strftime("%H:%M"),
        "reachable": True if decision_hour is None else decision_hour.reachable,
        "qualifies": False if decision_hour is None else decision_hour.qualifies,
        "proxy_median": hour.proxy_median,
        "proxy_min": hour.proxy_min,
        "proxy_max": hour.proxy_max,
        "proxy_stddev": hour.proxy_stddev,
        "mid_cloud_median": hour.mid_cloud_median,
        "visibility_median_km": hour.visibility_median_km,
        "precip_median": hour.precip_median,
        "humidity_median": hour.humidity_median,
        "model_count": hour.model_count,
        "full_model_count": hour.full_model_count,
        "partial_model_count": hour.partial_model_count,
        "models_good_proxy": hour.models_good_proxy,
        "models_good_mid_cloud": hour.models_good_mid_cloud,
        "models_good_visibility": hour.models_good_visibility,
        "models_good_precip": hour.models_good_precip,
        "consensus": hour.consensus_label,
        "outlier_models": list(hour.outlier_models),
        "stability": stability_payload(stability),
        "models": [
            {
                "model": member.model,
                "proxy": member.proxy.score,
                "mid_cloud_pct": member.record.cloud_mid_pct,
                "visibility_km": member.record.visibility_km,
                "precip_probability": member.record.precipitation_probability_pct,
                "humidity": member.record.relative_humidity_pct,
                "full_model": member.full_model,
                "outlier": member.outlier,
            }
            for member in hour.members
        ],
    }


def model_diagnostics(result: ConsensusResult) -> list[dict[str, object]]:
    return [
        {
            "model": member.model,
            "status": "FULL" if member.full_forecast else "PARTIAL",
            "supported": member.capability.supported,
            "variables_available": sorted(member.capability.variables_available),
            "missing_required": sorted(member.capability.missing_required),
            "missing_optional": sorted(member.capability.missing_optional),
            "error": member.capability.error,
        }
        for member in result.members
    ]


def trend_payload(metrics: StabilityMetrics, *, variable: str = "proxy") -> dict[str, object]:
    if variable not in {"proxy", "mid_cloud", "visibility"}:
        variable = "proxy"
    return {
        "variable": variable,
        "trend": metrics.trend_label,
        "confidence": metrics.confidence,
        "samples": metrics.samples,
        "latest_proxy": metrics.latest_proxy,
        "previous_proxy": metrics.previous_proxy,
        "delta_last_snapshot": metrics.delta_last_snapshot,
        "delta_6h": metrics.delta_6h,
        "delta_12h": metrics.delta_12h,
        "delta_24h": metrics.delta_24h,
        "recent_proxy_mean": metrics.recent_proxy_mean,
        "recent_proxy_stddev": metrics.recent_proxy_stddev,
        "points": [
            {
                "retrieved_at": canonical_iso(point.retrieved_at),
                "value": _point_value(point, variable),
                "proxy": point.proxy,
                "mid_cloud_pct": point.mid_cloud_pct,
                "visibility_km": point.visibility_km,
                "model_count": point.model_count,
            }
            for point in metrics.points
        ],
    }


def window_payload(window: DecisionWindow | None) -> dict[str, object] | None:
    if window is None:
        return None
    peak = window.peak.consensus
    return {
        "start": canonical_iso(window.start),
        "end": canonical_iso(window.end),
        "duration_hours": window.duration_hours,
        "peak_time": canonical_iso(peak.valid_time),
        "peak_proxy_median": window.peak_proxy,
        "mean_proxy": window.mean_proxy,
        "minimum_proxy": window.minimum_proxy,
        "consensus": window.consensus_label,
        "stability_confidence": window.stability_confidence,
        "trend": window.trend_label,
        "mid_cloud_max": window.mid_cloud_max,
        "visibility_min_km": window.visibility_min,
        "models_good_proxy": peak.models_good_proxy,
        "full_model_count": peak.full_model_count,
        "partial_model_count": peak.partial_model_count,
        "proxy_min": peak.proxy_min,
        "proxy_max": peak.proxy_max,
        "mid_cloud_median": peak.mid_cloud_median,
        "visibility_median_km": peak.visibility_median_km,
        "precip_median": peak.precip_median,
    }


def stability_payload(metrics: StabilityMetrics | None) -> dict[str, object]:
    if metrics is None:
        return {
            "trend": "UNKNOWN",
            "confidence": "UNKNOWN",
            "samples": 0,
            "delta_6h": None,
            "delta_12h": None,
            "delta_24h": None,
            "recent_proxy_stddev": None,
        }
    return {
        "trend": metrics.trend_label,
        "confidence": metrics.confidence,
        "samples": metrics.samples,
        "delta_last_snapshot": metrics.delta_last_snapshot,
        "delta_6h": metrics.delta_6h,
        "delta_12h": metrics.delta_12h,
        "delta_24h": metrics.delta_24h,
        "recent_proxy_mean": metrics.recent_proxy_mean,
        "recent_proxy_stddev": metrics.recent_proxy_stddev,
    }


def _point_value(point: StabilityPoint, variable: str) -> float | None:
    if variable == "mid_cloud":
        return point.mid_cloud_pct
    if variable == "visibility":
        return point.visibility_km
    return point.proxy


def _default_selected_date(result: DecisionResult, dates: Iterable[date]) -> date | None:
    if result.winner is not None:
        return result.winner.date
    return next(iter(dates), None)
