from __future__ import annotations

from datetime import date, datetime

from fuji_visibility.consensus import ConsensusHour, ConsensusResult
from fuji_visibility.decision import decide_days
from fuji_visibility.stability import StabilityPoint, calculate_stability


def _hour(hour, proxy, *, label="HIGH", full=5):
    valid_time = datetime.fromisoformat(f"2026-08-{26 if hour < 24 else 27:02d}T{hour % 24:02d}:00:00+09:00")
    return ConsensusHour(
        valid_time=valid_time,
        model_count=full,
        full_model_count=full,
        partial_model_count=0,
        proxy_median=proxy,
        proxy_min=proxy - 2,
        proxy_max=proxy + 2,
        proxy_stddev=2,
        mid_cloud_median=10,
        mid_cloud_min=8,
        mid_cloud_max=12,
        mid_cloud_stddev=2,
        visibility_median_km=35,
        visibility_min_km=30,
        visibility_max_km=40,
        visibility_stddev_km=2,
        precip_median=5,
        humidity_median=60,
        models_good_proxy=full,
        models_good_mid_cloud=full,
        models_good_visibility=full,
        consensus_label=label,
        outlier_models=(),
        members=(),
    )


def _result(*hours):
    return ConsensusResult(
        requested_models=("a", "b", "c", "d", "e"),
        members=(),
        failures=(),
        hours=tuple(hours),
        requested_lat=35.52,
        requested_lon=138.75,
    )


def _high_stability():
    points = [
        StabilityPoint(
            retrieved_at=datetime.fromisoformat(f"2026-08-20T{8 + index * 4:02d}:00:00+09:00"),
            proxy=80 + index,
            mid_cloud_pct=10,
            visibility_km=35,
        )
        for index in range(4)
    ]
    return calculate_stability(points)


def test_arrival_cutoff_and_window_grouping():
    result = decide_days(
        [(date(2026, 8, 26), _result(_hour(7, 96), _hour(8, 82), _hour(9, 80)))],
        arrival_after="08:00",
        hours=(5, 12),
        min_window_hours=2,
    )
    assert result.winner is not None
    assert result.winner.best_window is not None
    assert result.winner.best_window.start.hour == 8
    assert result.winner.best_window.duration_hours == 2


def test_no_clear_winner_when_difference_is_below_threshold():
    first = _result(_hour(8, 84), _hour(9, 84))
    second = _result(_hour(8, 85), _hour(9, 85))
    stability = {}
    result = decide_days(
        [(date(2026, 8, 26), first), (date(2026, 8, 26), second)],
        hours=(8, 9),
        stability_by_time=stability,
        min_window_hours=2,
        proxy_difference_threshold=5,
    )
    assert result.no_clear_winner is True
    assert result.status == "NO CLEAR WINNER"
