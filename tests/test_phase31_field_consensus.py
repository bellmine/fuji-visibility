from __future__ import annotations

from datetime import date, datetime

from fuji_visibility.consensus import ConsensusHour, ConsensusResult, FieldConsensus
from fuji_visibility.decision import decide_days
from fuji_visibility.models import ModelCapability


JST = "+09:00"


def _evidence(name: str, values: tuple[float, ...], good_votes: int, support: str) -> FieldConsensus:
    return FieldConsensus(
        field=name,
        model_count=len(values),
        values=values,
        median=sorted(values)[len(values) // 2] if values else None,
        minimum=min(values) if values else None,
        maximum=max(values) if values else None,
        stddev=0.0,
        good_votes=good_votes,
        support=support,
        good_threshold=25.0,
        good_when="below_or_equal",
    )


def _hour(
    hour: int,
    proxies: tuple[float, ...],
    *,
    mid_support: str = "STRONG_SUPPORT",
    mid_values: tuple[float, ...] = (10.0, 12.0, 15.0, 18.0, 20.0),
    precip_support: str = "MODERATE_SUPPORT",
    precip_values: tuple[float, ...] = (10.0, 20.0, 25.0),
    trend: str = "STABLE",
) -> ConsensusHour:
    full_count = len(proxies)
    fields = {
        "mid_cloud": _evidence("mid_cloud", mid_values, len(mid_values), mid_support),
        "precipitation": _evidence("precipitation", precip_values, len(precip_values), precip_support),
        "visibility": _evidence("visibility", (28.0, 32.0), 2, "MODERATE_SUPPORT"),
        "humidity": _evidence("humidity", (55.0, 60.0, 65.0), 3, "STRONG_SUPPORT"),
    }
    return ConsensusHour(
        valid_time=datetime.fromisoformat(f"2026-08-26T{hour:02d}:00:00{JST}"),
        model_count=5,
        full_model_count=full_count,
        partial_model_count=5 - full_count,
        proxy_median=float(sorted(proxies)[len(proxies) // 2]),
        proxy_min=min(proxies),
        proxy_max=max(proxies),
        proxy_stddev=0.0,
        mid_cloud_median=15.0,
        mid_cloud_min=10.0,
        mid_cloud_max=20.0,
        mid_cloud_stddev=0.0,
        visibility_median_km=30.0,
        visibility_min_km=28.0,
        visibility_max_km=32.0,
        visibility_stddev_km=0.0,
        precip_median=20.0,
        humidity_median=60.0,
        models_good_proxy=full_count,
        models_good_mid_cloud=len(mid_values),
        models_good_visibility=2,
        models_good_precip=len(precip_values),
        consensus_label="MEDIUM",
        outlier_models=(),
        members=(),
        full_proxy_model_count=full_count,
        proxy_values=proxies,
        proxy_spread=max(proxies) - min(proxies),
        mid_cloud_model_count=len(mid_values),
        mid_cloud_values=mid_values,
        mid_cloud_good_votes=len(mid_values),
        visibility_model_count=2,
        visibility_values_km=(28.0, 32.0),
        visibility_good_votes=2,
        precip_model_count=len(precip_values),
        precip_values=precip_values,
        precip_good_votes=len(precip_values),
        humidity_model_count=3,
        humidity_values=(55.0, 60.0, 65.0),
        humidity_good_votes=3,
        field_consensus=fields,
    )


def _result(*hours: ConsensusHour) -> ConsensusResult:
    return ConsensusResult(
        requested_models=("auto", "gfs_seamless", "ecmwf_ifs025", "jma_msm", "jma_gsm"),
        members=(),
        failures=(),
        hours=hours,
        requested_lat=35.52,
        requested_lon=138.75,
    )


def test_capability_classification_exposes_field_supports() -> None:
    capability = ModelCapability(
        model="ecmwf_ifs025",
        supported=True,
        variables_available={"cloud_cover_mid", "precipitation_probability", "relative_humidity_2m"},
        missing_required=set(),
        missing_optional={"visibility"},
    )
    assert capability.status == "PARTIAL_USEFUL"
    assert capability.supports == {
        "proxy": False,
        "mid_cloud": True,
        "visibility": False,
        "precipitation": True,
        "humidity": True,
    }


def test_good_two_source_proxy_becomes_promising_and_groups_window() -> None:
    result = decide_days(
        [(date(2026, 8, 26), _result(_hour(11, (73.2, 78.5)), _hour(12, (74.0, 79.0))))],
        hours=(11, 12),
    )
    assert result.status == "PROMISING"
    assert result.promising_winner is not None
    assert result.promising_winner.best_promising_window is not None
    assert result.promising_winner.best_promising_window.duration_hours == 2
    assert result.promising_winner.best_promising_window.peak.consensus.field_consensus["mid_cloud"].support == "STRONG_SUPPORT"


def test_severe_proxy_disagreement_is_not_a_qualifying_window() -> None:
    result = decide_days(
        [(date(2026, 8, 26), _result(_hour(11, (52.0, 88.0)), _hour(12, (52.0, 88.0))))],
        hours=(11, 12),
    )
    assert result.status == "NO QUALIFYING WINDOW"
    assert result.days[0].hours[0].status == "MODEL_DISAGREEMENT"
    assert result.days[0].hours[0].confidence == "LOW"


def test_low_score_and_insufficient_core_data_are_distinct() -> None:
    low = decide_days(
        [(date(2026, 8, 26), _result(_hour(11, (66.0, 70.0)), _hour(12, (66.0, 70.0))))],
        hours=(11, 12),
    )
    assert low.status == "NO QUALIFYING WINDOW"
    assert low.days[0].hours[0].status == "LOW_SCORE"

    insufficient = decide_days(
        [(date(2026, 8, 26), _result(_hour(11, (78.0,)), _hour(12, (78.0,))))],
        hours=(11, 12),
    )
    assert insufficient.status == "INSUFFICIENT EVIDENCE"
    assert insufficient.days[0].hours[0].status == "INSUFFICIENT_CORE_DATA"


def test_opposed_mid_cloud_blocks_formal_recommendation() -> None:
    result = decide_days(
        [
            (
                date(2026, 8, 26),
                _result(
                    _hour(11, (82.0, 84.0), mid_support="OPPOSED", mid_values=(60, 65, 70, 75, 80)),
                    _hour(12, (82.0, 84.0), mid_support="OPPOSED", mid_values=(60, 65, 70, 75, 80)),
                ),
            )
        ],
        hours=(11, 12),
    )
    assert result.status == "NO QUALIFYING WINDOW"
    assert result.days[0].hours[0].status == "FIELD_CONSENSUS_WEAK"
    assert "MID_CLOUD_OPPOSED" in result.days[0].hours[0].qualification_reasons


def test_volatile_history_reduces_confidence_without_becoming_bad_weather() -> None:
    result = decide_days(
        [(date(2026, 8, 26), _result(_hour(11, (78.0, 80.0)), _hour(12, (78.0, 80.0))))],
        hours=(11, 12),
        stability_by_time={
            hour.valid_time.isoformat(): type("Metrics", (), {"trend_label": "VOLATILE", "confidence": "HIGH"})()
            for hour in _result(_hour(11, (78.0, 80.0)), _hour(12, (78.0, 80.0))).hours
        },
    )
    assert result.status == "PROMISING"
    assert result.confidence == "LOW"
