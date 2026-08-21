"""Reachable-window decisions that keep quality, consensus, and stability separate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from statistics import mean, median, pstdev
from typing import Iterable, Sequence

from .config import (
    DECISION_MIN_PROXY_DIFFERENCE,
    DECISION_MIN_WINDOW_HOURS,
    FIELD_SUPPORT_STRONG_MIN_MODELS,
    GOOD_HUMIDITY_MAX,
    GOOD_MID_CLOUD_MAX,
    GOOD_PRECIP_MAX,
    GOOD_VISIBILITY_MIN_KM,
    MAX_PROXY_SPREAD_FOR_STRONG_SUPPORT,
    MAX_PROXY_SPREAD_FOR_WEAK_SUPPORT,
    MIN_FULL_PROXY_MODELS,
    MIN_PROXY,
)
from .consensus import ConsensusHour, ConsensusResult, FieldConsensus
from .stability import StabilityMetrics
from .time_utils import canonical_iso, parse_clock, to_jst


@dataclass(frozen=True)
class DecisionHour:
    consensus: ConsensusHour
    reachable: bool
    qualifies: bool
    stability: StabilityMetrics
    status: str = "OTHER"
    confidence: str = "INSUFFICIENT"
    decision_reasons: tuple[str, ...] = ()
    qualification_reasons: tuple[str, ...] = ()

    @property
    def decision_status(self) -> str:
        return self.status

    @property
    def promising(self) -> bool:
        return self.status == "PROMISING"


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
    status: str = "QUALIFIES"
    confidence: str = "MEDIUM"

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
    promising_windows: tuple[DecisionWindow, ...] = ()

    @property
    def best_window(self) -> DecisionWindow | None:
        return self.windows[0] if self.windows else None

    @property
    def best_promising_window(self) -> DecisionWindow | None:
        return self.promising_windows[0] if self.promising_windows else None


@dataclass(frozen=True)
class DecisionResult:
    days: tuple[DecisionDay, ...]
    winner: DecisionDay | None
    no_clear_winner: bool
    rationale: tuple[str, ...]
    min_proxy: float
    min_window_hours: int
    promising_winner: DecisionDay | None = None
    confidence: str = "INSUFFICIENT"
    decision_reasons: tuple[str, ...] = ()
    insufficient_evidence: bool = False

    @property
    def status(self) -> str:
        if self.no_clear_winner:
            return "NO CLEAR WINNER"
        if self.winner is not None:
            return "RECOMMENDED"
        if self.promising_winner is not None:
            return "PROMISING"
        if self.insufficient_evidence:
            return "INSUFFICIENT EVIDENCE"
        return "NO QUALIFYING WINDOW"

    @property
    def field_consensus_summary(self) -> dict[str, dict[str, object]]:
        day = self.winner or self.promising_winner
        if day is None:
            return {}
        window = day.best_window or day.best_promising_window
        if window is None:
            return {}
        return window.peak.consensus.field_consensus_summary


def decide_days(
    daily_results: Sequence[tuple[date, ConsensusResult]],
    *,
    arrival_after: time | str | None = None,
    hours: tuple[int, int] = (0, 23),
    stability_by_time: dict[str, StabilityMetrics] | None = None,
    min_proxy: float = MIN_PROXY,
    min_window_hours: int = DECISION_MIN_WINDOW_HOURS,
    min_full_proxy_models: int | None = None,
    min_full_models: int | None = None,
    proxy_difference_threshold: float = DECISION_MIN_PROXY_DIFFERENCE,
    max_proxy_spread_strong: float = MAX_PROXY_SPREAD_FOR_STRONG_SUPPORT,
    max_proxy_spread_weak: float = MAX_PROXY_SPREAD_FOR_WEAK_SUPPORT,
    good_mid_cloud_max: float = GOOD_MID_CLOUD_MAX,
    good_visibility_min_km: float = GOOD_VISIBILITY_MIN_KM,
    good_precip_max: float = GOOD_PRECIP_MAX,
    good_humidity_max: float = GOOD_HUMIDITY_MAX,
) -> DecisionResult:
    if min_window_hours <= 0:
        raise ValueError("min_window_hours must be positive")
    start_hour, end_hour = hours
    arrival = parse_clock(arrival_after) if isinstance(arrival_after, str) else arrival_after
    stability = stability_by_time or {}
    if min_full_proxy_models is None:
        min_full_proxy_models = min_full_models or MIN_FULL_PROXY_MODELS
    if min_full_proxy_models <= 0:
        raise ValueError("min_full_proxy_models must be positive")
    if max_proxy_spread_strong > max_proxy_spread_weak:
        raise ValueError("max_proxy_spread_strong must not exceed max_proxy_spread_weak")
    days: list[DecisionDay] = []
    for target_date, result in daily_results:
        assessments: list[DecisionHour] = []
        for hour in result.hours:
            local = to_jst(hour.valid_time)
            if local.date() != target_date or not (start_hour <= local.hour <= end_hour):
                continue
            reachable = arrival is None or local.time().replace(second=0, microsecond=0) >= arrival
            hour_stability = stability.get(canonical_iso(hour.valid_time), _unknown_stability())
            assessment = _assess_hour(
                hour,
                reachable=reachable,
                stability=hour_stability,
                min_proxy=min_proxy,
                min_full_proxy_models=min_full_proxy_models,
                max_proxy_spread_strong=max_proxy_spread_strong,
                max_proxy_spread_weak=max_proxy_spread_weak,
                good_mid_cloud_max=good_mid_cloud_max,
                good_visibility_min_km=good_visibility_min_km,
                good_precip_max=good_precip_max,
                good_humidity_max=good_humidity_max,
            )
            assessments.append(
                DecisionHour(
                    consensus=hour,
                    reachable=reachable,
                    qualifies=assessment["qualifies"],
                    stability=hour_stability,
                    status=assessment["status"],
                    confidence=assessment["confidence"],
                    decision_reasons=assessment["reasons"],
                    qualification_reasons=assessment["reasons"],
                )
            )
        assessments.sort(key=lambda item: item.consensus.valid_time)
        windows = _candidate_windows(assessments, min_window_hours=min_window_hours)
        promising_windows = _promising_windows(assessments)
        days.append(
            DecisionDay(
                date=target_date,
                hours=tuple(assessments),
                windows=tuple(sorted(windows, key=_window_sort_key, reverse=True)),
                promising_windows=tuple(
                    sorted(promising_windows, key=_window_sort_key, reverse=True)
                ),
            )
        )
    winner, ambiguous, rationale = _choose_winner(
        days,
        proxy_difference_threshold=proxy_difference_threshold,
    )
    promising_winner: DecisionDay | None = None
    if winner is None and not ambiguous:
        promising_winner, promising_ambiguous, promising_rationale = _choose_winner(
            days,
            proxy_difference_threshold=proxy_difference_threshold,
            promising=True,
        )
        if promising_ambiguous:
            ambiguous = True
            rationale = promising_rationale
        elif promising_winner is not None:
            rationale = [
                "No day has a reachable qualifying window.",
                "A reachable evidence-supported promising window is available.",
            ] + promising_rationale
    insufficient_evidence = _insufficient_result(days)
    if winner is None and promising_winner is None and not ambiguous:
        rationale = (
            ["Not enough core forecast evidence is currently available."]
            if insufficient_evidence
            else ["No day has a reachable qualifying window."]
        )
    selected_day = winner or promising_winner
    selected_window = None if selected_day is None else (selected_day.best_window or selected_day.best_promising_window)
    return DecisionResult(
        days=tuple(days),
        winner=winner,
        no_clear_winner=ambiguous,
        rationale=tuple(rationale),
        min_proxy=min_proxy,
        min_window_hours=min_window_hours,
        promising_winner=promising_winner,
        confidence=(selected_window.confidence if selected_window is not None else "INSUFFICIENT"),
        decision_reasons=tuple(
            selected_window.peak.qualification_reasons if selected_window is not None else ()
        ),
        insufficient_evidence=insufficient_evidence,
    )


def _assess_hour(
    hour: ConsensusHour,
    *,
    reachable: bool,
    stability: StabilityMetrics,
    min_proxy: float,
    min_full_proxy_models: int,
    max_proxy_spread_strong: float,
    max_proxy_spread_weak: float,
    good_mid_cloud_max: float,
    good_visibility_min_km: float,
    good_precip_max: float,
    good_humidity_max: float,
) -> dict[str, object]:
    """Classify one hour using the same evidence layers shown in the UI."""

    if not reachable:
        return {
            "qualifies": False,
            "status": "BEFORE_ARRIVAL",
            "confidence": "INSUFFICIENT",
            "reasons": ("BEFORE_ARRIVAL",),
        }

    full_count = _full_proxy_count(hour)
    reasons: list[str] = []
    if full_count < min_full_proxy_models:
        reasons.extend(("FULL_PROXY_MODELS_INSUFFICIENT", "INSUFFICIENT_CORE_DATA"))
        return {
            "qualifies": False,
            "status": "INSUFFICIENT_CORE_DATA",
            "confidence": "INSUFFICIENT",
            "reasons": tuple(reasons),
        }

    if hour.proxy_median is None:
        reasons.extend(("PROXY_UNAVAILABLE", "INSUFFICIENT_CORE_DATA"))
        return {
            "qualifies": False,
            "status": "INSUFFICIENT_CORE_DATA",
            "confidence": "INSUFFICIENT",
            "reasons": tuple(reasons),
        }
    if hour.proxy_median < min_proxy:
        reasons.extend(("LOW_PROXY", "PROXY_BELOW_THRESHOLD"))
        return {
            "qualifies": False,
            "status": "LOW_SCORE",
            "confidence": "LOW",
            "reasons": tuple(reasons),
        }
    reasons.extend(("PROXY_OK", "PROXY_ABOVE_THRESHOLD", "FULL_PROXY_MODELS_OK"))

    spread = _proxy_spread(hour)
    if spread is not None and spread > max_proxy_spread_weak:
        reasons.extend(("PROXY_DISAGREEMENT", "PROXY_DISAGREEMENT_SEVERE"))
        return {
            "qualifies": False,
            "status": "MODEL_DISAGREEMENT",
            "confidence": "LOW",
            "reasons": tuple(reasons),
        }
    if spread is not None and spread <= max_proxy_spread_strong:
        reasons.append("PROXY_MODELS_AGREE")
    elif spread is not None:
        reasons.append("PROXY_DISAGREEMENT_LIMITED")

    field_map = {
        "mid_cloud": _field_evidence(hour, "mid_cloud", good_threshold=good_mid_cloud_max),
        "precipitation": _field_evidence(
            hour, "precipitation", good_threshold=good_precip_max
        ),
        "visibility": _field_evidence(
            hour, "visibility", good_threshold=good_visibility_min_km
        ),
        "humidity": _field_evidence(hour, "humidity", good_threshold=good_humidity_max),
    }
    mid = field_map["mid_cloud"]
    precip = field_map["precipitation"]
    if mid is None or mid.support == "INSUFFICIENT":
        reasons.append("MID_CLOUD_INSUFFICIENT")
    elif mid.support == "OPPOSED":
        reasons.append("MID_CLOUD_OPPOSED")
        return {
            "qualifies": False,
            "status": "FIELD_CONSENSUS_WEAK",
            "confidence": "LOW",
            "reasons": tuple(reasons),
        }
    elif mid.support == "STRONG_SUPPORT":
        reasons.append("MID_CLOUD_STRONGLY_SUPPORTED")
    else:
        reasons.append("MID_CLOUD_SUPPORTED")

    if precip is None or precip.support == "INSUFFICIENT":
        reasons.append("PRECIP_INSUFFICIENT")
    elif precip.support == "OPPOSED":
        reasons.append("PRECIP_OPPOSED")
        return {
            "qualifies": False,
            "status": "FIELD_CONSENSUS_WEAK",
            "confidence": "LOW",
            "reasons": tuple(reasons),
        }
    else:
        reasons.append("PRECIP_SUPPORTED")

    visibility = field_map["visibility"]
    if visibility is not None and visibility.support in {"STRONG_SUPPORT", "MODERATE_SUPPORT"}:
        reasons.append("VISIBILITY_SUPPORTED")
    elif visibility is not None and visibility.model_count:
        reasons.append("LIMITED_VISIBILITY_MODEL_COUNT")
    humidity = field_map["humidity"]
    if humidity is not None and humidity.support == "OPPOSED":
        reasons.append("HUMIDITY_OPPOSED")
    elif humidity is not None and humidity.support in {"STRONG_SUPPORT", "MODERATE_SUPPORT"}:
        reasons.append("HUMIDITY_SUPPORTED")

    confidence = _hour_confidence(
        full_count=full_count,
        spread=spread,
        mid=mid,
        precip=precip,
        humidity=humidity,
        stability=stability,
        max_proxy_spread_strong=max_proxy_spread_strong,
        max_proxy_spread_weak=max_proxy_spread_weak,
    )
    reasons.append(f"CONFIDENCE_{confidence}")
    # A high-confidence candidate is a formal qualifying hour.  A weather-
    # positive hour with limited or volatile evidence remains explicitly
    # promising instead of being mislabeled as bad weather.
    status = "QUALIFIES" if confidence == "HIGH" else "PROMISING"
    return {
        "qualifies": status == "QUALIFIES",
        "status": status,
        "confidence": confidence,
        "reasons": tuple(reasons),
    }


def _hour_confidence(
    *,
    full_count: int,
    spread: float | None,
    mid: FieldConsensus | None,
    precip: FieldConsensus | None,
    humidity: FieldConsensus | None,
    stability: StabilityMetrics,
    max_proxy_spread_strong: float,
    max_proxy_spread_weak: float,
) -> str:
    if full_count < MIN_FULL_PROXY_MODELS:
        return "INSUFFICIENT"
    if spread is None or spread > max_proxy_spread_weak:
        return "LOW"
    if stability.trend_label == "VOLATILE" or stability.confidence == "LOW":
        return "LOW"
    if humidity is not None and humidity.support == "OPPOSED":
        return "LOW"
    mid_positive = mid is not None and mid.support in {"STRONG_SUPPORT", "MODERATE_SUPPORT"}
    precip_positive = precip is not None and precip.support in {
        "STRONG_SUPPORT",
        "MODERATE_SUPPORT",
    }
    if (
        full_count >= FIELD_SUPPORT_STRONG_MIN_MODELS
        and spread <= max_proxy_spread_strong
        and mid is not None
        and mid.support == "STRONG_SUPPORT"
        and precip_positive
        and stability.trend_label != "WORSENING"
    ):
        return "HIGH"
    if mid_positive and (precip_positive or precip is None or precip.support == "INSUFFICIENT"):
        return "MEDIUM"
    return "LOW"


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


def _promising_windows(assessments: Sequence[DecisionHour]) -> list[DecisionWindow]:
    promising = [assessment for assessment in assessments if assessment.status == "PROMISING"]
    groups: list[list[DecisionHour]] = []
    for assessment in promising:
        if not groups or not _adjacent(groups[-1][-1], assessment):
            groups.append([assessment])
        else:
            groups[-1].append(assessment)
    return [_window(group, status="PROMISING") for group in groups]


def _window(group: Sequence[DecisionHour], *, status: str = "QUALIFIES") -> DecisionWindow:
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
        status=status,
        confidence=_window_confidence(group),
    )


def _window_confidence(group: Sequence[DecisionHour]) -> str:
    ranks = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INSUFFICIENT": 0}
    return _rank_label(min(ranks.get(item.confidence, 0) for item in group), {
        3: "HIGH",
        2: "MEDIUM",
        1: "LOW",
        0: "INSUFFICIENT",
    })


def _full_proxy_count(hour: ConsensusHour) -> int:
    return hour.full_proxy_model_count or hour.full_model_count


def _proxy_spread(hour: ConsensusHour) -> float | None:
    if hour.proxy_spread is not None:
        return hour.proxy_spread
    if hour.proxy_min is None or hour.proxy_max is None:
        return None
    return hour.proxy_max - hour.proxy_min


def _field_evidence(
    hour: ConsensusHour,
    name: str,
    *,
    good_threshold: float,
) -> FieldConsensus | None:
    canonical = "precipitation" if name in {"precip", "precipitation"} else name
    if hour.field_consensus:
        return hour.field_consensus.get(canonical)

    if canonical == "mid_cloud":
        model_count = hour.mid_cloud_model_count or (hour.model_count if hour.mid_cloud_median is not None else 0)
        values = hour.mid_cloud_values or _fallback_values(hour.mid_cloud_median, model_count)
        good_votes = hour.mid_cloud_good_votes or hour.models_good_mid_cloud
        threshold = good_threshold
        when = "below_or_equal"
    elif canonical == "visibility":
        model_count = hour.visibility_model_count or (hour.full_model_count if hour.visibility_median_km is not None else 0)
        values = hour.visibility_values_km or _fallback_values(hour.visibility_median_km, model_count)
        good_votes = hour.visibility_good_votes or hour.models_good_visibility
        threshold = good_threshold
        when = "above_or_equal"
    elif canonical == "precipitation":
        model_count = hour.precip_model_count or (hour.model_count if hour.precip_median is not None else 0)
        values = hour.precip_values or _fallback_values(hour.precip_median, model_count)
        good_votes = hour.precip_good_votes or hour.models_good_precip
        if good_votes == 0 and hour.precip_values == () and hour.precip_median is not None:
            good_votes = model_count if hour.precip_median <= good_threshold else 0
        threshold = good_threshold
        when = "below_or_equal"
    elif canonical == "humidity":
        model_count = hour.humidity_model_count or (hour.model_count if hour.humidity_median is not None else 0)
        values = hour.humidity_values or _fallback_values(hour.humidity_median, model_count)
        good_votes = hour.humidity_good_votes
        if good_votes == 0 and hour.humidity_values == () and hour.humidity_median is not None:
            good_votes = model_count if hour.humidity_median <= good_threshold else 0
        threshold = good_threshold
        when = "below_or_equal"
    else:
        return None
    if model_count <= 0:
        return None
    if not values and model_count:
        values = _fallback_values(None, model_count)
    return _synthetic_field_consensus(
        canonical,
        values,
        model_count=model_count,
        good_votes=good_votes,
        threshold=threshold,
        when=when,
    )


def _synthetic_field_consensus(
    name: str,
    values: Sequence[float],
    *,
    model_count: int,
    good_votes: int,
    threshold: float,
    when: str,
) -> FieldConsensus:
    # Legacy manually-created ConsensusHour values only carry aggregate
    # medians and vote counts.  Preserve their semantics for callers while
    # exposing the same field-level shape as freshly built consensus hours.
    count = max(model_count, len(values))
    ratio = good_votes / count if count else 0.0
    if count < 2:
        support = "INSUFFICIENT"
    elif count >= 3 and ratio >= 0.75:
        support = "STRONG_SUPPORT"
    elif ratio >= 0.60:
        support = "MODERATE_SUPPORT"
    elif ratio < 0.5:
        support = "OPPOSED"
    else:
        support = "MIXED"
    numeric_values = tuple(float(value) for value in values)
    return FieldConsensus(
        field=name,
        model_count=count,
        values=numeric_values,
        median=_median(numeric_values),
        minimum=min(numeric_values) if numeric_values else None,
        maximum=max(numeric_values) if numeric_values else None,
        stddev=_stddev(numeric_values),
        good_votes=good_votes,
        support=support,
        good_threshold=threshold,
        good_when=when,
    )


def _fallback_values(value: float | None, count: int) -> tuple[float, ...]:
    return () if value is None else tuple(value for _ in range(max(1, count)))


def _median(values: Sequence[float]) -> float | None:
    return None if not values else float(median(values))


def _stddev(values: Sequence[float]) -> float | None:
    return None if not values else float(pstdev(values))


def _insufficient_result(days: Sequence[DecisionDay]) -> bool:
    assessments = [hour for day in days for hour in day.hours if hour.reachable]
    if not assessments:
        return True
    return all(hour.status == "INSUFFICIENT_CORE_DATA" for hour in assessments)


def _choose_winner(
    days: Sequence[DecisionDay],
    *,
    proxy_difference_threshold: float,
    promising: bool = False,
) -> tuple[DecisionDay | None, bool, list[str]]:
    available = [
        day
        for day in days
        if (day.best_promising_window if promising else day.best_window) is not None
    ]
    if not available:
        return None, False, [
            "No day has a reachable promising window."
            if promising
            else "No day has a reachable qualifying window."
        ]
    window_for_day = lambda day: day.best_promising_window if promising else day.best_window
    ranked = sorted(available, key=lambda day: _window_sort_key(window_for_day(day)), reverse=True)
    if len(ranked) == 1:
        return ranked[0], False, [
            "Only one candidate day has a reachable promising window."
            if promising
            else "Only one candidate day has a reachable qualifying window."
        ]
    first, second = ranked[0], ranked[1]
    first_window = window_for_day(first)
    second_window = window_for_day(second)
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
            "status": window.status,
            "confidence": window.confidence,
            "stability_confidence": window.stability_confidence,
            "trend": window.trend_label,
            "mid_cloud_max": window.mid_cloud_max,
            "visibility_min_km": window.visibility_min,
            "model_good_proxy": peak.models_good_proxy,
            "full_model_count": peak.full_model_count,
            "proxy_min": peak.proxy_min,
            "proxy_max": peak.proxy_max,
            "proxy": peak.proxy_payload,
            "field_consensus": peak.field_consensus_summary,
        }

    def hour_payload(hour: DecisionHour) -> dict[str, object]:
        consensus = hour.consensus
        return {
            "valid_time": canonical_iso(consensus.valid_time),
            "reachable": hour.reachable,
            "qualifies": hour.qualifies,
            "status": hour.status,
            "decision_status": hour.status,
            "confidence": hour.confidence,
            "decision_reasons": list(hour.decision_reasons),
            "qualification_reasons": list(hour.qualification_reasons),
            "proxy_median": consensus.proxy_median,
            "proxy_min": consensus.proxy_min,
            "proxy_max": consensus.proxy_max,
            "consensus": consensus.consensus_label,
            "stability": hour.stability.confidence,
            "trend": hour.stability.trend_label,
            "proxy": consensus.proxy_payload,
            "field_consensus": consensus.field_consensus_summary,
        }

    return {
        "status": result.status,
        "winner_date": None if result.winner is None else result.winner.date.isoformat(),
        "promising_winner_date": (
            None if result.promising_winner is None else result.promising_winner.date.isoformat()
        ),
        "no_clear_winner": result.no_clear_winner,
        "confidence": result.confidence,
        "decision_reasons": list(result.decision_reasons),
        "field_consensus_summary": result.field_consensus_summary,
        "insufficient_evidence": result.insufficient_evidence,
        "min_proxy": result.min_proxy,
        "min_window_hours": result.min_window_hours,
        "rationale": list(result.rationale),
        "days": [
            {
                "date": day.date.isoformat(),
                "best_window": window_payload(day.best_window),
                "windows": [window_payload(window) for window in day.windows],
                "best_promising_window": window_payload(day.best_promising_window),
                "promising_windows": [
                    window_payload(window) for window in day.promising_windows
                ],
                "hours": [hour_payload(hour) for hour in day.hours],
            }
            for day in result.days
        ],
    }
