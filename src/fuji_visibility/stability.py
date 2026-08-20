"""Forecast stability and confidence metrics derived from saved snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, pstdev
from typing import Iterable, Sequence

from .config import (
    STABILITY_HIGH_MIN_SNAPSHOTS,
    STABILITY_IMPROVING_DELTA,
    STABILITY_LARGE_REVERSAL,
    STABILITY_MEDIUM_STDDEV,
    STABILITY_MID_CLOUD_HIGH_STDDEV,
    STABILITY_MIN_SNAPSHOTS,
    STABILITY_STABLE_STDDEV,
    STABILITY_VOLATILE_STDDEV,
    STABILITY_WORSENING_DELTA,
)
from .consensus import _stddev
from .models import StoredForecast
from .scoring import proxy_score


@dataclass(frozen=True)
class StabilityPoint:
    retrieved_at: datetime
    proxy: float | None
    mid_cloud_pct: float | None
    visibility_km: float | None
    model_count: int | None = None
    full_model_count: int | None = None


@dataclass(frozen=True)
class StabilityMetrics:
    samples: int
    latest_retrieved_at: datetime | None
    latest_proxy: float | None
    previous_proxy: float | None
    delta_last_snapshot: float | None
    delta_6h: float | None
    delta_12h: float | None
    delta_24h: float | None
    recent_proxy_mean: float | None
    recent_proxy_stddev: float | None
    recent_mid_cloud_mean: float | None
    recent_mid_cloud_stddev: float | None
    recent_visibility_mean: float | None
    recent_visibility_stddev: float | None
    consecutive_improving: int
    consecutive_worsening: int
    trend_label: str
    confidence: str
    points: tuple[StabilityPoint, ...]

    @property
    def stability_label(self) -> str:
        return self.confidence


def model_stability(
    rows: Iterable[StoredForecast],
    *,
    cloud_strategy: str = "mid",
    history_hours: int = 24,
) -> StabilityMetrics:
    points = [
        StabilityPoint(
            retrieved_at=row.retrieved_at,
            proxy=proxy_score(row, cloud_strategy).score,
            mid_cloud_pct=row.cloud_mid_pct,
            visibility_km=row.visibility_km,
        )
        for row in rows
    ]
    return calculate_stability(points, history_hours=history_hours)


def consensus_stability(
    rows: Iterable[StoredForecast],
    *,
    cloud_strategy: str = "mid",
    history_hours: int = 24,
) -> StabilityMetrics:
    """Aggregate same-retrieval model rows before calculating drift."""

    # Multi-model snapshot collection performs one request per model, so the
    # retrieval timestamps can differ by a few seconds. Cluster rows that were
    # collected within ten minutes into one derived consensus observation;
    # normal 3-hour+ scheduled collections remain separate.
    ordered_rows = sorted(rows, key=lambda row: row.retrieved_at)
    grouped_rows: list[list[StoredForecast]] = []
    grouped_models: list[set[str]] = []
    for row in ordered_rows:
        starts_new_collection = (
            not grouped_rows
            or row.retrieved_at - grouped_rows[-1][-1].retrieved_at > timedelta(minutes=10)
            or row.model in grouped_models[-1]
        )
        if starts_new_collection:
            grouped_rows.append([row])
            grouped_models.append({row.model})
        else:
            grouped_rows[-1].append(row)
            grouped_models[-1].add(row.model)
    points: list[StabilityPoint] = []
    for group in grouped_rows:
        proxy_values: list[float] = []
        for row in group:
            score = proxy_score(row, cloud_strategy).score
            if score is not None:
                proxy_values.append(score)
        mid_values = [row.cloud_mid_pct for row in group if row.cloud_mid_pct is not None]
        visibility_values = [row.visibility_km for row in group if row.visibility_km is not None]
        points.append(
            StabilityPoint(
                retrieved_at=group[0].retrieved_at,
                proxy=float(_median(proxy_values)) if proxy_values else None,
                mid_cloud_pct=float(_median(mid_values)) if mid_values else None,
                visibility_km=float(_median(visibility_values)) if visibility_values else None,
                model_count=len(group),
                full_model_count=len(proxy_values),
            )
        )
    return calculate_stability(points, history_hours=history_hours)


def calculate_stability(
    points: Iterable[StabilityPoint],
    *,
    history_hours: int = 24,
) -> StabilityMetrics:
    if history_hours <= 0:
        raise ValueError("history_hours must be positive")
    ordered = sorted(points, key=lambda point: point.retrieved_at)
    if not ordered:
        return StabilityMetrics(
            samples=0,
            latest_retrieved_at=None,
            latest_proxy=None,
            previous_proxy=None,
            delta_last_snapshot=None,
            delta_6h=None,
            delta_12h=None,
            delta_24h=None,
            recent_proxy_mean=None,
            recent_proxy_stddev=None,
            recent_mid_cloud_mean=None,
            recent_mid_cloud_stddev=None,
            recent_visibility_mean=None,
            recent_visibility_stddev=None,
            consecutive_improving=0,
            consecutive_worsening=0,
            trend_label="UNKNOWN",
            confidence="UNKNOWN",
            points=(),
        )
    latest_time = ordered[-1].retrieved_at
    cutoff = latest_time - timedelta(hours=history_hours)
    recent = [point for point in ordered if point.retrieved_at >= cutoff]
    proxy_points = [point for point in recent if point.proxy is not None]
    proxy_values = [point.proxy for point in proxy_points if point.proxy is not None]
    mid_values = [point.mid_cloud_pct for point in recent if point.mid_cloud_pct is not None]
    visibility_values = [point.visibility_km for point in recent if point.visibility_km is not None]
    latest_proxy = proxy_points[-1].proxy if proxy_points else None
    previous_proxy = proxy_points[-2].proxy if len(proxy_points) >= 2 else None
    differences = [
        current.proxy - previous.proxy
        for previous, current in zip(proxy_points, proxy_points[1:])
        if previous.proxy is not None and current.proxy is not None
    ]
    delta_6h = _delta_at_or_before(proxy_points, latest_time, timedelta(hours=6))
    delta_12h = _delta_at_or_before(proxy_points, latest_time, timedelta(hours=12))
    delta_24h = _delta_at_or_before(proxy_points, latest_time, timedelta(hours=24))
    recent_proxy_stddev = _stddev(proxy_values)
    recent_mid_stddev = _stddev(mid_values)
    large_reversal = _has_large_reversal(differences)
    volatile = bool(
        (recent_proxy_stddev is not None and recent_proxy_stddev > STABILITY_VOLATILE_STDDEV)
        or large_reversal
    )
    if latest_proxy is None or len(proxy_points) < 2:
        trend_label = "UNKNOWN"
    elif volatile:
        trend_label = "VOLATILE"
    elif (
        delta_6h is not None
        and previous_proxy is not None
        and latest_proxy >= previous_proxy
        and delta_6h >= STABILITY_IMPROVING_DELTA
    ):
        trend_label = "IMPROVING"
    elif (
        delta_6h is not None
        and previous_proxy is not None
        and latest_proxy <= previous_proxy
        and delta_6h <= STABILITY_WORSENING_DELTA
    ):
        trend_label = "WORSENING"
    elif (
        delta_6h is not None
        and abs(delta_6h) < STABILITY_IMPROVING_DELTA
        and (recent_proxy_stddev is None or recent_proxy_stddev <= STABILITY_STABLE_STDDEV)
    ):
        trend_label = "STABLE"
    else:
        trend_label = "UNKNOWN"
    confidence = _confidence(
        len(proxy_points),
        recent_proxy_stddev,
        recent_mid_stddev,
        large_reversal,
    )
    return StabilityMetrics(
        samples=len(recent),
        latest_retrieved_at=latest_time,
        latest_proxy=latest_proxy,
        previous_proxy=previous_proxy,
        delta_last_snapshot=(
            None if latest_proxy is None or previous_proxy is None else latest_proxy - previous_proxy
        ),
        delta_6h=delta_6h,
        delta_12h=delta_12h,
        delta_24h=delta_24h,
        recent_proxy_mean=_mean(proxy_values),
        recent_proxy_stddev=recent_proxy_stddev,
        recent_mid_cloud_mean=_mean(mid_values),
        recent_mid_cloud_stddev=recent_mid_stddev,
        recent_visibility_mean=_mean(visibility_values),
        recent_visibility_stddev=_stddev(visibility_values),
        consecutive_improving=_consecutive(differences, improving=True),
        consecutive_worsening=_consecutive(differences, improving=False),
        trend_label=trend_label,
        confidence=confidence,
        points=tuple(recent),
    )


def _confidence(
    sample_count: int,
    proxy_stddev: float | None,
    mid_stddev: float | None,
    large_reversal: bool,
) -> str:
    if sample_count < STABILITY_MIN_SNAPSHOTS or proxy_stddev is None:
        return "UNKNOWN"
    if (
        sample_count >= STABILITY_HIGH_MIN_SNAPSHOTS
        and proxy_stddev <= STABILITY_STABLE_STDDEV
        and mid_stddev is not None
        and mid_stddev <= STABILITY_MID_CLOUD_HIGH_STDDEV
        and not large_reversal
    ):
        return "HIGH"
    if sample_count >= STABILITY_MIN_SNAPSHOTS and proxy_stddev <= STABILITY_MEDIUM_STDDEV:
        return "MEDIUM"
    return "LOW"


def _delta_at_or_before(
    points: Sequence[StabilityPoint], latest_time: datetime, offset: timedelta
) -> float | None:
    scored = [point for point in points if point.proxy is not None]
    if not scored:
        return None
    candidates = [point for point in scored if point.retrieved_at <= latest_time - offset]
    if not candidates:
        return None
    current = scored[-1].proxy
    prior = candidates[-1].proxy
    return None if current is None or prior is None else current - prior


def _has_large_reversal(differences: Sequence[float]) -> bool:
    if any(abs(value) >= STABILITY_LARGE_REVERSAL for value in differences):
        return True
    for previous, current in zip(differences, differences[1:]):
        if previous * current < 0 and abs(previous) >= STABILITY_IMPROVING_DELTA and abs(current) >= STABILITY_IMPROVING_DELTA:
            return True
    return False


def _consecutive(differences: Sequence[float], *, improving: bool) -> int:
    count = 0
    for difference in reversed(differences):
        is_direction = difference >= 0.5 if improving else difference <= -0.5
        if is_direction:
            count += 1
        else:
            break
    return count


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else float(mean(values))


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return float((ordered[middle - 1] + ordered[middle]) / 2)
