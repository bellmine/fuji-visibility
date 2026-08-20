from __future__ import annotations

from datetime import datetime, timedelta

from fuji_visibility.stability import StabilityPoint, calculate_stability


def _points(values, *, mid=10):
    start = datetime.fromisoformat("2026-08-20T08:00:00+09:00")
    return [
        StabilityPoint(
            retrieved_at=start + timedelta(hours=index * 6),
            proxy=value,
            mid_cloud_pct=mid + index % 2,
            visibility_km=35 + index,
        )
        for index, value in enumerate(values)
    ]


def test_improving_series_has_high_stability_confidence():
    metrics = calculate_stability(_points((70, 72, 78, 84)))
    assert metrics.trend_label == "IMPROVING"
    assert metrics.confidence == "HIGH"
    assert metrics.delta_6h == 6
    assert metrics.delta_12h == 12


def test_volatile_series_is_low_confidence():
    metrics = calculate_stability(_points((55, 91, 60, 90)))
    assert metrics.trend_label == "VOLATILE"
    assert metrics.confidence == "LOW"


def test_insufficient_history_is_unknown():
    metrics = calculate_stability(_points((82, 84)))
    assert metrics.confidence == "UNKNOWN"
    assert metrics.trend_label == "STABLE"
