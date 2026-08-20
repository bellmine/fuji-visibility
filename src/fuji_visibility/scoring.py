"""Transparent Fuji Proxy Score calculations."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .config import PROXY_WEIGHTS, SCORE_BREAKPOINTS
from .models import ComponentScores, HourlyForecast, ProxyScore

CLOUD_STRATEGIES = (
    "total",
    "mid",
    "low_mid_max",
    "low_mid_weighted",
    "mid_high_weighted",
)


def linear_piecewise(value: float | None, breakpoints: Sequence[tuple[float, float]]) -> float | None:
    """Interpolate between breakpoints and clamp outside their range."""

    if value is None or not math.isfinite(value):
        return None
    if not breakpoints:
        raise ValueError("at least one score breakpoint is required")
    points = sorted(breakpoints)
    if value <= points[0][0]:
        return float(points[0][1])
    if value >= points[-1][0]:
        return float(points[-1][1])
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        if left_x <= value <= right_x:
            if right_x == left_x:
                return float(right_y)
            ratio = (value - left_x) / (right_x - left_x)
            return float(left_y + ratio * (right_y - left_y))
    return float(points[-1][1])


def effective_cloud_pct(record: HourlyForecast, strategy: str = "mid") -> float | None:
    """Return the cloud field used by the proxy, without hiding missing inputs."""

    if strategy not in CLOUD_STRATEGIES:
        choices = ", ".join(CLOUD_STRATEGIES)
        raise ValueError(f"unknown cloud strategy {strategy!r}; choose one of {choices}")
    if strategy == "total":
        return record.cloud_total_pct
    if strategy == "mid":
        return record.cloud_mid_pct
    if strategy == "low_mid_max":
        if record.cloud_low_pct is None or record.cloud_mid_pct is None:
            return None
        return max(record.cloud_low_pct, record.cloud_mid_pct)
    if strategy == "low_mid_weighted":
        if record.cloud_low_pct is None or record.cloud_mid_pct is None:
            return None
        return 0.35 * record.cloud_low_pct + 0.65 * record.cloud_mid_pct
    if record.cloud_mid_pct is None or record.cloud_high_pct is None:
        return None
    return 0.75 * record.cloud_mid_pct + 0.25 * record.cloud_high_pct


def score_components(
    record: HourlyForecast,
    *,
    cloud_strategy: str = "mid",
) -> tuple[ComponentScores, float | None, tuple[str, ...]]:
    cloud = effective_cloud_pct(record, cloud_strategy)
    components = ComponentScores(
        visibility=linear_piecewise(record.visibility_km, SCORE_BREAKPOINTS["visibility"]),
        cloud=linear_piecewise(cloud, SCORE_BREAKPOINTS["cloud"]),
        precipitation=linear_piecewise(
            record.precipitation_probability_pct, SCORE_BREAKPOINTS["precipitation"]
        ),
        humidity=linear_piecewise(record.relative_humidity_pct, SCORE_BREAKPOINTS["humidity"]),
    )

    missing: list[str] = []
    if record.visibility_m is None:
        missing.append("visibility")
    if cloud is None:
        missing.append(f"cloud ({cloud_strategy})")
    if record.precipitation_probability_pct is None:
        missing.append("precipitation_probability")
    if record.relative_humidity_pct is None:
        missing.append("relative_humidity")

    if missing:
        return components, None, tuple(missing)
    assert components.visibility is not None
    assert components.cloud is not None
    assert components.precipitation is not None
    assert components.humidity is not None
    score = (
        components.visibility * PROXY_WEIGHTS["visibility"]
        + components.cloud * PROXY_WEIGHTS["cloud"]
        + components.precipitation * PROXY_WEIGHTS["precipitation"]
        + components.humidity * PROXY_WEIGHTS["humidity"]
    )
    return components, score, ()


def proxy_score(record: HourlyForecast, cloud_strategy: str = "mid") -> ProxyScore:
    components, score, missing = score_components(record, cloud_strategy=cloud_strategy)
    return ProxyScore(
        score=score,
        cloud_strategy=cloud_strategy,
        effective_cloud_pct=effective_cloud_pct(record, cloud_strategy),
        components=components,
        missing_fields=missing,
    )
