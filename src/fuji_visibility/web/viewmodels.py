"""JSON-safe view models for templates and dashboard API responses."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Iterable

from ..consensus import ConsensusHour, ConsensusResult
from ..decision import DecisionDay, DecisionHour, DecisionResult, DecisionWindow
from ..services import DashboardData
from ..stability import StabilityMetrics, StabilityPoint
from ..time_utils import canonical_iso, to_jst
from .i18n import (
    CONSENSUS_LABELS,
    DECISION_LABELS,
    DECISION_REASON_LABELS,
    FIELD_SUPPORT_LABELS,
    FRESHNESS_LABELS,
    HOUR_STATUS_LABELS,
    MODEL_STATUS_LABELS,
    PROXY_AGREEMENT_LABELS,
    REFRESH_STATUS_LABELS,
    STABILITY_LABELS,
    TREND_LABELS,
    label,
    localized_coverage,
    localized_date,
    localized_rationale,
)


def dashboard_payload(data: DashboardData, *, selected_date: date | None = None) -> dict[str, object]:
    result_by_date = {target_date: result for target_date, result in data.daily_results}
    day_by_date = {day.date: day for day in data.decision.days}
    selected = selected_date or _default_selected_date(data.decision, data.dates)
    selected_result = result_by_date.get(selected)
    days = [
        day_payload(
            target_date,
            result_by_date.get(target_date),
            day_by_date.get(target_date),
            data.stability_by_time,
        )
        for target_date in data.dates
    ]
    status = {
        **data.status,
        "freshness_label": label(FRESHNESS_LABELS, str(data.status.get("freshness"))),
        "last_refresh_status_label": label(
            REFRESH_STATUS_LABELS, str(data.status.get("last_refresh_status"))
        ),
        "coverage_label": localized_coverage(
            int(data.status.get("full_models", 0)),
            int(data.status.get("configured_models", 0)),
        ),
    }
    return {
        "generated_at": canonical_iso(datetime.now().astimezone()),
        "selected_date": None if selected_result is None else selected.isoformat(),
        "status": status,
        "decision": decision_payload(data.decision),
        "days": days,
        # Keep the browser bootstrap payload free of internal English state labels.
        "client": {
            "status": {"location": data.status.get("location", "")},
            "days": [
                {
                    "date": day["date"],
                    "hours": [{"local_time": hour["local_time"]} for hour in day["hours"]],
                }
                for day in days
            ],
        },
    }


def decision_payload(result: DecisionResult) -> dict[str, object]:
    def decision_hour_payload(hour: DecisionHour) -> dict[str, object]:
        consensus = hour.consensus
        return {
            "valid_time": canonical_iso(consensus.valid_time),
            "reachable": hour.reachable,
            "qualifies": hour.qualifies,
            "status": hour.status,
            "confidence": hour.confidence,
            "decision_reasons": list(hour.decision_reasons),
            "proxy": consensus.proxy_payload,
            "field_consensus": _localized_field_consensus(consensus.field_consensus_summary),
        }

    return {
        "status": result.status,
        "status_label": label(DECISION_LABELS, result.status),
        "winner_date": None if result.winner is None else result.winner.date.isoformat(),
        "winner_date_label": None if result.winner is None else localized_date(result.winner.date),
        "promising_winner_date": (
            None if result.promising_winner is None else result.promising_winner.date.isoformat()
        ),
        "promising_winner_date_label": (
            None
            if result.promising_winner is None
            else localized_date(result.promising_winner.date)
        ),
        "no_clear_winner": result.no_clear_winner,
        "confidence": result.confidence,
        "confidence_label": _confidence_label(result.confidence),
        "decision_reasons": list(result.decision_reasons),
        "field_consensus_summary": _localized_field_consensus(result.field_consensus_summary),
        "insufficient_evidence": result.insufficient_evidence,
        "min_proxy": result.min_proxy,
        "min_window_hours": result.min_window_hours,
        "rationale": list(result.rationale),
        "rationale_label": localized_rationale(result.rationale),
        "days": [
            {
                "date": day.date.isoformat(),
                "best_window": window_payload(day.best_window),
                "windows": [window_payload(window) for window in day.windows],
                "best_promising_window": window_payload(day.best_promising_window),
                "promising_windows": [
                    window_payload(window) for window in day.promising_windows
                ],
                "hours": [decision_hour_payload(hour) for hour in day.hours],
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
            "label": localized_date(target_date),
            "best_window": None,
            "best_promising_window": None,
            "status": "INSUFFICIENT EVIDENCE",
            "status_label": label(DECISION_LABELS, "INSUFFICIENT EVIDENCE"),
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
        "label": localized_date(target_date),
        "best_window": window_payload(decision_day.best_window if decision_day else None),
        "best_promising_window": window_payload(
            decision_day.best_promising_window if decision_day else None
        ),
        "status": _day_status(decision_day),
        "status_label": label(DECISION_LABELS, _day_status(decision_day)),
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
        "status": "OTHER" if decision_hour is None else decision_hour.status,
        "status_label": label(
            HOUR_STATUS_LABELS,
            "OTHER" if decision_hour is None else decision_hour.status,
            default="暂无法判断",
        ),
        "confidence": "INSUFFICIENT" if decision_hour is None else decision_hour.confidence,
        "confidence_label": _confidence_label(
            "INSUFFICIENT" if decision_hour is None else decision_hour.confidence
        ),
        "decision_reasons": [] if decision_hour is None else list(decision_hour.decision_reasons),
        "decision_reasons_label": (
            []
            if decision_hour is None
            else [DECISION_REASON_LABELS.get(reason, "暂无更多判断说明") for reason in decision_hour.decision_reasons]
        ),
        "qualification_reasons": (
            [] if decision_hour is None else list(decision_hour.qualification_reasons)
        ),
        "qualification_reasons_label": (
            []
            if decision_hour is None
            else [DECISION_REASON_LABELS.get(reason, "暂无更多判断说明") for reason in decision_hour.qualification_reasons]
        ),
        "proxy_median": hour.proxy_median,
        "proxy_min": hour.proxy_min,
        "proxy_max": hour.proxy_max,
        "proxy_stddev": hour.proxy_stddev,
        "proxy": {
            **hour.proxy_payload,
            "agreement_label": label(PROXY_AGREEMENT_LABELS, hour.proxy_agreement),
        },
        "mid_cloud_median": hour.mid_cloud_median,
        "visibility_median_km": hour.visibility_median_km,
        "precip_median": hour.precip_median,
        "humidity_median": hour.humidity_median,
        "model_count": hour.model_count,
        "full_model_count": hour.full_model_count,
        "full_proxy_model_count": hour.full_proxy_model_count,
        "partial_model_count": hour.partial_model_count,
        "models_good_proxy": hour.models_good_proxy,
        "models_good_mid_cloud": hour.models_good_mid_cloud,
        "models_good_visibility": hour.models_good_visibility,
        "models_good_precip": hour.models_good_precip,
        "mid_cloud_model_count": hour.mid_cloud_model_count,
        "visibility_model_count": hour.visibility_model_count,
        "precip_model_count": hour.precip_model_count,
        "humidity_model_count": hour.humidity_model_count,
        "field_consensus": _localized_field_consensus(hour.field_consensus_summary),
        "consensus": hour.consensus_label,
        "consensus_label": label(CONSENSUS_LABELS, hour.consensus_label),
        "reachability_label": "可到达" if (decision_hour is None or decision_hour.reachable) else "到达前",
        "window_label": "符合条件" if (decision_hour is not None and decision_hour.qualifies) else "不符合条件",
        "coverage_label": localized_coverage(hour.full_model_count, hour.model_count),
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
                    "capability_status": member.capability_status,
                    "capability_status_label": label(MODEL_STATUS_LABELS, member.capability_status),
                    "supports": member.supports,
                "outlier": member.outlier,
            }
            for member in hour.members
        ],
    }


def model_diagnostics(result: ConsensusResult) -> list[dict[str, object]]:
    return [
        {
            "model": member.model,
            "status": member.capability.status,
            "status_label": label(
                MODEL_STATUS_LABELS, member.capability.status
            ),
            "supported": member.capability.supported,
            "supports": member.capability.supports,
            "support_labels": {
                name: "有" if supported else "—"
                for name, supported in member.capability.supports.items()
            },
            "usable_fields": list(member.capability.usable_fields),
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
        "trend_label": label(TREND_LABELS, metrics.trend_label),
        "confidence": metrics.confidence,
        "confidence_label": label(STABILITY_LABELS, metrics.confidence),
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
        "consensus_label": label(CONSENSUS_LABELS, window.consensus_label),
        "stability_confidence": window.stability_confidence,
        "stability_confidence_label": label(STABILITY_LABELS, window.stability_confidence),
        "trend": window.trend_label,
        "trend_label": label(TREND_LABELS, window.trend_label),
        "status": window.status,
        "status_label": label(DECISION_LABELS, "RECOMMENDED" if window.status == "QUALIFIES" else "PROMISING"),
        "confidence": window.confidence,
        "confidence_label": _confidence_label(window.confidence),
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
        "field_consensus": _localized_field_consensus(peak.field_consensus_summary),
    }


def stability_payload(metrics: StabilityMetrics | None) -> dict[str, object]:
    if metrics is None:
        return {
            "trend": "UNKNOWN",
            "trend_label": label(TREND_LABELS, "UNKNOWN"),
            "confidence": "UNKNOWN",
            "confidence_label": label(STABILITY_LABELS, "UNKNOWN"),
            "samples": 0,
            "delta_6h": None,
            "delta_12h": None,
            "delta_24h": None,
            "recent_proxy_stddev": None,
        }
    return {
        "trend": metrics.trend_label,
        "trend_label": label(TREND_LABELS, metrics.trend_label),
        "confidence": metrics.confidence,
        "confidence_label": label(STABILITY_LABELS, metrics.confidence),
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
    if result.promising_winner is not None:
        return result.promising_winner.date
    return next(iter(dates), None)


def _confidence_label(value: str | None) -> str:
    if value == "INSUFFICIENT":
        return "数据不足"
    return label(STABILITY_LABELS, value, default="未知")


def _localized_field_consensus(
    values: dict[str, dict[str, object]] | None,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for name, evidence in (values or {}).items():
        item = dict(evidence)
        support = str(item.get("support", "INSUFFICIENT"))
        item["support_label"] = label(FIELD_SUPPORT_LABELS, support)
        if name == "visibility":
            item["median_km"] = item.get("median")
            item["values_km"] = item.get("values", [])
        result[name] = item
    return result


def _day_status(day: DecisionDay | None) -> str:
    if day is None:
        return "INSUFFICIENT EVIDENCE"
    if day.best_window is not None:
        return "RECOMMENDED"
    if day.best_promising_window is not None:
        return "PROMISING"
    if day.hours and all(hour.status in {"INSUFFICIENT_CORE_DATA", "BEFORE_ARRIVAL"} for hour in day.hours):
        return "INSUFFICIENT EVIDENCE"
    return "NO QUALIFYING WINDOW"
