"""Hour filtering, reachable-window ranking, and forecast drift metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from statistics import mean, pstdev
from typing import Iterable

from .models import ForecastResult, HourlyForecast, ProxyScore, StoredForecast
from .scoring import proxy_score
from .time_utils import parse_clock, to_jst


@dataclass(frozen=True)
class HourAssessment:
    record: HourlyForecast
    reachable: bool
    score: ProxyScore


@dataclass(frozen=True)
class BestReachableWindow:
    start: datetime
    end: datetime
    peak: HourAssessment
    tolerance: float


@dataclass(frozen=True)
class DayComparison:
    date: date
    assessments: tuple[HourAssessment, ...]
    best_window: BestReachableWindow | None

    @property
    def peak_score(self) -> float | None:
        return None if self.best_window is None else self.best_window.peak.score.score


@dataclass(frozen=True)
class TrendMetrics:
    valid_time: datetime
    samples: int
    assessments: tuple[HourAssessment, ...]
    latest: HourAssessment | None
    previous: HourAssessment | None
    delta_since_previous: float | None
    delta_6h: float | None
    delta_12h: float | None
    improving_snapshots: int
    worsening_snapshots: int
    score_stddev: float | None
    visibility_trend_km: tuple[float | None, ...]
    mid_cloud_trend_pct: tuple[float | None, ...]
    precipitation_trend_pct: tuple[float | None, ...]
    label: str


def parse_hour_range(value: str) -> tuple[int, int]:
    text = value.strip()
    if "-" not in text:
        hour = int(text)
        if hour < 0 or hour > 23:
            raise ValueError("hour must be between 0 and 23")
        return hour, hour
    left, right = text.split("-", 1)
    start, end = int(left), int(right)
    if not (0 <= start <= 23 and 0 <= end <= 23) or start > end:
        raise ValueError("hours must be an inclusive range such as 5-12")
    return start, end


def assess_day(
    result: ForecastResult,
    target_date: date,
    *,
    hours: tuple[int, int] = (0, 23),
    arrival_after: time | str | None = None,
    cloud_strategy: str = "mid",
) -> DayComparison:
    start_hour, end_hour = hours
    arrival = parse_clock(arrival_after) if isinstance(arrival_after, str) else arrival_after
    selected: list[HourAssessment] = []
    for record in result.hours:
        local = to_jst(record.valid_time)
        if local.date() != target_date or not (start_hour <= local.hour <= end_hour):
            continue
        reachable = arrival is None or local.time().replace(second=0, microsecond=0) >= arrival
        selected.append(HourAssessment(record=record, reachable=reachable, score=proxy_score(record, cloud_strategy)))
    selected.sort(key=lambda item: item.record.valid_time)
    return DayComparison(
        date=target_date,
        assessments=tuple(selected),
        best_window=find_best_reachable_window(selected),
    )


def find_best_reachable_window(
    assessments: Iterable[HourAssessment],
    *,
    tolerance: float = 10.0,
) -> BestReachableWindow | None:
    if tolerance < 0:
        raise ValueError("window tolerance cannot be negative")
    reachable = [
        assessment
        for assessment in assessments
        if assessment.reachable and assessment.score.score is not None
    ]
    if not reachable:
        return None
    peak = max(reachable, key=lambda item: item.score.score or float("-inf"))
    threshold = (peak.score.score or 0.0) - tolerance
    eligible = [item for item in reachable if (item.score.score or -math.inf) >= threshold]
    eligible.sort(key=lambda item: item.record.valid_time)
    peak_index = next(index for index, item in enumerate(eligible) if item is peak)

    start_index = peak_index
    while start_index > 0 and _is_adjacent(eligible[start_index - 1], eligible[start_index]):
        start_index -= 1
    end_index = peak_index
    while end_index + 1 < len(eligible) and _is_adjacent(eligible[end_index], eligible[end_index + 1]):
        end_index += 1
    return BestReachableWindow(
        start=eligible[start_index].record.valid_time,
        end=eligible[end_index].record.valid_time,
        peak=peak,
        tolerance=tolerance,
    )


def compare_results(
    first: ForecastResult,
    second: ForecastResult,
    first_date: date,
    second_date: date,
    *,
    hours: tuple[int, int] = (0, 23),
    arrival_after: time | str | None = None,
    cloud_strategy: str = "mid",
    window_tolerance: float = 10.0,
) -> tuple[DayComparison, DayComparison]:
    return (
        _assess_day_with_tolerance(
            first,
            first_date,
            hours=hours,
            arrival_after=arrival_after,
            cloud_strategy=cloud_strategy,
            window_tolerance=window_tolerance,
        ),
        _assess_day_with_tolerance(
            second,
            second_date,
            hours=hours,
            arrival_after=arrival_after,
            cloud_strategy=cloud_strategy,
            window_tolerance=window_tolerance,
        ),
    )


def _assess_day_with_tolerance(
    result: ForecastResult,
    target_date: date,
    *,
    hours: tuple[int, int],
    arrival_after: time | str | None,
    cloud_strategy: str,
    window_tolerance: float,
) -> DayComparison:
    comparison = assess_day(
        result,
        target_date,
        hours=hours,
        arrival_after=arrival_after,
        cloud_strategy=cloud_strategy,
    )
    return DayComparison(
        date=comparison.date,
        assessments=comparison.assessments,
        best_window=find_best_reachable_window(
            comparison.assessments, tolerance=window_tolerance
        ),
    )


def rank_days(comparisons: Iterable[DayComparison]) -> list[DayComparison]:
    return sorted(
        comparisons,
        key=lambda comparison: (
            comparison.peak_score is not None,
            comparison.peak_score if comparison.peak_score is not None else float("-inf"),
        ),
        reverse=True,
    )


def calculate_trend(
    rows: Iterable[StoredForecast],
    *,
    cloud_strategy: str = "mid",
    valid_time: datetime | None = None,
) -> TrendMetrics:
    ordered = sorted(rows, key=lambda row: row.retrieved_at)
    if not ordered:
        raise ValueError("no saved snapshots contain this valid hour")
    target = valid_time or ordered[-1].valid_time
    assessments = [
        HourAssessment(record=row, reachable=True, score=proxy_score(row, cloud_strategy))
        for row in ordered
    ]
    scored = [item for item in assessments if item.score.score is not None]
    latest = assessments[-1]
    previous = assessments[-2] if len(assessments) >= 2 else None
    score_values = [item.score.score for item in scored if item.score.score is not None]
    differences = [
        current.score.score - prior.score.score
        for prior, current in zip(scored, scored[1:])
        if prior.score.score is not None and current.score.score is not None
    ]
    improving = _consecutive_direction(differences, positive=True)
    worsening = _consecutive_direction(differences, positive=False)
    return TrendMetrics(
        valid_time=target,
        samples=len(ordered),
        assessments=tuple(assessments),
        latest=latest,
        previous=previous,
        delta_since_previous=_score_delta(previous, latest),
        delta_6h=_delta_at_or_before(assessments, latest, timedelta(hours=6)),
        delta_12h=_delta_at_or_before(assessments, latest, timedelta(hours=12)),
        improving_snapshots=improving,
        worsening_snapshots=worsening,
        score_stddev=pstdev(score_values) if len(score_values) >= 2 else None,
        visibility_trend_km=tuple(item.record.visibility_km for item in assessments),
        mid_cloud_trend_pct=tuple(item.record.cloud_mid_pct for item in assessments),
        precipitation_trend_pct=tuple(
            item.record.precipitation_probability_pct for item in assessments
        ),
        label=_trend_label(latest.score.score, differences, score_values),
    )


def _is_adjacent(left: HourAssessment, right: HourAssessment) -> bool:
    return right.record.valid_time - left.record.valid_time == timedelta(hours=1)


def _score_delta(left: HourAssessment | None, right: HourAssessment | None) -> float | None:
    if left is None or right is None or left.score.score is None or right.score.score is None:
        return None
    return right.score.score - left.score.score


def _delta_at_or_before(
    assessments: list[HourAssessment], latest: HourAssessment, offset: timedelta
) -> float | None:
    target = latest.record.retrieved_at - offset
    candidates = [item for item in assessments if item.record.retrieved_at <= target]
    if not candidates:
        return None
    return _score_delta(candidates[-1], latest)


def _consecutive_direction(differences: list[float], *, positive: bool) -> int:
    count = 0
    for difference in reversed(differences):
        is_direction = difference > 0.5 if positive else difference < -0.5
        if is_direction:
            count += 1
        else:
            break
    return count


def _trend_label(
    latest_score: float | None, differences: list[float], scores: list[float]
) -> str:
    if not scores:
        return "UNSTABLE"
    spread = pstdev(scores) if len(scores) >= 2 else 0.0
    recent = differences[-1] if differences else 0.0
    if spread >= 15 or (len(differences) >= 2 and abs(recent) >= 15):
        return "VOLATILE"
    if recent >= 0.5:
        return "IMPROVING"
    if recent <= -0.5:
        return "WORSENING"
    return "STABLE"
