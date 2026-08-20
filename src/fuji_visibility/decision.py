"""Reachable-window decisions that keep quality, consensus, and stability separate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from statistics import mean
from typing import Iterable, Sequence

from .config import (
    DECISION_MIN_FULL_MODELS,
    DECISION_MIN_PROXY_DIFFERENCE,
    DECISION_MIN_WINDOW_HOURS,
    GOOD_PROXY_THRESHOLD,
)
from .consensus import ConsensusHour, ConsensusResult
from .stability import StabilityMetrics
from .time_utils import canonical_iso, parse_clock, to_jst


@dataclass(frozen=True)
class DecisionHour:
    consensus: ConsensusHour
    reachable: bool
    qualifies: bool
    stability: StabilityMetrics


@dataclass(frozen=True)
class DecisionWindow:
    start: datetime
    end: datetime
    hours: tuple[DecisionHour, ...]
    peak: DecisionHour
    mean_proxy: float
    minimum_proxy: float
    consensus_rank: int
    stability_rank: int
    consensus_label: str
    stability_confidence: str
    trend_label: str

    @property
    def duration_hours(self) -> int:
        return len(self.hours)

    @property
    def peak_proxy(self) -> float:
        return self.peak.consensus.proxy_median or 0.0

    @property
    def mid_cloud_max(self) -> float | None:
        values = [hour.consensus.mid_cloud_median for hour in self.hours]
        values = [value for value in values if value is not None]
        return max(values) if values else None

    @property
    def visibility_min(self) -> float | None:
        values = [hour.consensus.visibility_median_km for hour in self.hours]
        values = [value for value in values if value is not None]
        return min(values) if values else None


@dataclass(frozen=True)
class DecisionDay:
    date: date
    hours: tuple[DecisionHour, ...]
    windows: tuple[DecisionWindow, ...]

    @property
    def best_window(self) -> DecisionWindow | None:
        return self.windows[0] if self.windows else None


@dataclass(frozen=True)
class DecisionResult:
    days: tuple[DecisionDay, ...]
    winner: DecisionDay | None
    no_clear_winner: bool
    rationale: tuple[str, ...]
    min_proxy: float
    min_window_hours: int

    @property
    def status(self) -> str:
        if self.no_clear_winner:
            return "NO CLEAR WINNER"
        return "RECOMMENDED" if self.winner is not None else "NO QUALIFYING WINDOW"


def decide_days(
    daily_results: Sequence[tuple[date, ConsensusResult]],
    *,
    arrival_after: time | str | None = None,
    hours: tuple[int, int] = (0, 23),
    stability_by_time: dict[str, StabilityMetrics] | None = None,
    min_proxy: float = GOOD_PROXY_THRESHOLD,
    min_window_hours: int = DECISION_MIN_WINDOW_HOURS,
    min_full_models: int = DECISION_MIN_FULL_MODELS,
    proxy_difference_threshold: float = DECISION_MIN_PROXY_DIFFERENCE,
) -> DecisionResult:
    if min_window_hours <= 0:
        raise ValueError("min_window_hours must be positive")
    start_hour, end_hour = hours
    arrival = parse_clock(arrival_after) if isinstance(arrival_after, str) else arrival_after
    stability = stability_by_time or {}
    days: list[DecisionDay] = []
    for target_date, result in daily_results:
        assessments: list[DecisionHour] = []
        for hour in result.hours:
            local = to_jst(hour.valid_time)
            if local.date() != target_date or not (start_hour <= local.hour <= end_hour):
                continue
            reachable = arrival is None or local.time().replace(second=0, microsecond=0) >= arrival
            hour_stability = stability.get(canonical_iso(hour.valid_time), _unknown_stability())
            qualifies = (
                reachable
                and hour.proxy_median is not None
                and hour.proxy_median >= min_proxy
                and hour.full_model_count >= min_full_models
                and hour.consensus_label in {"HIGH", "MEDIUM"}
            )
            assessments.append(
                DecisionHour(
                    consensus=hour,
                    reachable=reachable,
                    qualifies=qualifies,
                    stability=hour_stability,
                )
            )
        assessments.sort(key=lambda item: item.consensus.valid_time)
        windows = _candidate_windows(assessments, min_window_hours=min_window_hours)
        days.append(
            DecisionDay(
                date=target_date,
                hours=tuple(assessments),
                windows=tuple(sorted(windows, key=_window_sort_key, reverse=True)),
            )
        )
    winner, ambiguous, rationale = _choose_winner(
        days,
        proxy_difference_threshold=proxy_difference_threshold,
    )
    return DecisionResult(
        days=tuple(days),
        winner=winner,
        no_clear_winner=ambiguous,
        rationale=tuple(rationale),
        min_proxy=min_proxy,
        min_window_hours=min_window_hours,
    )


def _candidate_windows(
    assessments: Sequence[DecisionHour], *, min_window_hours: int
) -> list[DecisionWindow]:
    qualifying = [assessment for assessment in assessments if assessment.qualifies]
    groups: list[list[DecisionHour]] = []
    for assessment in qualifying:
        if not groups or not _adjacent(groups[-1][-1], assessment):
            groups.append([assessment])
        else:
            groups[-1].append(assessment)
    windows: list[DecisionWindow] = []
    for group in groups:
        if len(group) < min_window_hours:
            continue
        windows.append(_window(group))
    return windows


def _window(group: Sequence[DecisionHour]) -> DecisionWindow:
    peak = max(group, key=lambda item: item.consensus.proxy_median or float("-inf"))
    proxies = [item.consensus.proxy_median for item in group if item.consensus.proxy_median is not None]
    consensus_rank = min(_consensus_rank(item.consensus.consensus_label) for item in group)
    stability_rank = min(_stability_rank(item.stability.confidence) for item in group)
    trend = _window_trend(group)
    return DecisionWindow(
        start=group[0].consensus.valid_time,
        end=group[-1].consensus.valid_time,
        hours=tuple(group),
        peak=peak,
        mean_proxy=float(mean(proxies)),
        minimum_proxy=min(proxies),
        consensus_rank=consensus_rank,
        stability_rank=stability_rank,
        consensus_label=_rank_label(consensus_rank, {3: "HIGH", 2: "MEDIUM", 1: "LOW", 0: "INSUFFICIENT_DATA"}),
        stability_confidence=_rank_label(stability_rank, {3: "HIGH", 2: "MEDIUM", 1: "LOW", 0: "UNKNOWN"}),
        trend_label=trend,
    )


def _choose_winner(
    days: Sequence[DecisionDay], *, proxy_difference_threshold: float
) -> tuple[DecisionDay | None, bool, list[str]]:
    available = [day for day in days if day.best_window is not None]
    if not available:
        return None, False, ["No day has a reachable qualifying window."]
    ranked = sorted(available, key=lambda day: _window_sort_key(day.best_window), reverse=True)
    if len(ranked) == 1:
        return ranked[0], False, ["Only one candidate day has a reachable qualifying window."]
    first, second = ranked[0], ranked[1]
    first_window = first.best_window
    second_window = second.best_window
    assert first_window is not None and second_window is not None
    proxy_delta = abs(first_window.peak_proxy - second_window.peak_proxy)
    materially_better = (
        first_window.consensus_rank > second_window.consensus_rank
        or first_window.stability_rank > second_window.stability_rank
        or first_window.duration_hours > second_window.duration_hours
    )
    if proxy_delta < proxy_difference_threshold and not materially_better:
        return (
            None,
            True,
            [
                f"Peak Proxy difference ({proxy_delta:.1f}) is below the "
                f"{proxy_difference_threshold:.1f}-point decision threshold.",
                "Recheck after the next model cycle.",
            ],
        )
    reasons = _why_wins(first_window, second_window)
    return first, False, reasons


def _why_wins(first: DecisionWindow, second: DecisionWindow) -> list[str]:
    reasons: list[str] = []
    if first.duration_hours > second.duration_hours:
        reasons.append("longer reachable window")
    if first.consensus_rank > second.consensus_rank:
        reasons.append("stronger multi-model agreement")
    if first.stability_rank > second.stability_rank:
        reasons.append("more stable recent forecast")
    if first.peak_proxy > second.peak_proxy:
        reasons.append("higher Proxy median")
    if first.trend_label == "IMPROVING" and second.trend_label != "IMPROVING":
        reasons.append("more favorable trend direction")
    return reasons or ["higher rules-based decision rank"]


def _window_sort_key(window: DecisionWindow | None) -> tuple[int, int, int, float, int]:
    if window is None:
        return (-1, -1, -1, float("-inf"), -1)
    trend_rank = {"IMPROVING": 3, "STABLE": 2, "UNKNOWN": 1, "WORSENING": 0, "VOLATILE": 0}.get(
        window.trend_label, 0
    )
    return (
        window.consensus_rank,
        window.stability_rank,
        window.duration_hours,
        window.peak_proxy,
        trend_rank,
    )


def _window_trend(group: Sequence[DecisionHour]) -> str:
    labels = [item.stability.trend_label for item in group]
    if "VOLATILE" in labels:
        return "VOLATILE"
    if "WORSENING" in labels:
        return "WORSENING"
    if "IMPROVING" in labels:
        return "IMPROVING"
    if "STABLE" in labels:
        return "STABLE"
    return "UNKNOWN"


def _adjacent(left: DecisionHour, right: DecisionHour) -> bool:
    return right.consensus.valid_time - left.consensus.valid_time == timedelta(hours=1)


def _consensus_rank(label: str) -> int:
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INSUFFICIENT_DATA": 0}.get(label, 0)


def _stability_rank(label: str) -> int:
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}.get(label, 0)


def _rank_label(rank: int, labels: dict[int, str]) -> str:
    return labels.get(rank, "UNKNOWN")


def _unknown_stability() -> StabilityMetrics:
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


def decision_payload(result: DecisionResult) -> dict[str, object]:
    """JSON-safe derived decision output for diagnostics and automation."""

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
            "stability_confidence": window.stability_confidence,
            "trend": window.trend_label,
            "mid_cloud_max": window.mid_cloud_max,
            "visibility_min_km": window.visibility_min,
            "model_good_proxy": peak.models_good_proxy,
            "full_model_count": peak.full_model_count,
            "proxy_min": peak.proxy_min,
            "proxy_max": peak.proxy_max,
        }

    return {
        "status": result.status,
        "winner_date": None if result.winner is None else result.winner.date.isoformat(),
        "no_clear_winner": result.no_clear_winner,
        "min_proxy": result.min_proxy,
        "min_window_hours": result.min_window_hours,
        "rationale": list(result.rationale),
        "days": [
            {
                "date": day.date.isoformat(),
                "best_window": window_payload(day.best_window),
                "windows": [window_payload(window) for window in day.windows],
                "hours": [
                    {
                        "valid_time": canonical_iso(hour.consensus.valid_time),
                        "reachable": hour.reachable,
                        "qualifies": hour.qualifies,
                        "proxy_median": hour.consensus.proxy_median,
                        "proxy_min": hour.consensus.proxy_min,
                        "proxy_max": hour.consensus.proxy_max,
                        "consensus": hour.consensus.consensus_label,
                        "stability": hour.stability.confidence,
                        "trend": hour.stability.trend_label,
                    }
                    for hour in day.hours
                ],
            }
            for day in result.days
        ],
    }
