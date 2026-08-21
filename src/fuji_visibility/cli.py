"""The ``fuji`` command-line interface."""

from __future__ import annotations

import logging
import json
from datetime import datetime, time, timezone
from pathlib import Path
from typing import NoReturn

import typer
from rich.console import Console

from .comparison import assess_day, compare_results, parse_hour_range
from .consensus import ConsensusFetcher, ConsensusResult
from .config import (
    DEFAULT_CLOUD_MAPPINGS,
    DEFAULT_CANDIDATE_MODELS,
    DEFAULT_DATABASE_PATH,
    DEFAULT_LOCATION,
    DEFAULT_RAW_DATA_PATH,
    DECISION_MIN_WINDOW_HOURS,
    GOOD_PROXY_THRESHOLD,
    LOCATION_PRESETS,
    REQUEST_TIMEOUT_SECONDS,
)
from .decision import decide_days, decision_payload
from .fingerprint import FingerprintSearcher, load_fingerprint
from .formatting import (
    render_comparison,
    render_consensus,
    render_decision,
    render_fingerprint,
    render_forecast,
    render_previous_runs,
    render_stability,
)
from .exporting import export_consensus_text, export_text, select_rows
from .open_meteo import OpenMeteoClient, OpenMeteoError
from .services import fetch_consensus_days as fetch_service_consensus_days
from .storage import ForecastStore, StorageError
from .stability import consensus_stability, model_stability
from .time_utils import JST, canonical_iso, iter_run_times, parse_clock, parse_date, parse_datetime

app = typer.Typer(
    name="fuji",
    help="Inspect hourly Open-Meteo inputs behind Mt. Fuji visibility decisions.",
    no_args_is_help=True,
)
console = Console()
error_console = Console(stderr=True)
logger = logging.getLogger(__name__)
_RUNTIME_OPTIONS: dict[str, object] = {
    "verbose": False,
    "db_path": DEFAULT_DATABASE_PATH,
    "raw_dir": DEFAULT_RAW_DATA_PATH,
}


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", help="Show API and persistence diagnostics."),
    db_path: Path = typer.Option(
        DEFAULT_DATABASE_PATH,
        "--db-path",
        help="SQLite database path used by snapshot/trend.",
    ),
    raw_dir: Path = typer.Option(
        DEFAULT_RAW_DATA_PATH,
        "--raw-dir",
        help="Directory for retained raw Open-Meteo JSON.",
    ),
) -> None:
    _RUNTIME_OPTIONS.update(verbose=verbose, db_path=db_path, raw_dir=raw_dir)
    if verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


@app.command()
def locations() -> None:
    """List editable named coordinate presets."""

    for preset in LOCATION_PRESETS.values():
        console.print(
            f"{preset.name:12} {preset.latitude:.3f},{preset.longitude:.3f} — {preset.description}"
        )


@app.command()
def forecast(
    date_value: str = typer.Argument(..., metavar="DATE", help="Local date, YYYY-MM-DD."),
    location: str = typer.Option(DEFAULT_LOCATION, "--location", help="Named location preset."),
    lat: float | None = typer.Option(None, "--lat", help="Custom latitude; use with --lon."),
    lon: float | None = typer.Option(None, "--lon", help="Custom longitude; use with --lat."),
    hours: str = typer.Option("0-23", "--hours", help="Inclusive local hour range, e.g. 5-12."),
    model: str = typer.Option("auto", "--model", help="auto or an explicit Open-Meteo model."),
    cloud_strategy: str = typer.Option("mid", "--cloud-strategy", help="Fuji Proxy cloud strategy."),
) -> None:
    """Display one date hour by hour."""

    target_date = _parse_date_or_exit(date_value)
    start_hour, end_hour = _parse_hours_or_exit(hours)
    latitude, longitude, location_name = _resolve_location_or_exit(location, lat, lon)
    try:
        with OpenMeteoClient(verbose=_verbose(), timeout=REQUEST_TIMEOUT_SECONDS) as client:
            result = client.fetch_forecast(
                latitude,
                longitude,
                model=model,
                start_date=target_date,
                end_date=target_date,
            )
        comparison = assess_day(
            result,
            target_date,
            hours=(start_hour, end_hour),
            cloud_strategy=cloud_strategy,
        )
        render_forecast(console, result, comparison, title=f"Mt Fuji Visibility — {location_name}")
    except (OpenMeteoError, ValueError) as exc:
        _exit_with_error(exc)


@app.command("export")
def export_data(
    date_value: str = typer.Argument(..., metavar="DATE", help="Local date, YYYY-MM-DD."),
    second_date_value: str | None = typer.Argument(None, metavar="DATE2"),
    third_date_value: str | None = typer.Argument(None, metavar="DATE3"),
    export_format: str = typer.Option("csv", "--format", help="csv or json."),
    output: str = typer.Option("-", "--output", help="Output file, or - for stdout."),
    location: str = typer.Option(DEFAULT_LOCATION, "--location"),
    lat: float | None = typer.Option(None, "--lat"),
    lon: float | None = typer.Option(None, "--lon"),
    hours: str = typer.Option("0-23", "--hours"),
    model: str = typer.Option("auto", "--model"),
    models: str | None = typer.Option(None, "--models", help="Consensus models or all."),
    cloud_strategy: str = typer.Option("mid", "--cloud-strategy"),
    arrival_after: str | None = typer.Option(None, "--arrival-after"),
) -> None:
    """Export normalized hourly rows or derived consensus diagnostics as CSV/JSON."""

    hour_range = _parse_hours_or_exit(hours)
    latitude, longitude, location_name = _resolve_location_or_exit(location, lat, lon)
    try:
        if date_value.lower() == "consensus":
            if second_date_value is None or third_date_value is None:
                raise ValueError(
                    "consensus export requires: export consensus DATE1 DATE2"
                )
            first_date = _parse_date_or_exit(second_date_value)
            second_date = _parse_date_or_exit(third_date_value)
            arrival = _parse_clock_or_exit(arrival_after) if arrival_after else None
            daily_results = _fetch_consensus_days(
                latitude,
                longitude,
                (first_date, second_date),
                models=_resolve_models(models or "all", model),
                cloud_strategy=cloud_strategy,
                hours=hour_range,
            )
            rendered = export_consensus_text(
                daily_results,
                export_format=export_format.lower(),
                hours=hour_range,
                arrival_after=arrival,
            )
            if output == "-":
                typer.echo(rendered, nl=False)
            else:
                output_path = Path(output).expanduser()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(rendered, encoding="utf-8")
                console.print(f"Exported consensus diagnostics to {output_path}")
            return
        if second_date_value is not None or third_date_value is not None:
            raise ValueError("single-date export accepts only one DATE argument")
        target_date = _parse_date_or_exit(date_value)
        if models is not None:
            raise ValueError("--models is only supported by consensus export")
        result = _fetch_day(latitude, longitude, target_date, model=model)
        rows = select_rows(result, target_date, hours=hour_range)
        rendered = export_text(
            result,
            rows,
            export_format=export_format.lower(),
            cloud_strategy=cloud_strategy,
        )
        if output == "-":
            typer.echo(rendered, nl=False)
        else:
            output_path = Path(output).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
            console.print(f"Exported {len(rows)} rows for {location_name} to {output_path}")
    except (OpenMeteoError, ValueError, OSError) as exc:
        _exit_with_error(exc)


@app.command()
def compare(
    first_date_value: str = typer.Argument(..., metavar="DATE1"),
    second_date_value: str = typer.Argument(..., metavar="DATE2"),
    location: str = typer.Option(DEFAULT_LOCATION, "--location"),
    lat: float | None = typer.Option(None, "--lat"),
    lon: float | None = typer.Option(None, "--lon"),
    hours: str = typer.Option("0-23", "--hours", help="Inclusive local hour range."),
    arrival_after: str | None = typer.Option(
        None,
        "--arrival-after",
        help="Arrival cutoff such as 08:00; earlier hours cannot win the recommendation.",
    ),
    model: str = typer.Option("auto", "--model"),
    cloud_strategy: str = typer.Option("mid", "--cloud-strategy"),
    window_tolerance: float = typer.Option(
        10.0,
        "--window-tolerance",
        help="Include adjacent reachable hours within this many Proxy points of the peak.",
    ),
) -> None:
    """Compare two dates and select the best reachable window."""

    first_date = _parse_date_or_exit(first_date_value)
    second_date = _parse_date_or_exit(second_date_value)
    hour_range = _parse_hours_or_exit(hours)
    arrival = _parse_clock_or_exit(arrival_after) if arrival_after else None
    latitude, longitude, location_name = _resolve_location_or_exit(location, lat, lon)
    try:
        with OpenMeteoClient(verbose=_verbose(), timeout=REQUEST_TIMEOUT_SECONDS) as client:
            first = client.fetch_forecast(
                latitude,
                longitude,
                model=model,
                start_date=first_date,
                end_date=first_date,
            )
            second = client.fetch_forecast(
                latitude,
                longitude,
                model=model,
                start_date=second_date,
                end_date=second_date,
            )
        comparisons = compare_results(
            first,
            second,
            first_date,
            second_date,
            hours=hour_range,
            arrival_after=arrival,
            cloud_strategy=cloud_strategy,
            window_tolerance=window_tolerance,
        )
        render_comparison(
            console,
            (first, second),
            comparisons,
            location_name=location_name,
            cloud_strategy=cloud_strategy,
        )
    except (OpenMeteoError, ValueError) as exc:
        _exit_with_error(exc)


@app.command()
def consensus(
    first_date_value: str = typer.Argument(..., metavar="DATE1"),
    second_date_value: str = typer.Argument(..., metavar="DATE2"),
    location: str = typer.Option(DEFAULT_LOCATION, "--location"),
    lat: float | None = typer.Option(None, "--lat"),
    lon: float | None = typer.Option(None, "--lon"),
    hours: str = typer.Option("0-23", "--hours"),
    arrival_after: str | None = typer.Option(None, "--arrival-after"),
    models: str | None = typer.Option(None, "--models", help="Comma-separated models or all."),
    cloud_strategy: str = typer.Option("mid", "--cloud-strategy"),
    show_models: bool = typer.Option(False, "--show-models", help="Show each model's hourly values."),
) -> None:
    """Compare two dates using equal-weighted multi-model consensus."""

    first_date = _parse_date_or_exit(first_date_value)
    second_date = _parse_date_or_exit(second_date_value)
    hour_range = _parse_hours_or_exit(hours)
    arrival = _parse_clock_or_exit(arrival_after) if arrival_after else None
    latitude, longitude, location_name = _resolve_location_or_exit(location, lat, lon)
    try:
        daily_results = _fetch_consensus_days(
            latitude,
            longitude,
            (first_date, second_date),
            models=_resolve_models(models or "all", "auto"),
            cloud_strategy=cloud_strategy,
            hours=hour_range,
        )
        render_consensus(
            console,
            daily_results,
            hours=hour_range,
            arrival_after=arrival,
            show_models=show_models,
        )
        console.print(f"Location: {location_name}")
    except (OpenMeteoError, ValueError) as exc:
        _exit_with_error(exc)


@app.command()
def decide(
    dates: str = typer.Option(..., "--dates", help="Comma-separated candidate dates."),
    location: str = typer.Option(DEFAULT_LOCATION, "--location"),
    lat: float | None = typer.Option(None, "--lat"),
    lon: float | None = typer.Option(None, "--lon"),
    hours: str = typer.Option("0-23", "--hours"),
    arrival_after: str | None = typer.Option(None, "--arrival-after"),
    models: str | None = typer.Option(None, "--models", help="Comma-separated models or all."),
    min_window_hours: int = typer.Option(DECISION_MIN_WINDOW_HOURS, "--min-window-hours", min=1),
    good_proxy: float = typer.Option(GOOD_PROXY_THRESHOLD, "--good-proxy"),
    cloud_strategy: str = typer.Option("mid", "--cloud-strategy"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Recommend a reachable day using consensus, stability, and window length."""

    date_values = _csv(dates)
    if len(date_values) < 2:
        _exit_with_error(ValueError("--dates requires at least two comma-separated dates"))
    target_dates = [_parse_date_or_exit(value) for value in date_values]
    hour_range = _parse_hours_or_exit(hours)
    arrival = _parse_clock_or_exit(arrival_after) if arrival_after else None
    latitude, longitude, location_name = _resolve_location_or_exit(location, lat, lon)
    try:
        daily_results = _fetch_consensus_days(
            latitude,
            longitude,
            tuple(target_dates),
            models=_resolve_models(models or "all", "auto"),
            cloud_strategy=cloud_strategy,
            hours=hour_range,
        )
        stability_by_time: dict[str, object] = {}
        with ForecastStore(_db_path()) as store:
            for target_date, consensus_result in daily_results:
                for hour in consensus_result.hours:
                    local = hour.valid_time.astimezone(JST)
                    if local.date() != target_date or not (hour_range[0] <= local.hour <= hour_range[1]):
                        continue
                    rows = store.trend(
                        hour.valid_time.isoformat(),
                        latitude=latitude,
                        longitude=longitude,
                        model=None,
                    )
                    stability_by_time[canonical_iso(hour.valid_time)] = consensus_stability(
                        rows,
                        cloud_strategy=cloud_strategy,
                    )
        decision_result = decide_days(
            daily_results,
            arrival_after=arrival,
            hours=hour_range,
            stability_by_time=stability_by_time,
            min_proxy=good_proxy,
            min_window_hours=min_window_hours,
        )
        if json_output:
            typer.echo(json.dumps(decision_payload(decision_result), ensure_ascii=False, indent=2))
        else:
            render_decision(
                console,
                decision_result,
                location_name=location_name,
                arrival_after=arrival,
            )
    except (OpenMeteoError, StorageError, ValueError) as exc:
        _exit_with_error(exc)


@app.command()
def snapshot(
    location: str = typer.Option(DEFAULT_LOCATION, "--location"),
    lat: float | None = typer.Option(None, "--lat"),
    lon: float | None = typer.Option(None, "--lon"),
    days: int = typer.Option(7, "--days", min=1, max=16, help="Forecast horizon to save."),
    model: str = typer.Option("auto", "--model"),
    models: str | None = typer.Option(None, "--models", help="Comma-separated models or all."),
) -> None:
    """Fetch and persist one or more model forecasts plus raw JSON responses."""

    latitude, longitude, location_name = _resolve_location_or_exit(location, lat, lon)
    try:
        with OpenMeteoClient(verbose=_verbose(), timeout=REQUEST_TIMEOUT_SECONDS) as client:
            fetcher = ConsensusFetcher(client)
            consensus_result = fetcher.fetch(
                latitude,
                longitude,
                models=_resolve_models(models, model),
                model_kwargs={"forecast_days": days},
            )
        if not consensus_result.members:
            detail = "; ".join(
                f"{failure.model}: {failure.reason}" for failure in consensus_result.failures
            )
            raise OpenMeteoError(f"No requested snapshot model succeeded. {detail}")
        with ForecastStore(_db_path()) as store:
            for member in consensus_result.members:
                snapshot_id = store.save_forecast(
                    member.forecast,
                    raw_directory=_raw_dir(),
                    save_raw=True,
                )
                missing = sorted(member.capability.missing_required | member.capability.missing_optional)
                suffix = f"; missing fields: {', '.join(missing)}" if missing else ""
                console.print(
                    f"Saved snapshot {snapshot_id} ({member.model}) for {location_name}: "
                    f"{len(member.forecast.hours)} hourly rows{suffix}."
                )
            if consensus_result.failures:
                console.print(f"Skipped models: {len(consensus_result.failures)}")
                for failure in consensus_result.failures:
                    console.print(f"  {failure.model}: {failure.reason}")
            console.print(f"Raw response directory: {_raw_dir()}")
            console.print(f"Database: {_db_path()}")
    except (OpenMeteoError, StorageError, ValueError) as exc:
        _exit_with_error(exc)


@app.command()
def trend(
    date_value: str = typer.Argument(..., metavar="DATE"),
    hour: str = typer.Option(..., "--hour", help="Local hour such as 09:00."),
    location: str = typer.Option(DEFAULT_LOCATION, "--location"),
    lat: float | None = typer.Option(None, "--lat"),
    lon: float | None = typer.Option(None, "--lon"),
    model: str | None = typer.Option(None, "--model", help="Filter saved snapshots by requested model."),
    cloud_strategy: str = typer.Option("mid", "--cloud-strategy"),
    consensus: bool = typer.Option(False, "--consensus", help="Aggregate saved model snapshots."),
) -> None:
    """Show saved forecast drift for one model or the model consensus."""

    target_date = _parse_date_or_exit(date_value)
    target_time = _parse_clock_or_exit(hour)
    latitude, longitude, _ = _resolve_location_or_exit(location, lat, lon)
    target = datetime.combine(target_date, target_time).replace(tzinfo=JST)
    try:
        with ForecastStore(_db_path()) as store:
            rows = store.trend(
                target.isoformat(),
                latitude=latitude,
                longitude=longitude,
                model=None if consensus else (model or "auto"),
            )
        if consensus:
            metrics = consensus_stability(rows, cloud_strategy=cloud_strategy)
        else:
            metrics = model_stability(rows, cloud_strategy=cloud_strategy)
        render_stability(console, metrics, valid_time=target, consensus=consensus)
    except (StorageError, ValueError) as exc:
        _exit_with_error(exc)


@app.command()
def fingerprint(
    input_path: Path = typer.Option(..., "--input", exists=True, readable=True, help="Fingerprint JSON."),
    lat_center: float = typer.Option(35.52, "--lat-center"),
    lon_center: float = typer.Option(138.75, "--lon-center"),
    radius_deg: float = typer.Option(0.04, "--radius-deg"),
    step_deg: float = typer.Option(0.01, "--step-deg"),
    models: str = typer.Option(",".join(DEFAULT_CANDIDATE_MODELS), "--models"),
    cloud_mappings: str = typer.Option(",".join(DEFAULT_CLOUD_MAPPINGS), "--cloud-mappings"),
    limit: int = typer.Option(10, "--limit", min=1, max=100),
) -> None:
    """Rank live coordinate/model/cloud interpretations against observations."""

    try:
        fingerprint_data = load_fingerprint(input_path)
        with OpenMeteoClient(verbose=_verbose(), timeout=REQUEST_TIMEOUT_SECONDS) as client:
            searcher = FingerprintSearcher(client, progress=logger.info if _verbose() else None)
            result = searcher.search_live(
                fingerprint_data,
                latitude_center=lat_center,
                longitude_center=lon_center,
                radius_deg=radius_deg,
                step_deg=step_deg,
                models=_csv(models),
                cloud_mappings=_csv(cloud_mappings),
            )
        render_fingerprint(console, result, limit=limit)
    except (OpenMeteoError, ValueError) as exc:
        _exit_with_error(exc)


@app.command("fingerprint-history")
def fingerprint_history(
    input_path: Path = typer.Option(..., "--input", exists=True, readable=True),
    search_from: str = typer.Option(..., "--search-from", help="UTC/ISO run start."),
    search_to: str = typer.Option(..., "--search-to", help="UTC/ISO run end."),
    run_interval_hours: int = typer.Option(6, "--run-interval-hours", min=1, max=24),
    lat_center: float = typer.Option(35.52, "--lat-center"),
    lon_center: float = typer.Option(138.75, "--lon-center"),
    radius_deg: float = typer.Option(0.04, "--radius-deg"),
    step_deg: float = typer.Option(0.01, "--step-deg"),
    models: str = typer.Option(",".join(DEFAULT_CANDIDATE_MODELS), "--models"),
    cloud_mappings: str = typer.Option(",".join(DEFAULT_CLOUD_MAPPINGS), "--cloud-mappings"),
    limit: int = typer.Option(10, "--limit", min=1, max=100),
) -> None:
    """Search archived Single Runs around a screenshot capture time."""

    try:
        fingerprint_data = load_fingerprint(input_path)
        start = parse_datetime(search_from, default_zone=timezone.utc).astimezone(timezone.utc)
        end = parse_datetime(search_to, default_zone=timezone.utc).astimezone(timezone.utc)
        runs = iter_run_times(start, end, interval_hours=run_interval_hours)
        if not runs:
            raise ValueError("the requested historical search range contains no aligned run times")
        with OpenMeteoClient(verbose=_verbose(), timeout=REQUEST_TIMEOUT_SECONDS) as client:
            searcher = FingerprintSearcher(client, progress=logger.info if _verbose() else None)
            result = searcher.search_history(
                fingerprint_data,
                runs=runs,
                latitude_center=lat_center,
                longitude_center=lon_center,
                radius_deg=radius_deg,
                step_deg=step_deg,
                models=_csv(models),
                cloud_mappings=_csv(cloud_mappings),
            )
        render_fingerprint(console, result, limit=limit, history=True)
    except (OpenMeteoError, ValueError) as exc:
        _exit_with_error(exc)


@app.command("previous-runs")
def previous_runs(
    date_value: str = typer.Argument(..., metavar="DATE"),
    hour: str = typer.Option(..., "--hour"),
    location: str = typer.Option(DEFAULT_LOCATION, "--location"),
    lat: float | None = typer.Option(None, "--lat"),
    lon: float | None = typer.Option(None, "--lon"),
    model: str = typer.Option("auto", "--model"),
    max_day: int = typer.Option(7, "--max-day", min=0, max=7),
) -> None:
    """Compare current and fixed-lead Previous Runs values."""

    target_date = _parse_date_or_exit(date_value)
    target_hour = _parse_clock_or_exit(hour)
    latitude, longitude, _ = _resolve_location_or_exit(location, lat, lon)
    try:
        with OpenMeteoClient(verbose=_verbose(), timeout=REQUEST_TIMEOUT_SECONDS) as client:
            points = client.fetch_previous_runs(
                latitude,
                longitude,
                model=model,
                start_date=target_date,
                end_date=target_date,
                max_day=max_day,
            )
        render_previous_runs(console, points, target_hour.hour)
    except (OpenMeteoError, ValueError) as exc:
        _exit_with_error(exc)


def _resolve_location_or_exit(
    location: str, lat: float | None, lon: float | None
) -> tuple[float, float, str]:
    if (lat is None) != (lon is None):
        _exit_with_error(ValueError("--lat and --lon must be supplied together"))
    if lat is not None and lon is not None:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            _exit_with_error(ValueError("coordinates are outside valid WGS84 ranges"))
        return lat, lon, f"custom {lat:.3f},{lon:.3f}"
    preset = LOCATION_PRESETS.get(location.lower())
    if preset is None:
        names = ", ".join(sorted(LOCATION_PRESETS))
        _exit_with_error(ValueError(f"unknown location {location!r}; choose one of: {names}"))
    return preset.latitude, preset.longitude, preset.name


def _fetch_day(
    latitude: float,
    longitude: float,
    target_date,
    *,
    model: str,
):
    with OpenMeteoClient(verbose=_verbose(), timeout=REQUEST_TIMEOUT_SECONDS) as client:
        return client.fetch_forecast(
            latitude,
            longitude,
            model=model,
            start_date=target_date,
            end_date=target_date,
        )


def _resolve_models(models: str | None, model: str = "auto") -> list[str]:
    if models is None:
        return [model]
    if model != "auto":
        raise ValueError("use either --model or --models, not both")
    if models.strip().lower() == "all":
        return list(DEFAULT_CANDIDATE_MODELS)
    selected = _csv(models)
    if not selected:
        raise ValueError("--models must contain at least one model")
    return selected


def _fetch_consensus_days(
    latitude: float,
    longitude: float,
    dates: tuple[object, ...],
    *,
    models: list[str],
    cloud_strategy: str,
    hours: tuple[int, int],
) -> list[tuple[object, ConsensusResult]]:
    del hours  # The API request covers the whole target date; CLI filtering follows.
    return fetch_service_consensus_days(
        latitude,
        longitude,
        dates,
        models=models,
        cloud_strategy=cloud_strategy,
        verbose=_verbose(),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def _verbose() -> bool:
    return bool(_RUNTIME_OPTIONS.get("verbose", False))


def _db_path() -> Path:
    return Path(_RUNTIME_OPTIONS.get("db_path", DEFAULT_DATABASE_PATH))


def _raw_dir() -> Path:
    return Path(_RUNTIME_OPTIONS.get("raw_dir", DEFAULT_RAW_DATA_PATH))


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_date_or_exit(value: str):
    try:
        return parse_date(value)
    except ValueError as exc:
        _exit_with_error(ValueError(f"invalid date {value!r}; use YYYY-MM-DD"), cause=exc)


def _parse_hours_or_exit(value: str) -> tuple[int, int]:
    try:
        return parse_hour_range(value)
    except ValueError as exc:
        _exit_with_error(ValueError(f"invalid --hours {value!r}; use an inclusive range such as 5-12"), cause=exc)


def _parse_clock_or_exit(value: str) -> time:
    try:
        return parse_clock(value)
    except ValueError as exc:
        _exit_with_error(ValueError(f"invalid time {value!r}; use HH:MM"), cause=exc)


def _exit_with_error(message: Exception, *, cause: Exception | None = None) -> NoReturn:
    del cause
    error_console.print(f"Error: {message}")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
