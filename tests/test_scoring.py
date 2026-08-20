from __future__ import annotations

import pytest

from fuji_visibility.scoring import effective_cloud_pct, linear_piecewise, proxy_score


def test_piecewise_score_interpolates_and_clamps():
    points = ((0, 100), (20, 80), (100, 0))
    assert linear_piecewise(0, points) == 100
    assert linear_piecewise(10, points) == 90
    assert linear_piecewise(-5, points) == 100
    assert linear_piecewise(150, points) == 0
    assert linear_piecewise(None, points) is None


def test_cloud_strategies(make_hour):
    record = make_hour(
        "2026-08-26T09:00:00+09:00",
        cloud_total_pct=40,
        cloud_low_pct=80,
        cloud_mid_pct=20,
        cloud_high_pct=60,
    )
    assert effective_cloud_pct(record, "total") == 40
    assert effective_cloud_pct(record, "mid") == 20
    assert effective_cloud_pct(record, "low_mid_max") == 80
    assert effective_cloud_pct(record, "low_mid_weighted") == pytest.approx(41)
    assert effective_cloud_pct(record, "mid_high_weighted") == pytest.approx(30)


def test_proxy_score_uses_published_weights_with_explicit_proxy_inputs(make_hour):
    record = make_hour(
        "2026-08-26T09:00:00+09:00",
        relative_humidity_pct=40,
        precipitation_probability_pct=0,
        cloud_mid_pct=0,
        visibility_m=60000,
    )
    score = proxy_score(record)
    # visibility=100, cloud=100, rain=100, humidity=90
    assert score.score == pytest.approx(99)
    assert score.missing_fields == ()


def test_proxy_score_is_unavailable_when_a_required_input_is_missing(make_hour):
    record = make_hour("2026-08-26T09:00:00+09:00", visibility_m=None)
    score = proxy_score(record)
    assert score.score is None
    assert "visibility" in score.missing_fields
