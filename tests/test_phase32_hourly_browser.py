from __future__ import annotations

from datetime import date, datetime

from fuji_visibility.consensus import ConsensusHour, ConsensusResult
from fuji_visibility.decision import decide_days
from fuji_visibility.stability import StabilityMetrics
from fuji_visibility.web.viewmodels import hour_payload


def _hour(
    hour: int,
    proxy: float,
    *,
    spread: float = 0.0,
    agreement: str = "GOOD",
) -> ConsensusHour:
    return ConsensusHour(
        valid_time=datetime.fromisoformat(f"2026-08-26T{hour:02d}:00:00+09:00"),
        model_count=2,
        full_model_count=2,
        partial_model_count=0,
        proxy_median=proxy,
        proxy_min=proxy - spread / 2,
        proxy_max=proxy + spread / 2,
        proxy_stddev=spread / 2,
        mid_cloud_median=10.0,
        mid_cloud_min=8.0,
        mid_cloud_max=12.0,
        mid_cloud_stddev=1.0,
        visibility_median_km=30.0,
        visibility_min_km=28.0,
        visibility_max_km=32.0,
        visibility_stddev_km=2.0,
        precip_median=5.0,
        humidity_median=60.0,
        models_good_proxy=2,
        models_good_mid_cloud=2,
        models_good_visibility=2,
        models_good_precip=2,
        consensus_label="MEDIUM",
        outlier_models=(),
        members=(),
        full_proxy_model_count=2,
        proxy_values=(proxy - spread / 2, proxy + spread / 2),
        proxy_spread=spread,
        proxy_agreement=agreement,
    )


def _result(*hours: ConsensusHour) -> ConsensusResult:
    return ConsensusResult(
        requested_models=("auto", "gfs_seamless"),
        members=(),
        failures=(),
        hours=hours,
        requested_lat=35.52,
        requested_lon=138.75,
    )


def test_best_block_keeps_all_hours_and_ignores_qualification_gate() -> None:
    result = decide_days(
        [
            (
                date(2026, 8, 26),
                _result(*[_hour(hour, proxy) for hour, proxy in zip((8, 9, 10, 11, 12), (61, 67, 72, 76, 77))]),
            )
        ],
        hours=(8, 12),
        best_block_hours=2,
    )

    day = result.days[0]
    assert len(day.hours) == 5
    assert day.best_block is not None
    assert (day.best_block.start.hour, day.best_block.end.hour) == (11, 12)
    assert day.best_block.mean_proxy == 76.5
    assert day.day_rank_score == 76.5
    assert all(not hour.qualifies for hour in day.hours)


def test_severe_disagreement_stays_visible_and_rankable() -> None:
    result = decide_days(
        [(date(2026, 8, 26), _result(_hour(11, 75, spread=40, agreement="SEVERE"), _hour(12, 74, spread=40, agreement="SEVERE")))],
        hours=(11, 12),
    )

    day = result.days[0]
    assert len(day.hours) == 2
    assert day.hours[0].status == "MODEL_DISAGREEMENT"
    assert day.best_block is not None
    assert "MODEL_DISAGREEMENT" in day.best_block.warnings


def test_before_arrival_remains_visible_but_is_excluded_from_block() -> None:
    result = decide_days(
        [(date(2026, 8, 26), _result(_hour(7, 90), _hour(8, 61), _hour(9, 67)))],
        arrival_after="08:00",
        hours=(7, 9),
    )

    day = result.days[0]
    assert [hour.consensus.valid_time.hour for hour in day.hours] == [7, 8, 9]
    assert day.hours[0].reachable is False
    assert day.hours[0].status == "BEFORE_ARRIVAL"
    assert day.best_block is not None
    assert day.best_block.start.hour == 8


def test_bad_day_still_gets_best_available_block() -> None:
    result = decide_days(
        [(date(2026, 8, 26), _result(_hour(8, 30), _hour(9, 45), _hour(10, 40)))],
        hours=(8, 10),
    )

    assert result.days[0].best_block is not None
    assert result.days[0].best_block.mean_proxy == 42.5


def test_hour_view_model_exposes_inline_trend_and_warning() -> None:
    hour = _hour(11, 75, spread=40, agreement="SEVERE")
    stability = StabilityMetrics(
        samples=3,
        latest_retrieved_at=None,
        latest_proxy=75.0,
        previous_proxy=68.0,
        delta_last_snapshot=7.0,
        delta_6h=7.0,
        delta_12h=None,
        delta_24h=None,
        recent_proxy_mean=72.0,
        recent_proxy_stddev=3.0,
        recent_mid_cloud_mean=10.0,
        recent_mid_cloud_stddev=1.0,
        recent_visibility_mean=30.0,
        recent_visibility_stddev=2.0,
        consecutive_improving=1,
        consecutive_worsening=0,
        trend_label="IMPROVING",
        confidence="MEDIUM",
        points=(),
    )

    payload = hour_payload(hour, None, stability, top_rank=1, is_best_block=True)
    assert payload["trend_label"] == "改善"
    assert payload["top_rank_label"] == "最高分"
    assert payload["is_best_block"] is True
    assert payload["warnings"]["labels"] == ["预报来源分歧大"]
