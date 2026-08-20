from __future__ import annotations

from datetime import date

from fuji_visibility.comparison import assess_day, calculate_trend
from fuji_visibility.models import ForecastResult


def test_arrival_cutoff_excludes_earlier_peak(make_hour):
    early = make_hour(
        "2026-08-26T07:00:00+09:00",
        visibility_m=60000,
        cloud_mid_pct=0,
        relative_humidity_pct=35,
        precipitation_probability_pct=0,
    )
    reachable = make_hour(
        "2026-08-26T08:00:00+09:00",
        visibility_m=30000,
        cloud_mid_pct=20,
        relative_humidity_pct=60,
        precipitation_probability_pct=10,
    )
    result = ForecastResult(
        model="auto",
        requested_lat=35.52,
        requested_lon=138.75,
        timezone="Asia/Tokyo",
        retrieved_at=early.retrieved_at,
        hours=[early, reachable],
        raw_payload={},
    )
    comparison = assess_day(
        result,
        date(2026, 8, 26),
        hours=(5, 12),
        arrival_after="08:00",
    )
    assert comparison.assessments[0].reachable is False
    assert comparison.best_window is not None
    assert comparison.best_window.peak.record.valid_time.hour == 8


def test_trend_reports_changes_and_stability(make_hour):
    rows = []
    for index, score_input in enumerate((20_000, 30_000, 40_000)):
        rows.append(
            make_hour(
                "2026-08-26T09:00:00+09:00",
                retrieved_at=f"2026-08-21T{7 + index * 6:02d}:35:00+09:00",
                visibility_m=score_input,
            )
        )
    metrics = calculate_trend(rows)
    assert metrics.samples == 3
    assert metrics.delta_since_previous is not None
    assert metrics.delta_since_previous > 0
    assert metrics.improving_snapshots >= 1
    assert len(metrics.assessments) == 3
