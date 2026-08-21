"""Rich terminal formatting kept separate from calculations and API code."""

from __future__ import annotations

from datetime import datetime, time
from typing import Iterable

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .comparison import DayComparison, HourAssessment, TrendMetrics
from .consensus import ConsensusHour, ConsensusResult
from .decision import DecisionResult, DecisionWindow
from .fingerprint import FingerprintCandidate, FingerprintSearchResult
from .models import ForecastResult, PreviousRunPoint
from .stability import StabilityMetrics
from .time_utils import display_datetime, to_jst


MISSING = "—"


def fmt(value: float | int | None, digits: int = 0, suffix: str = "") -> str:
    if value is None:
        return MISSING
    return f"{value:.{digits}f}{suffix}"


def render_forecast(
    console: Console,
    result: ForecastResult,
    comparison: DayComparison,
    *,
    title: str | None = None,
) -> None:
    if title:
        console.print(f"[bold]{title}[/bold]")
    _render_metadata(console, result)
    _render_day_table(console, comparison)
    _render_best_window(console, comparison)


def render_comparison(
    console: Console,
    results: Iterable[ForecastResult],
    comparisons: Iterable[DayComparison],
    *,
    location_name: str,
    cloud_strategy: str,
) -> None:
    results_list = list(results)
    comparisons_list = list(comparisons)
    console.print(f"[bold]Mt Fuji Visibility — {location_name}[/bold]")
    retrieved = min((result.retrieved_at for result in results_list), default=None)
    if retrieved:
        console.print(f"Retrieved: {display_datetime(retrieved)}")
    console.print("Source: Open-Meteo")
    console.print(f"Model: {', '.join(sorted({result.model for result in results_list}))}")
    console.print(f"Fuji Proxy Score: approximate; cloud strategy={cloud_strategy}")
    for comparison in comparisons_list:
        console.print()
        console.print(f"[bold]{comparison.date.strftime('%a %Y-%m-%d').upper()}[/bold]")
        _render_day_table(console, comparison)
        _render_best_window(console, comparison)
    ranked = sorted(
        comparisons_list,
        key=lambda item: item.peak_score if item.peak_score is not None else float("-inf"),
        reverse=True,
    )
    if ranked and ranked[0].peak_score is not None:
        best = ranked[0]
        console.print()
        console.print(
            f"[bold]Best reachable day:[/bold] {best.date.strftime('%a %Y-%m-%d').upper()} "
            f"(peak {best.peak_score:.0f})"
        )
        if best.best_window:
            console.print(
                f"Best reachable window: {format_time_window(best.best_window.start, best.best_window.end)}"
            )
            console.print(f"Peak hour: {to_jst(best.best_window.peak.record.valid_time):%H:%M}")
    else:
        console.print("Best reachable day: unavailable — no complete Proxy Score inputs.")


def render_trend(console: Console, metrics: TrendMetrics) -> None:
    console.print(f"[bold]Forecast trend — {display_datetime(metrics.valid_time)}[/bold]")
    table = Table(show_header=True, header_style="bold")
    for column in ("Retrieved at", "Mid cloud", "Visibility", "RH", "Rain", "Proxy"):
        table.add_column(column)
    samples = _trend_samples(metrics)
    for retrieved, mid_cloud, visibility, humidity, rain, score in samples:
        table.add_row(
            display_datetime(retrieved),
            fmt(mid_cloud, 0, "%"),
            fmt(visibility, 1, " km"),
            fmt(humidity, 0, "%"),
            fmt(rain, 0, "%"),
            fmt(score, 0),
        )
    console.print(table)
    console.print(
        f"Status: [bold]{metrics.label}[/bold] | samples={metrics.samples} | "
        f"delta previous={fmt(metrics.delta_since_previous, 1)} | "
        f"delta 6h={fmt(metrics.delta_6h, 1)} | delta 12h={fmt(metrics.delta_12h, 1)}"
    )


def render_stability(
    console: Console,
    metrics: StabilityMetrics,
    *,
    valid_time: datetime,
    consensus: bool = False,
) -> None:
    title = "Consensus forecast trend" if consensus else "Forecast stability"
    console.print(f"[bold]{title} — {display_datetime(valid_time)}[/bold]")
    table = Table(show_header=True, header_style="bold")
    for column in ("Retrieved", "Proxy Median", "Mid Cloud", "Vis km", "Models"):
        table.add_column(column)
    for point in metrics.points:
        model_count = "—" if point.model_count is None else str(point.model_count)
        table.add_row(
            display_datetime(point.retrieved_at),
            fmt(point.proxy, 0),
            fmt(point.mid_cloud_pct, 0, "%"),
            fmt(point.visibility_km, 1),
            model_count,
        )
    console.print(table)
    console.print(
        f"Trend: [bold]{metrics.trend_label}[/bold] | "
        f"Stability confidence: [bold]{metrics.confidence}[/bold] | "
        f"samples={metrics.samples}"
    )
    console.print(
        f"6h delta: {fmt(metrics.delta_6h, 1)} | "
        f"12h delta: {fmt(metrics.delta_12h, 1)} | "
        f"24h delta: {fmt(metrics.delta_24h, 1)} | "
        f"recent Proxy σ: {fmt(metrics.recent_proxy_stddev, 1)}"
    )


def render_consensus(
    console: Console,
    daily_results: Iterable[tuple[object, ConsensusResult]],
    *,
    hours: tuple[int, int] = (0, 23),
    arrival_after: time | None = None,
    show_models: bool = False,
) -> None:
    console.print("[bold]Mt Fuji Model Consensus[/bold]")
    console.print("Consensus is equal-weighted and separate from forecast quality.")
    for target_date, result in daily_results:
        console.print()
        console.print(f"[bold]{target_date.strftime('%a %Y-%m-%d').upper()}[/bold]")
        table = Table(show_header=True, header_style="bold")
        for column in (
            "Time",
            "Reach",
            "Models",
            "Full",
            "Proxy median",
            "Range",
            "Mid cloud",
            "Visibility",
            "Consensus",
        ):
            table.add_column(column)
        detail_lines: list[str] = []
        agreement_lines: list[str] = []
        for hour in result.hours:
            local = to_jst(hour.valid_time)
            if local.date() != target_date or not (hours[0] <= local.hour <= hours[1]):
                continue
            reachable = arrival_after is None or local.time().replace(second=0, microsecond=0) >= arrival_after
            reach_text = Text("yes" if reachable else "no", style="green" if reachable else "dim")
            proxy_range = (
                f"{hour.proxy_min:.0f}–{hour.proxy_max:.0f}"
                if hour.proxy_min is not None and hour.proxy_max is not None
                else MISSING
            )
            table.add_row(
                local.strftime("%H:%M"),
                reach_text,
                str(hour.model_count),
                str(hour.full_model_count),
                fmt(hour.proxy_median, 0),
                proxy_range,
                fmt(hour.mid_cloud_median, 0, "%"),
                fmt(hour.visibility_median_km, 1, " km"),
                hour.consensus_label,
            )
            agreement_lines.append(
                f"  {local:%H:%M} agreement: "
                f"Proxy {hour.models_good_proxy}/{hour.full_model_count}, "
                f"mid cloud {hour.models_good_mid_cloud}/{hour.model_count}, "
                f"visibility {hour.models_good_visibility}/{hour.full_model_count}, "
                f"Proxy σ {fmt(hour.proxy_stddev, 1)}"
            )
            if show_models:
                for member in hour.members:
                    flag = " OUTLIER" if member.outlier else ""
                    detail_lines.append(
                        f"  {local:%H:%M} {member.model:<18} "
                        f"Proxy {fmt(member.proxy.score, 0)}  "
                        f"Mid {fmt(member.record.cloud_mid_pct, 0, '%')}  "
                        f"Vis {fmt(member.record.visibility_km, 1, ' km')}{flag}"
                    )
        console.print(table)
        for line in agreement_lines:
            console.print(line)
        if detail_lines:
            console.print("Model details:")
            for line in detail_lines:
                console.print(line)
        if result.failures:
            console.print(f"Skipped models: {len(result.failures)}")
            for failure in result.failures:
                console.print(f"  {failure.model}: {failure.reason}")
        partials = [member for member in result.members if not member.full_forecast]
        if partials:
            console.print(f"Partial models: {len(partials)}")
            for member in partials:
                missing = sorted(
                    member.capability.missing_required | member.capability.missing_optional
                )
                console.print(f"  {member.model}: missing {', '.join(missing) or 'proxy fields'}")


def render_decision(
    console: Console,
    result: DecisionResult,
    *,
    location_name: str,
    arrival_after: time | None,
) -> None:
    console.print("[bold]Mt Fuji Decision[/bold]")
    console.print(f"Location: {location_name}")
    if arrival_after is not None:
        console.print(f"Reachable from: {arrival_after:%H:%M} JST")
    console.print()
    if result.no_clear_winner:
        console.print("[bold yellow]NO CLEAR WINNER[/bold yellow]")
        for reason in result.rationale:
            console.print(f"- {reason}")
    elif result.winner is None and result.promising_winner is not None:
        console.print(
            f"[bold cyan]PROMISING: {result.promising_winner.date.strftime('%a %Y-%m-%d').upper()}[/bold cyan]"
        )
        _render_decision_window(
            console,
            result.promising_winner.best_promising_window,
            heading="Promising reachable window",
            good_proxy=result.min_proxy,
        )
        console.print("Why this window is worth watching:")
        for reason in result.rationale:
            console.print(f"- {reason}")
    elif result.winner is not None and result.winner.best_window is not None:
        winner = result.winner
        window = winner.best_window
        console.print(f"[bold green]RECOMMENDED: {winner.date.strftime('%a %Y-%m-%d').upper()}[/bold green]")
        _render_decision_window(
            console,
            window,
            heading="Best reachable window",
            good_proxy=result.min_proxy,
        )
        console.print("Why this day wins:")
        for reason in result.rationale:
            console.print(f"- {reason}")
    elif result.insufficient_evidence:
        console.print("[bold yellow]INSUFFICIENT EVIDENCE[/bold yellow]")
        for reason in result.rationale:
            console.print(f"- {reason}")
    else:
        console.print("[bold yellow]NO QUALIFYING WINDOW[/bold yellow]")
        for reason in result.rationale:
            console.print(f"- {reason}")
    for day in result.days:
        console.print()
        console.print(f"[bold]{day.date.strftime('%a %Y-%m-%d').upper()}[/bold]")
        window = day.best_window or day.best_promising_window
        if window is None:
            console.print(
                "Not enough core forecast evidence."
                if day.hours and all(item.status == "INSUFFICIENT_CORE_DATA" for item in day.hours)
                else "No reachable qualifying window."
            )
            continue
        _render_decision_window(
            console,
            window,
            heading=("Best reachable window" if day.best_window is not None else "Promising reachable window"),
            good_proxy=result.min_proxy,
        )


def _render_decision_window(
    console: Console,
    window: DecisionWindow | None,
    *,
    heading: str,
    good_proxy: float,
) -> None:
    if window is None:
        console.print("No window details are available.")
        return
    console.print(f"{heading}: {format_time_window(window.start, window.end)}")
    console.print(
        f"Peak: {to_jst(window.peak.consensus.valid_time):%H:%M} | "
        f"Proxy median: {window.peak_proxy:.0f} | "
        f"Consensus: {window.consensus_label} | "
        f"Status: {window.status} | "
        f"Confidence: {window.confidence} | "
        f"Forecast stability: {window.stability_confidence} | "
        f"Trend: {window.trend_label}"
    )
    console.print(
        f"Model agreement: {window.peak.consensus.models_good_proxy}/"
        f"{window.peak.consensus.full_model_count} models Proxy >= {good_proxy:g} | "
        f"Proxy range: {fmt(window.peak.consensus.proxy_min, 0)}–"
        f"{fmt(window.peak.consensus.proxy_max, 0)}"
    )
    console.print(
        f"Weather: Mid cloud median {fmt(window.peak.consensus.mid_cloud_median, 0, '%')}, "
        f"visibility median {fmt(window.peak.consensus.visibility_median_km, 1, ' km')}, "
        f"rain median {fmt(window.peak.consensus.precip_median, 0, '%')}"
    )
    for field_name, evidence in window.peak.consensus.field_consensus.items():
        console.print(
            f"{field_name}: {evidence.support} ({evidence.good_votes}/{evidence.model_count} good)"
        )
    if window.mid_cloud_max is not None and window.mid_cloud_max > (window.peak.consensus.mid_cloud_median or 0):
        console.print(f"Main risk: mid-level cloud reaches {window.mid_cloud_max:.0f}% within the window.")
    elif window.visibility_min is not None and window.visibility_min < (window.peak.consensus.visibility_median_km or float('inf')):
        console.print(f"Main risk: visibility falls to {window.visibility_min:.1f} km within the window.")
    else:
        console.print("Main risk: no dominant worsening variable in the selected window.")


def render_fingerprint(
    console: Console,
    result: FingerprintSearchResult,
    *,
    limit: int = 10,
    history: bool = False,
) -> None:
    console.print(
        f"[bold]Fingerprint candidates ({'historical runs' if history else 'live forecast'})[/bold]"
    )
    console.print(f"Requests attempted: {result.attempted_requests}")
    table = Table(show_header=True, header_style="bold")
    for column in ("Rank", "Coord", "Model", "Run", "Cloud mapping", "Error"):
        table.add_column(column)
    for index, candidate in enumerate(result.candidates[:limit], start=1):
        run = "—" if candidate.run is None else f"{to_jst(candidate.run):%Y-%m-%d %H:%M} JST"
        table.add_row(
            str(index),
            f"{candidate.latitude:.3f},{candidate.longitude:.3f}",
            candidate.model,
            run,
            candidate.cloud_mapping,
            f"{candidate.error:.2f}",
        )
    console.print(table)
    for index, candidate in enumerate(result.candidates[:limit], start=1):
        console.print(f"Candidate {index} residuals:")
        for residual in candidate.residuals:
            console.print(
                f"  {to_jst(residual.valid_time):%Y-%m-%d %H:%M} — "
                f"temp {residual.temperature:+.2f}°C, cloud {residual.cloud:+.1f}pp, "
                f"visibility {residual.visibility:+.1f}km, point {residual.point_error:.2f}"
            )
    if not result.candidates:
        console.print("No complete candidates matched. Check the API/model errors below.")
    if result.failures:
        console.print(f"Skipped candidates/mappings: {len(result.failures)}")
        for failure in result.failures[:5]:
            run = "" if failure.run is None else f" run={failure.run.isoformat()}"
            console.print(
                f"  {failure.latitude:.3f},{failure.longitude:.3f} {failure.model}{run}: "
                f"{failure.reason}"
            )


def render_previous_runs(console: Console, points: Iterable[PreviousRunPoint], hour: int) -> None:
    selected = sorted(
        [point for point in points if to_jst(point.valid_time).hour == hour],
        key=lambda point: point.day_offset,
    )
    table = Table(show_header=True, header_style="bold")
    for column in ("Run offset", "Temp", "Mid cloud", "Visibility", "RH", "Rain"):
        table.add_column(column)
    for point in selected:
        table.add_row(
            "current" if point.day_offset == 0 else f"previous_day{point.day_offset}",
            fmt(point.temperature_c, 1, "°C"),
            fmt(point.cloud_mid_pct, 0, "%"),
            fmt(point.visibility_km, 1, " km"),
            fmt(point.relative_humidity_pct, 0, "%"),
            fmt(point.precipitation_probability_pct, 0, "%"),
        )
    console.print(table)


def _render_metadata(console: Console, result: ForecastResult) -> None:
    console.print(
        f"Source: Open-Meteo | Model: {result.model}"
        + (f" (response {result.resolved_model})" if result.resolved_model else "")
    )
    console.print(f"Retrieved: {display_datetime(result.retrieved_at)}")


def _render_day_table(console: Console, comparison: DayComparison) -> None:
    table = Table(show_header=True, header_style="bold")
    for column in (
        "Time",
        "Reach",
        "Temp °C",
        "Total %",
        "Low %",
        "Mid %",
        "High %",
        "Vis km",
        "RH %",
        "Rain %",
        "Proxy",
    ):
        table.add_column(column)
    for assessment in comparison.assessments:
        row = assessment.record
        reach = Text("yes" if assessment.reachable else "no", style="green" if assessment.reachable else "dim")
        table.add_row(
            to_jst(row.valid_time).strftime("%H:%M"),
            reach,
            fmt(row.temperature_c, 1),
            fmt(row.cloud_total_pct, 0, "%"),
            fmt(row.cloud_low_pct, 0, "%"),
            fmt(row.cloud_mid_pct, 0, "%"),
            fmt(row.cloud_high_pct, 0, "%"),
            fmt(row.visibility_km, 1),
            fmt(row.relative_humidity_pct, 0, "%"),
            fmt(row.precipitation_probability_pct, 0, "%"),
            fmt(assessment.score.score, 0),
        )
    console.print(table)
    for assessment in comparison.assessments:
        if assessment.score.missing_fields:
            console.print(
                f"{to_jst(assessment.record.valid_time):%H:%M}: "
                f"Proxy unavailable; missing {', '.join(assessment.score.missing_fields)}."
            )


def _render_best_window(console: Console, comparison: DayComparison) -> None:
    if comparison.best_window is None:
        console.print("Best reachable window: unavailable")
        return
    window = comparison.best_window
    console.print(
        f"Best reachable window: {format_time_window(window.start, window.end)} | "
        f"peak {to_jst(window.peak.record.valid_time):%H:%M} — "
        f"Fuji Proxy {window.peak.score.score:.0f}"
    )


def format_time_window(start: datetime, end: datetime) -> str:
    local_start, local_end = to_jst(start), to_jst(end)
    if local_start.date() == local_end.date():
        return f"{local_start:%a %b %d, %H:%M}–{local_end:%H:%M} JST"
    return f"{local_start:%Y-%m-%d %H:%M}–{local_end:%Y-%m-%d %H:%M} JST"


def _trend_samples(metrics: TrendMetrics) -> list[tuple[datetime, float | None, float | None, float | None, float | None, float | None]]:
    values = []
    for assessment in metrics.assessments:
        values.append(
            (
                assessment.record.retrieved_at,
                assessment.record.cloud_mid_pct,
                assessment.record.visibility_km,
                assessment.record.relative_humidity_pct,
                assessment.record.precipitation_probability_pct,
                assessment.score.score,
            )
        )
    return values
